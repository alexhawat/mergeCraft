"""W14 / W18 — degradation, recovery, redacted diagnostic bundles (#365).

Out of scope: soak/SLO test tiers (#364); webhook transport idempotency (#361).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.cd_batch import (
    BUNDLE_MODULE,
    CLEANUP_FAILURE_MODES,
    RECOVERY_MODULE,
    require_callable,
    require_module,
)


def test_provider_outage_degrades_instead_of_crashing() -> None:
    """Happy: a mid-review provider outage yields a degraded outcome, not a crash."""
    module = require_module(RECOVERY_MODULE)
    degrade = require_callable(module, "on_provider_outage")
    outcome = degrade(stage="review")
    status = getattr(outcome, "status", None) or outcome.get("status")
    assert status in {"degraded", "unavailable", "retry"}


def test_local_cache_corruption_is_recoverable(tmp_path: Path) -> None:
    """Error: present corrupt cache is rebuilt; missing paths are not fake-passed."""
    module = require_module(RECOVERY_MODULE)
    recover = require_callable(module, "recover_corrupt_cache")
    missing = recover(path="not-a-real-cache")
    missing_rebuilt = getattr(missing, "rebuilt", None)
    if missing_rebuilt is None:
        missing_rebuilt = missing.get("rebuilt")
    assert missing_rebuilt is False
    cache = tmp_path / "corrupt-cache"
    cache.write_text("garbage", encoding="utf-8")
    result = recover(path=str(cache))
    rebuilt = getattr(result, "rebuilt", None)
    if rebuilt is None:
        rebuilt = result.get("rebuilt")
    assert rebuilt is True


def test_disk_space_and_resource_preflight_fail_closed() -> None:
    """Error: insufficient disk fails closed with a named message."""
    module = require_module(RECOVERY_MODULE)
    preflight = require_callable(module, "resource_preflight")
    with pytest.raises(
        (OSError, RuntimeError, ValueError),
        match=r"disk|space|resource|memory",
    ):
        preflight(free_bytes=0, memory_limit_bytes=1)


def test_memory_limits_are_honoured_where_deployment_permits() -> None:
    """Edge: a configured memory limit is exposed on the recovery surface."""
    module = require_module(RECOVERY_MODULE)
    limits = require_callable(module, "configured_memory_limit_bytes")()
    assert isinstance(limits, int)
    assert limits >= 0


def test_giant_repositories_are_handled_gracefully() -> None:
    """Happy: oversized repos degrade with a skip/partial rather than OOM."""
    module = require_module(RECOVERY_MODULE)
    handle = require_callable(module, "handle_giant_repository")
    outcome = handle(file_count=10_000_000)
    status = getattr(outcome, "status", None) or outcome.get("status")
    assert status in {"degraded", "skipped", "partial", "budget_exceeded"}


def test_scm_publication_is_idempotent_without_using_webhook_transport() -> None:
    """Happy: duplicate publication is suppressed at the SCM layer (#361 owns webhooks)."""
    module = require_module(RECOVERY_MODULE)
    publish = require_callable(module, "publish_review_idempotent")
    publish(review_id="r1", body="ok")
    second = publish(review_id="r1", body="ok")
    duplicate = getattr(second, "duplicate", None)
    if duplicate is None:
        duplicate = second.get("duplicate")
    assert duplicate is True
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "webhook" not in source.casefold() or "transport" not in source.casefold()


def test_execution_is_resumable_where_correctness_permits() -> None:
    """Happy: a checkpointed run can resume."""
    module = require_module(RECOVERY_MODULE)
    resume = require_callable(module, "resume_review")
    outcome = resume(run_id="run-1")
    status = getattr(outcome, "status", None) or outcome.get("status")
    assert status in {"resumed", "completed", "checkpointed"}


def test_diagnostic_bundle_redacts_secrets(tmp_path: Path) -> None:
    """Error: automatic bundles never contain secret material."""
    module = require_module(BUNDLE_MODULE)
    write = require_callable(module, "write_diagnostic_bundle")
    secret = "sk-bundle-leak-token-xyz"
    bundle = write(tmp_path / "bundle.tgz", extra_text=f"token={secret}")
    path = Path(bundle) if not isinstance(bundle, Path) else bundle
    data = path.read_bytes()
    assert secret.encode("utf-8") not in data


@pytest.mark.parametrize("mode", sorted(CLEANUP_FAILURE_MODES))
def test_cleanup_runs_on_timeout_cancel_and_crashes(mode: str) -> None:
    """Happy: cleanup is invoked for each named failure mode."""
    module = require_module(RECOVERY_MODULE)
    cleanup = require_callable(module, "cleanup_on_failure")
    result = cleanup(mode)
    cleaned = getattr(result, "cleaned", None)
    if cleaned is None:
        cleaned = result.get("cleaned")
    assert cleaned is True
