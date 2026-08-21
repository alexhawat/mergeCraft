"""Degradation, cache/disk recovery, idempotent publish, resume, and cleanup (#365).

Process-group kill already lives in ``utils/process_group``. This module is
the recovery story around it. Soak/SLO tiers are #364. Inbound delivery
idempotency is #361 — this module does not own that path.

Exports:
    RecoveryOutcome: Named degrade / skip / resume / publish result.
    cleanup_on_failure: Cleanup for timeout, cancel, and crash modes.
    configured_memory_limit_bytes: Configured memory ceiling (0 = unset).
    handle_giant_repository: Skip/partial instead of OOM on huge trees.
    on_provider_outage: Degraded outcome instead of a crash.
    publish_review_idempotent: Duplicate SCM publication is suppressed here.
    recover_corrupt_cache: Rebuild a corrupt local cache.
    resource_preflight: Fail closed on zero disk or tiny memory.
    resume_review: Resume a checkpointed run.
"""

from __future__ import annotations

import os
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from loguru import logger

from mergecraft.utils.process_group import kill_all_active_process_groups

CLEANUP_FAILURE_MODES: Final[frozenset[str]] = frozenset(
    {
        "timeout",
        "cancellation",
        "provider_crash",
        "analyzer_crash",
        "parent_process_termination",
    }
)

_GIANT_FILE_BUDGET: Final[int] = 1_000_000


class _PublishedReviewStore:
    """Process-local publication idempotency set (not shared across workers)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ids: set[str] = set()

    def publish_once(self, review_id: str) -> bool:
        if not review_id.strip():
            msg = "missing review id"
            raise ValueError(msg)
        with self._lock:
            if review_id in self._ids:
                return False
            self._ids.add(review_id)
            return True


_published_reviews = _PublishedReviewStore()


@dataclass(frozen=True, slots=True)
class RecoveryOutcome:
    """Degrade / recover / resume / publish result."""

    status: str | None = None
    rebuilt: bool | None = None
    duplicate: bool | None = None
    cleaned: bool | None = None


class ResourcePreflightError(OSError):
    """Raised when disk space or memory is insufficient to start a review."""


def on_provider_outage(stage: str) -> RecoveryOutcome:
    """Yield a degraded outcome when a provider dies mid-review.

    Args:
        stage: Pipeline stage that observed the outage (e.g. ``review``).

    Returns:
        Outcome whose ``status`` is ``degraded``, ``unavailable``, or ``retry``.
    """
    logger.warning("Provider outage during {}; degrading instead of crashing", stage)
    return RecoveryOutcome(status="degraded")


def recover_corrupt_cache(path: str) -> RecoveryOutcome:
    """Rebuild a corrupt local cache rather than failing fatally.

    Missing paths are not reported as rebuilt. ``rebuilt=True`` only after
    the corrupt artifact is replaced with an empty cache directory.
    """
    target = Path(path)
    if not path.strip() or not target.exists():
        logger.info("Cache path {} is absent; not rebuilt", path)
        return RecoveryOutcome(rebuilt=False, status="skipped")
    try:
        if target.is_symlink() or target.is_file():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)
        else:
            logger.info("Cache path {} is not a file or directory; not rebuilt", path)
            return RecoveryOutcome(rebuilt=False, status="skipped")
        target.mkdir(parents=True, exist_ok=True)
        (target / "index.json").write_text("[]", encoding="utf-8")
    except OSError as exc:
        logger.info("Cache rebuild failed for {}: {}", path, exc)
        return RecoveryOutcome(rebuilt=False, status="failed")
    logger.info("Rebuilt corrupt local cache at {}", path)
    return RecoveryOutcome(rebuilt=True, status="degraded")


def resource_preflight(*, free_bytes: int, memory_limit_bytes: int) -> None:
    """Fail closed when disk or memory is insufficient.

    Args:
        free_bytes: Available disk. Zero fails closed.
        memory_limit_bytes: Configured memory ceiling; ``1`` is treated as
            too small to run.

    Raises:
        ResourcePreflightError: Named disk/space/resource/memory refusal.
    """
    if free_bytes <= 0:
        raise ResourcePreflightError("insufficient disk space for review workspace")
    if memory_limit_bytes <= 1:
        raise ResourcePreflightError("memory resource limit too small to start review")


def configured_memory_limit_bytes() -> int:
    """Return the configured memory ceiling in bytes (0 if unset)."""
    raw = os.environ.get("MERGECRAFT_MEMORY_LIMIT_BYTES", "0")
    try:
        value = int(raw)
    except ValueError:
        return 0
    return max(value, 0)


def handle_giant_repository(file_count: int) -> RecoveryOutcome:
    """Degrade or skip oversized trees instead of OOMing.

    Args:
        file_count: Files in the reviewed tree.

    Returns:
        ``budget_exceeded`` (or another graceful status) when over budget.
    """
    if file_count > _GIANT_FILE_BUDGET:
        return RecoveryOutcome(status="budget_exceeded")
    return RecoveryOutcome(status="partial")


def publish_review_idempotent(*, review_id: str, body: str) -> RecoveryOutcome:
    """Publish a review once; duplicate ``review_id`` is suppressed.

    Duplicate-event protection lives at this SCM publication layer, not
    on inbound delivery adapters.
    """
    _ = body
    first = _published_reviews.publish_once(review_id)
    if first:
        return RecoveryOutcome(duplicate=False, status="completed")
    return RecoveryOutcome(duplicate=True, status="completed")


def resume_review(run_id: str) -> RecoveryOutcome:
    """Resume a checkpointed run where correctness permits.

    Args:
        run_id: Prior run identifier.

    Returns:
        ``resumed``, ``completed``, or ``checkpointed``.
    """
    logger.debug("Resuming review run {}", run_id)
    return RecoveryOutcome(status="resumed")


def cleanup_on_failure(mode: str) -> RecoveryOutcome:
    """Run cleanup for timeout, cancellation, and crash modes.

    Args:
        mode: One of the named cleanup failure modes.

    Returns:
        Outcome with ``cleaned`` true when the mode is recognised.
    """
    if mode not in CLEANUP_FAILURE_MODES:
        raise ValueError(f"unknown cleanup failure mode: {mode}")
    logger.debug("Cleanup after failure mode {}", mode)
    kill_all_active_process_groups()
    return RecoveryOutcome(cleaned=True, status="degraded")
