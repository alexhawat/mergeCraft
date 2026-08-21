"""Local review-result cache, distinct from the ``mergecraft cache`` CLI typer (#378)."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from mergecraft.offline_review import OfflineReviewResult
from mergecraft.run_outcome import RunOutcome
from mergecraft.utils.run_bounds import resolve_run_bounds
from mergecraft.utils.run_cache import RunCache, default_cache_root, open_run_cache

if TYPE_CHECKING:
    from pathlib import Path

_KEY_PREFIX = "review-result:"


def review_result_cache_key(diff_bytes: bytes, *, model: str | None = None) -> str:
    """Return a cache key for a materialized review diff."""
    digest = hashlib.sha256(diff_bytes).hexdigest()
    model_part = model or ""
    return f"{_KEY_PREFIX}{digest}:{model_part}"


def _open_result_cache() -> RunCache:
    bounds = resolve_run_bounds()
    return open_run_cache(root=default_cache_root(), max_bytes=bounds.cache_max_bytes)


def load_review_result(key: str) -> OfflineReviewResult | None:
    """Load a previously cached review result, or ``None`` on miss/corrupt."""
    cache = _open_result_cache()
    raw = cache.get(key)
    if raw is None:
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        return None
    if not isinstance(payload, dict):
        return None
    outcome_raw = payload.get("outcome")
    outcome = RunOutcome(outcome_raw) if isinstance(outcome_raw, str) else None
    return OfflineReviewResult(
        success=bool(payload.get("success")),
        output=payload.get("output") if isinstance(payload.get("output"), str) else None,
        error=payload.get("error") if isinstance(payload.get("error"), str) else None,
        diff_path=payload.get("diff_path") if isinstance(payload.get("diff_path"), str) else None,
        empty_diff=bool(payload.get("empty_diff")),
        structured_output=(
            payload.get("structured_output")
            if isinstance(payload.get("structured_output"), str)
            else None
        ),
        evidence_packet_path=(
            payload.get("evidence_packet_path")
            if isinstance(payload.get("evidence_packet_path"), str)
            else None
        ),
        outcome=outcome,
    )


def store_review_result(key: str, result: OfflineReviewResult) -> None:
    """Persist a successful review result for later ``--use-cache`` / ``--resume`` hits."""
    payload = {
        "success": result.success,
        "output": result.output,
        "error": result.error,
        "diff_path": result.diff_path,
        "empty_diff": result.empty_diff,
        "structured_output": result.structured_output,
        "evidence_packet_path": result.evidence_packet_path,
        "outcome": result.outcome.value if result.outcome is not None else None,
    }
    cache = _open_result_cache()
    cache.put(key, json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def cache_key_for_diff_path(path: Path, *, model: str | None = None) -> str:
    """Hash an on-disk unified diff into a result-cache key."""
    return review_result_cache_key(path.read_bytes(), model=model)


__all__ = [
    "cache_key_for_diff_path",
    "load_review_result",
    "review_result_cache_key",
    "store_review_result",
]
