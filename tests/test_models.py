"""Unit tests for the model alias catalog."""

from __future__ import annotations

import pytest

from mergecraft.models import (
    AUTO_EFFICIENT,
    AUTO_INTELLIGENT,
    DEFAULT_PROXY_MODEL,
    MODEL_ALIASES,
    PROVIDERS,
    default_auto_tier,
    get_auto_select_hint_model,
    get_model_env_vars,
    get_model_managed_credentials,
    get_model_provider,
    get_provider_display_name,
    is_auto_tier,
    is_bedrock_anthropic_id,
    is_card_gated_model,
    is_vertex_anthropic_id,
    parse_model,
    resolve_auto_tier,
    resolve_cli_model,
    resolve_display_alias,
    resolve_model_slug,
    resolve_openrouter_model,
)


def test_providers_include_expected_keys() -> None:
    expected = {
        "anthropic",
        "openai",
        "google",
        "xai",
        "deepseek",
        "moonshotai",
        "opencode",
        "opencode-go",
        "nous",
        "tokenhub",
        "bedrock",
        "vertex",
        "openrouter",
    }
    assert expected <= set(PROVIDERS)


def test_model_aliases_cover_all_provider_models() -> None:
    expected_count = sum(len(p.models) for p in PROVIDERS.values())
    assert len(MODEL_ALIASES) == expected_count
    slugs = {a.slug for a in MODEL_ALIASES}
    assert "anthropic/claude-opus" in slugs
    assert "opencode/big-pickle" in slugs
    assert "bedrock/byok" in slugs


def test_parse_model_and_provider_helpers() -> None:
    assert parse_model("anthropic/claude-opus") == ("anthropic", "claude-opus")
    with pytest.raises(ValueError, match="invalid model slug"):
        parse_model("no-slash")
    assert get_model_provider("openai/gpt") == "openai"
    assert get_provider_display_name("anthropic/claude-opus") == "Anthropic"
    assert get_provider_display_name("unknown/model") is None


def test_env_vars_and_managed_credentials() -> None:
    assert "ANTHROPIC_API_KEY" in get_model_env_vars("anthropic/claude-opus")
    assert get_model_env_vars("opencode/big-pickle") == []
    assert get_model_managed_credentials("openai/gpt") == ["CODEX_AUTH_JSON"]
    assert get_model_managed_credentials("anthropic/claude-opus") == []


def test_resolve_display_alias_follows_fallback_chain() -> None:
    alias = resolve_display_alias("openai/gpt-codex")
    assert alias is not None
    assert alias.slug == "openai/gpt"
    assert alias.display_name == "GPT Sol"
    assert resolve_cli_model("openai/gpt-codex") == "openai/gpt-5.6-sol"
    assert resolve_openrouter_model("openai/gpt-codex") == "openrouter/openai/gpt-5.6-sol"


def test_resolve_auto_tier_sentinels() -> None:
    assert is_auto_tier(AUTO_EFFICIENT)
    assert is_auto_tier(AUTO_INTELLIGENT)
    assert not is_auto_tier("anthropic/claude-opus")
    assert default_auto_tier(has_card=True) == AUTO_INTELLIGENT
    assert default_auto_tier(has_card=False) == AUTO_EFFICIENT
    assert resolve_auto_tier(model=AUTO_INTELLIGENT, has_card=False) == AUTO_EFFICIENT
    assert resolve_auto_tier(model=AUTO_INTELLIGENT, has_card=True) == AUTO_INTELLIGENT
    assert resolve_cli_model(AUTO_EFFICIENT) == "moonshotai/kimi-k2.7-code"
    assert resolve_cli_model(AUTO_INTELLIGENT) == "anthropic/claude-opus-4-8"


def test_is_card_gated_model() -> None:
    assert is_card_gated_model("anthropic/claude-opus") is True
    assert is_card_gated_model("opencode/big-pickle") is False
    assert is_card_gated_model(AUTO_EFFICIENT) is True


def test_default_proxy_model() -> None:
    assert DEFAULT_PROXY_MODEL == "openrouter/moonshotai/kimi-k2.7-code"
    assert get_auto_select_hint_model() == "Kimi K2"


def test_resolve_model_slug_direct() -> None:
    assert resolve_model_slug("anthropic/claude-opus") == "anthropic/claude-opus-4-8"
    assert resolve_model_slug("missing/model") is None


def test_preferred_and_subagent_fields() -> None:
    opus = next(a for a in MODEL_ALIASES if a.slug == "anthropic/claude-opus")
    assert opus.preferred is True
    assert opus.subagent_model == "anthropic/claude-sonnet"
    hidden = next(a for a in MODEL_ALIASES if a.slug == "opencode/minimax-m2.5-free")
    assert hidden.hidden is True
    assert hidden.fallback == "opencode/big-pickle"


def test_bedrock_and_vertex_routing_helpers() -> None:
    assert is_bedrock_anthropic_id("us.anthropic.claude-opus-4-7") is True
    assert is_bedrock_anthropic_id("amazon.nova-pro-v1:0") is False
    assert is_vertex_anthropic_id("claude-opus-4-1@20250805") is True
    assert is_vertex_anthropic_id("gemini-2.5-pro") is False
    bedrock = next(a for a in MODEL_ALIASES if a.slug == "bedrock/byok")
    assert bedrock.routing == "bedrock"
    vertex = next(a for a in MODEL_ALIASES if a.slug == "vertex/byok")
    assert vertex.routing == "vertex"
