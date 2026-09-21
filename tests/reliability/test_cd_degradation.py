"""W14 / W18 — live redacted diagnostic bundles (#365).

Recovery cleanup moved to a behavioural suite that observes the kill side
effect and the failure-to-clean path (``tests/reliability/test_recovery.py``);
the former ``cleaned is True`` terminal assertion lives there no longer.
"""

from __future__ import annotations

from pathlib import Path

from tests.support.cd_batch import (
    BUNDLE_MODULE,
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
