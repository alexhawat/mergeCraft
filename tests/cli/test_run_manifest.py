"""CC2 — run manifest fingerprints and telemetry defaults (`.ignorelocal/02-cli-sources-trust-wave-plan.md`).

Authoring wave: **CC2.1** (RED). Implementation: **CC2.2**.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

_CC2_2_XFAIL = pytest.mark.xfail(
    reason="green after CC2.2: run manifest + D11 telemetry default", strict=False
)


def _manifest_mod() -> object:
    try:
        import mergecraft.evidence.run_manifest as mod
    except ImportError as exc:
        pytest.fail(f"mergecraft.evidence.run_manifest not importable: {exc}")
    return mod


@_CC2_2_XFAIL
def test_manifest_carries_model_cli_and_prompt_hashes(tmp_path: Path) -> None:
    """Run manifest records model/CLI versions and prompt/config/policy hashes."""
    mod = _manifest_mod()
    build = getattr(mod, "build_run_manifest", None)
    if build is None:
        pytest.fail("build_run_manifest not defined in mergecraft.evidence.run_manifest")

    manifest = build(
        cwd=tmp_path,
        model="anthropic/claude-sonnet",
        agent_id="claude",
        prompt_text="review this diff",
        config_path=tmp_path / ".mergecraft" / "config.yaml",
    )

    assert manifest.get("model_versions") or manifest.get("model_version")
    assert manifest.get("cli_versions") or manifest.get("cli_version")
    hashes = manifest.get("hashes") or manifest
    for key in ("prompt", "config", "policy"):
        field = f"{key}_hash"
        assert field in hashes or field in manifest, f"missing {field} in manifest: {manifest}"


@_CC2_2_XFAIL
def test_local_run_defaults_to_no_remote_telemetry(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """D11 — local private-repo reviews ship no remote telemetry by default."""
    mod = _manifest_mod()
    resolve = getattr(mod, "resolve_local_telemetry_defaults", None)
    if resolve is None:
        pytest.fail(
            "resolve_local_telemetry_defaults not defined in mergecraft.evidence.run_manifest"
        )

    monkeypatch.delenv("MERGECRAFT_TRACING", raising=False)
    monkeypatch.delenv("MERGECRAFT_TRACING_TO", raising=False)
    monkeypatch.delenv("MERGECRAFT_LOGFIRE_TOKEN", raising=False)

    defaults = resolve(cwd=tmp_path, private_repo=True)
    assert defaults.get("enabled") is False or defaults.get("tracing_to") in {
        None,
        "local_files",
        "off",
    }
    remote_sinks = {"logfire", "otel"}
    tracing_to = defaults.get("tracing_to")
    assert tracing_to not in remote_sinks, (
        f"local private run must not default to remote sink: {defaults}"
    )
