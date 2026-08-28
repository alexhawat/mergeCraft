"""GREEN — gateway settings snapshot reuse (AG9 / issue #496)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from tests.ci.workflow_support import REPO_ROOT

_REPO_ROOT = Path(REPO_ROOT)


@pytest.fixture(autouse=True)
def _reset_gateway_settings_cache() -> None:
    from mergecraft.config.settings_snapshot import reset_gateway_settings_cache

    reset_gateway_settings_cache()


def test_resolve_gateway_endpoint_does_not_reload_per_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mergecraft.agents.openai_compatible_gateways import resolve_gateway_endpoint

    calls = 0

    def _fake_load(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        from mergecraft.config.settings import load_repo_settings

        return load_repo_settings(root=_REPO_ROOT, load_learnings_files=False)

    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY", "k")
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_BASE_URL", "https://example.invalid")
    with patch(
        "mergecraft.config.settings_snapshot.load_repo_settings",
        side_effect=_fake_load,
    ):
        for model in ("custom/m1", "custom/m2", "custom/m3"):
            resolve_gateway_endpoint(model)
    assert calls == 1


def test_has_gateway_credentials_reads_the_run_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    from mergecraft.agents.openai_compatible_gateways import has_gateway_credentials

    calls = 0

    def _fake_load(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        from mergecraft.config.settings import load_repo_settings

        return load_repo_settings(root=_REPO_ROOT, load_learnings_files=False)

    with patch(
        "mergecraft.config.settings_snapshot.load_repo_settings",
        side_effect=_fake_load,
    ):
        has_gateway_credentials("custom")
        has_gateway_credentials("custom")
    assert calls == 1


def test_falls_back_to_a_live_load_when_no_snapshot_is_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mergecraft.agents.openai_compatible_gateways import has_gateway_credentials

    monkeypatch.delenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY", raising=False)
    monkeypatch.delenv("MERGECRAFT_CUSTOM_PROVIDER_BASE_URL", raising=False)
    assert isinstance(has_gateway_credentials("nous"), bool)


def test_registry_backed_and_legacy_resolution_are_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mergecraft.agents.openai_compatible_gateways import resolve_gateway_endpoint

    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY", "k")
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_BASE_URL", "https://example.invalid")
    endpoint = resolve_gateway_endpoint("custom/model-id")
    assert endpoint is not None
    provider_id, base_url, api_key = endpoint
    assert provider_id == "custom"
    assert base_url.startswith("https://")
    assert api_key == "k"


def test_derived_gateway_cache_reloads_after_config_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.cli.support_provider_registry import (
        bootstrap_nous_registry,
        bootstrap_opencode_gateway,
    )

    from mergecraft.agents.opencode import build_custom_provider

    TOKENHUB_BASE_URL = "https://tokenhub-intl.tencentcloudmaas.com/v1"
    bootstrap_nous_registry(
        tmp_path, monkeypatch, model_id="deepseek/deepseek-v4-flash", api_key="nous-key"
    )
    assert build_custom_provider("nous/deepseek/deepseek-v4-flash") is not None
    bootstrap_opencode_gateway(
        tmp_path,
        monkeypatch,
        label="tokenhub",
        url=TOKENHUB_BASE_URL,
        model_id="hy3",
        api_key="th-key",
        env_index=2,
    )
    tokenhub = build_custom_provider("tokenhub/hy3")
    assert tokenhub is not None
    assert "tokenhub" in tokenhub


def test_no_caller_signature_changed() -> None:
    """AST guard for D22 — opencode/codex call sites unchanged on trunk until AG9."""
    for rel in ("src/mergecraft/agents/opencode.py", "src/mergecraft/agents/codex.py"):
        proc = subprocess.run(
            ["git", "show", f"origin/pre-0.0.1:{rel}"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        trunk = proc.stdout
        current = (_REPO_ROOT / rel).read_text(encoding="utf-8")
        assert current == trunk
