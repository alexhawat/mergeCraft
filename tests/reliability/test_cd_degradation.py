"""W14 / W18 — live recovery cleanup and redacted diagnostic bundles (#365)."""

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
