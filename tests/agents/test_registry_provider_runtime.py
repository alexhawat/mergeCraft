"""RED tests for BE #481 — registry-only provider runtime resolution.

Wave plan: ``.ignorelocal/waves/open-issues-sweep-2026-08-24-b-provider-registry-wave-plan.md``
BE — test-creator. Pins: unknown provider → ``configuration_error`` (D4),
Nous via registry ``harness: opencode`` only, kill bare ``return "opencode"``
fallback, harness field respected per registry row, legacy ``NOUS_API_KEY`` shim (D7).
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

import pytest
from tests.cli.support_provider_registry import (
    CUSTOM_REGISTRY_URL,
    NOUS_BASE_URL,
    NOUS_DEEPSEEK_V4,
    NOUS_TENCENT_HY3,
    bootstrap_nous_registry,
    clear_legacy_gateway_env,
    format_model_slug,
    scaffold_mergecraft_home,
    write_indexed_provider_secret,
    write_registry_provider_row,
)

from mergecraft.config.settings import RepoSettings, load_repo_settings
from mergecraft.main import _classify_error_outcome
from mergecraft.run_outcome import RunOutcome
from mergecraft.utils.agent_resolve import (
    ModelFallbackPolicyError,
    _agent_mode_for_slug,
    _harness_supports_provider,
    has_credentials_for_slug,
    resolve_harness,
    resolve_runtime_agent,
)

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

BE_XFAIL = pytest.mark.xfail(reason="green after BE impl", strict=False)

_UNKNOWN_SLUG = "acme-registry/unregistered-model"
_UNKNOWN_PROVIDER = "acme-registry"


def _configuration_error_types() -> tuple[type[BaseException], ...]:
    from mergecraft.main import _ConfigurationError

    return (ModelFallbackPolicyError, _ConfigurationError, ValueError)


# ── D4 / issue #481 — unknown provider is configuration_error ────────────────


@BE_XFAIL
def test_agent_mode_for_unknown_provider_raises_configuration_error() -> None:
    """Bare ``return "opencode"`` fallback must be gone for unknown providers."""
    with pytest.raises(_configuration_error_types(), match=r"configuration|unknown|provider"):
        _agent_mode_for_slug(_UNKNOWN_SLUG)


@BE_XFAIL
def test_resolve_harness_unknown_provider_raises_configuration_error() -> None:
    settings = RepoSettings.model_validate({"model": _UNKNOWN_SLUG})
    with pytest.raises(_configuration_error_types(), match=r"configuration|unknown|provider"):
        resolve_harness(settings, _UNKNOWN_SLUG)


@BE_XFAIL
def test_resolve_runtime_agent_unknown_provider_not_opencode(
    monkeypatch: MonkeyPatch,
) -> None:
    clear_legacy_gateway_env(monkeypatch)
    try:
        agent = resolve_runtime_agent(model=_UNKNOWN_SLUG)
    except _configuration_error_types():
        return
    assert agent.name != "opencode", (
        f"unknown provider {_UNKNOWN_SLUG!r} silently routed to opencode"
    )


@BE_XFAIL
def test_classify_unknown_provider_error_maps_to_configuration_error() -> None:
    settings = RepoSettings.model_validate({"model": _UNKNOWN_SLUG})
    with pytest.raises(_configuration_error_types()) as exc_info:
        resolve_harness(settings, _UNKNOWN_SLUG)
    assert _classify_error_outcome(exc_info.value) is RunOutcome.configuration_error


@BE_XFAIL
def test_harness_supports_provider_rejects_unregistered_custom_provider() -> None:
    """Custom providers must be registered — no silent opencode allow-list bypass."""
    assert _harness_supports_provider("opencode", _UNKNOWN_PROVIDER) is False


# ── Nous works only via registry (harness: opencode) ───────────────────────


@BE_XFAIL
def test_nous_resolves_to_opencode_via_registry_harness(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    slug = bootstrap_nous_registry(tmp_path, monkeypatch, model_id=NOUS_TENCENT_HY3)
    settings = load_repo_settings(root=tmp_path, load_learnings_files=False)
    assert resolve_harness(settings, slug) == "opencode"
    agent = resolve_runtime_agent(model=slug, settings=settings)
    assert agent.name == "opencode"


@BE_XFAIL
def test_nous_credentials_from_indexed_registry_key_only(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    slug = bootstrap_nous_registry(tmp_path, monkeypatch, model_id=NOUS_DEEPSEEK_V4)
    load_repo_settings(root=tmp_path, load_learnings_files=False)
    assert has_credentials_for_slug(slug) is True
    monkeypatch.delenv("LLM_PROVIDER_1_API_KEY", raising=False)
    assert has_credentials_for_slug(slug) is False


@BE_XFAIL
def test_nous_without_registry_entry_raises_configuration_error(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    clear_legacy_gateway_env(monkeypatch)
    slug = format_model_slug("nous", NOUS_TENCENT_HY3)
    settings = load_repo_settings(root=tmp_path, load_learnings_files=False)
    with pytest.raises(_configuration_error_types(), match=r"configuration|provider|registry"):
        resolve_runtime_agent(model=slug, settings=settings)


@BE_XFAIL
def test_resolve_gateway_endpoint_uses_registry_url_not_preset(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    from mergecraft.agents.openai_compatible_gateways import resolve_gateway_endpoint

    slug = bootstrap_nous_registry(
        tmp_path,
        monkeypatch,
        url=CUSTOM_REGISTRY_URL,
        model_id=NOUS_TENCENT_HY3,
        api_key="registry-url-canary-key",
    )
    endpoint = resolve_gateway_endpoint(slug)
    assert endpoint is not None
    provider_id, base_url, api_key = endpoint
    assert provider_id == "nous"
    assert base_url == CUSTOM_REGISTRY_URL
    assert base_url != NOUS_BASE_URL
    assert api_key == "registry-url-canary-key"


# ── Harness field respected per registry row (#481 acceptance) ────────────────

_HARNESS_REGISTRY_CASES = (
    pytest.param(
        "codex",
        "acme",
        "acme/gateway-model-1",
        CUSTOM_REGISTRY_URL,
        id="registry-incompatible-harness-is-configuration-error",
    ),
    pytest.param(
        "opencode",
        "openai",
        "openai/gpt-5.3-codex",
        None,
        id="openai-registry-overrides-codex-inference",
    ),
    pytest.param(
        "opencode",
        "anthropic",
        "anthropic/claude-sonnet",
        None,
        id="anthropic-registry-overrides-claude-inference",
    ),
    pytest.param(
        "opencode",
        "google",
        "google/gemini-3.1-pro-preview",
        None,
        id="google-registry-overrides-gemini-inference",
    ),
    pytest.param(
        "opencode",
        "cursor",
        "cursor/cloud-agent",
        None,
        id="cursor-registry-overrides-cursor-inference",
    ),
)


@BE_XFAIL
@pytest.mark.parametrize(
    ("harness", "label", "slug", "url"),
    _HARNESS_REGISTRY_CASES,
)
def test_registry_declared_harness_respected_at_runtime(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    harness: str,
    label: str,
    slug: str,
    url: str | None,
) -> None:
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    clear_legacy_gateway_env(monkeypatch)
    write_registry_provider_row(
        tmp_path,
        label=label,
        harness=harness,
        env_index=1,
        url=url,
    )
    write_indexed_provider_secret(
        tmp_path,
        env_index=1,
        label=label,
        api_key=f"{label}-registry-test-key",
    )
    if label == "openai":
        monkeypatch.setenv("CODEX_AUTH_JSON", '{"access_token":"test-token"}')
    elif label == "anthropic":
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth-test-token")
    elif label == "google":
        monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    elif label == "cursor":
        monkeypatch.setenv("CURSOR_API_KEY", "cursor-test-key")

    settings = load_repo_settings(root=tmp_path, load_learnings_files=False)
    if harness == "codex" and label == "acme":
        with pytest.raises(
            _configuration_error_types(), match=r"configuration|incompatible|harness"
        ):
            resolve_harness(settings, slug)
        return
    resolved = resolve_harness(settings, slug)
    assert resolved == harness, (
        f"registry harness {harness!r} must win over inference for {slug!r}; got {resolved!r}"
    )


# ── D7 — legacy NOUS_API_KEY honoured with deprecation warning ──────────────


@BE_XFAIL
def test_legacy_nous_api_key_emits_deprecation_warning_once(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    slug = bootstrap_nous_registry(tmp_path, monkeypatch, model_id=NOUS_TENCENT_HY3)
    monkeypatch.delenv("LLM_PROVIDER_1_API_KEY", raising=False)
    monkeypatch.setenv("NOUS_API_KEY", "legacy-nous-shim-key")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert has_credentials_for_slug(slug) is True
        assert has_credentials_for_slug(slug) is True

    deprecation = [item for item in caught if issubclass(item.category, DeprecationWarning)]
    assert len(deprecation) == 1, (
        f"expected exactly one DeprecationWarning for legacy NOUS_API_KEY, got {deprecation}"
    )
