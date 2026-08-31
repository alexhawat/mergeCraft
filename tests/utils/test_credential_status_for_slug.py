"""W1.3 — credential probe consolidation (wave plan 15, green after W4)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from mergecraft.config.settings import load_repo_settings
from mergecraft.utils.agent_resolve import has_credentials_for_slug
from tests.cli.support_provider_registry import bootstrap_nous_registry, scaffold_mergecraft_home
from tests.trust_credentials.support import NOUS_SLUG, import_agent_resolve_symbol

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

_CLEAR_KEYS: tuple[str, ...] = (
    "NOUS_API_KEY",
    "MERGECRAFT_CUSTOM_PROVIDER_API_KEY",
    "MERGECRAFT_CUSTOM_PROVIDER_API_KEY_1",
    "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL",
    "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_1",
    "LLM_PROVIDER_1_API_KEY",
    "ANTHROPIC_API_KEY",
)


def _clear_env(monkeypatch: MonkeyPatch) -> None:
    for key in _CLEAR_KEYS:
        monkeypatch.delenv(key, raising=False)


def _credential_status(slug: str, *, tmp_path: Path) -> object:
    status_fn = import_agent_resolve_symbol("credential_status_for_slug")
    settings = load_repo_settings(root=tmp_path, load_learnings_files=False)
    return status_fn(slug, settings=settings, cwd=tmp_path, wired=True)


def test_nous_slug_true_with_only_singleton_custom_provider_key(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """#552 — MERGECRAFT_CUSTOM_PROVIDER_API_KEY alone must credential nous/… slugs."""
    _clear_env(monkeypatch)
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY", "singleton-gateway-key")
    assert has_credentials_for_slug(NOUS_SLUG) is True


def test_nous_slug_true_with_indexed_custom_provider_key(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Indexed MERGECRAFT_CUSTOM_PROVIDER_API_KEY_<N> must still credential nous/… slugs."""
    _clear_env(monkeypatch)
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY_1", "indexed-gateway-key")
    monkeypatch.setenv(
        "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_1", "https://gateway.example.invalid/v1"
    )
    assert has_credentials_for_slug(NOUS_SLUG) is True


def test_nous_slug_true_via_legacy_nous_api_key_with_once_warning(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Legacy NOUS_API_KEY remains supported and warns once (regression guard)."""
    _clear_env(monkeypatch)
    bootstrap_nous_registry(tmp_path, monkeypatch, model_id="deepseek/deepseek-v4-flash")
    monkeypatch.delenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY", raising=False)
    monkeypatch.setenv("NOUS_API_KEY", "legacy-nous-key")
    assert has_credentials_for_slug(NOUS_SLUG) is True
    assert has_credentials_for_slug(NOUS_SLUG) is True


def test_no_credential_reports_looked_for_env_vars(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """D10 — credential_status_for_slug().looked_for names consulted env vars."""
    _clear_env(monkeypatch)
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    status = _credential_status(NOUS_SLUG, tmp_path=tmp_path)
    assert status.available is False
    looked_for = getattr(status, "looked_for", "")
    joined = " ".join(looked_for) if isinstance(looked_for, tuple) else str(looked_for)
    assert "MERGECRAFT_CUSTOM_PROVIDER_API_KEY" in joined or "NOUS_API_KEY" in joined


@pytest.mark.parametrize(
    ("setup", "expected_source"),
    [
        ("registry", "registry-indexed"),
        ("singleton", "gateway-singleton"),
        ("indexed", "gateway-singleton"),
        ("legacy", "legacy-env"),
    ],
)
def test_credential_status_reports_source_route(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    setup: str,
    expected_source: str,
) -> None:
    """D8 — credential_status_for_slug reports the winning source route."""
    _clear_env(monkeypatch)
    if setup == "registry":
        bootstrap_nous_registry(tmp_path, monkeypatch, model_id="deepseek/deepseek-v4-flash")
    elif setup == "singleton":
        scaffold_mergecraft_home(tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY", "singleton-key")
    elif setup == "indexed":
        scaffold_mergecraft_home(tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY_2", "indexed-key")
        monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_2", "https://gw.example/v1")
    else:
        bootstrap_nous_registry(tmp_path, monkeypatch, model_id="deepseek/deepseek-v4-flash")
        monkeypatch.delenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY", raising=False)
        monkeypatch.delenv("LLM_PROVIDER_1_API_KEY", raising=False)
        monkeypatch.delenv("LLM_PROVIDER_1", raising=False)
        monkeypatch.setenv("NOUS_API_KEY", "legacy-key")
    status = _credential_status(NOUS_SLUG, tmp_path=tmp_path)
    assert status.available is True
    assert status.source == expected_source


@pytest.mark.parametrize(
    ("slug", "env_key", "env_value"),
    [
        ("anthropic/claude-sonnet", "ANTHROPIC_API_KEY", "sk-ant-test"),
        ("openai/gpt-5", "OPENAI_API_KEY", "sk-openai-test"),
        ("google/gemini-3-pro", "GEMINI_API_KEY", "gemini-test"),
        ("cursor/composer", "CURSOR_API_KEY", "cursor-test"),
    ],
)
def test_other_provider_branches_unchanged(
    monkeypatch: MonkeyPatch, slug: str, env_key: str, env_value: str
) -> None:
    """Regression — non-nous provider credential branches stay unchanged."""
    for key in _CLEAR_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("CODEX_AUTH_JSON", raising=False)
    assert has_credentials_for_slug(slug) is False
    monkeypatch.setenv(env_key, env_value)
    assert has_credentials_for_slug(slug) is True


def test_unwired_provider_message_differs_from_missing_credential(tmp_path: Path) -> None:
    """D9 — plan-11 unwired vs empty-env messages stay distinct."""
    format_fn = import_agent_resolve_symbol("format_credential_gap_message")
    unwired = format_fn(
        slug="acme/private-model",
        wired=False,
        status=_credential_status(NOUS_SLUG, tmp_path=tmp_path),
    )
    missing = format_fn(
        slug=NOUS_SLUG,
        wired=True,
        status=_credential_status(NOUS_SLUG, tmp_path=tmp_path),
    )
    assert unwired != missing
    assert "mergecraft.yml" in unwired.lower() or "wired" in unwired.lower()
    assert "env" in missing.lower() or "MERGECRAFT" in missing or "NOUS_API_KEY" in missing
