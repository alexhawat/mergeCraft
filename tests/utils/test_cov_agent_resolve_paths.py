"""Decision-path coverage for ``mergecraft.utils.agent_resolve`` (issue #431).

Every test here drives a *second* way out of a decision that production code
only ever takes one way in the existing suite: the credential matrix per
provider, the binary-availability fallbacks, chain construction under
``pin``/``head``/``modelFallbacks``, the residency filter, the
``allow_fallback=false`` policy, skip-reason classification, harness
validation, and the fail-loud arms of ``resolve_runtime_agent``.

Nothing here touches the network: every provider probe in this module is a
pure environment read, and the only external lookups (``shutil.which``,
``Path.exists``) are monkeypatched.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.agents.shared import AgentResult
from mergecraft.config.settings import RepoSettings
from mergecraft.models import BEDROCK_MODEL_ID_ENV, VERTEX_MODEL_ID_ENV
from mergecraft.utils import agent_resolve as ar

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

# Every env var any credential probe in ``agent_resolve`` reads. Cleared for
# each test so a developer machine's real credentials cannot make a
# "missing credential" arm silently pass.
_ENV_KEYS = (
    "ANTHROPIC_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "AWS_BEARER_TOKEN_BEDROCK",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "VERTEX_SERVICE_ACCOUNT_JSON",
    "CODEX_AUTH_JSON",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_GENERATIVE_AI_API_KEY",
    "CURSOR_API_KEY",
    "NOUS_API_KEY",
    "TOKENHUB_API_KEY",
    "MERGECRAFT_CUSTOM_PROVIDER_API_KEY",
    "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL",
    BEDROCK_MODEL_ID_ENV,
    VERTEX_MODEL_ID_ENV,
    "MERGECRAFT_MODEL",
    "MERGECRAFT_AGENT",
    "MERGECRAFT_TEMP_DIR",
)

CODEX_SUBSCRIPTION_JSON = json.dumps({"tokens": {"access_token": "codex-access"}})


@pytest.fixture(autouse=True)
def _clean_provider_env(monkeypatch: MonkeyPatch) -> None:
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


# ---------------------------------------------------------------------------
# has_credentials_for_slug — one arm per provider, both answers
# ---------------------------------------------------------------------------


def test_has_credentials_rejects_a_slug_with_no_provider_prefix() -> None:
    """A slug without ``provider/`` cannot be parsed — treated as no credentials."""
    assert ar.has_credentials_for_slug("gpt-5") is False


def test_anthropic_credentials_accept_either_oauth_token_or_api_key(
    monkeypatch: MonkeyPatch,
) -> None:
    assert ar.has_credentials_for_slug("anthropic/claude-sonnet") is False
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat-x")
    assert ar.has_credentials_for_slug("anthropic/claude-sonnet") is True
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
    assert ar.has_credentials_for_slug("anthropic/claude-sonnet") is True


def test_whitespace_only_credential_does_not_count_as_configured(
    monkeypatch: MonkeyPatch,
) -> None:
    """``_has_env`` strips — a blank secret is the "unset in CI" shape."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "   ")
    assert ar.has_credentials_for_slug("anthropic/claude-sonnet") is False


def test_openai_credentials_prefer_subscription_json_then_api_key(
    monkeypatch: MonkeyPatch,
) -> None:
    assert ar.has_credentials_for_slug("openai/gpt") is False
    monkeypatch.setenv("CODEX_AUTH_JSON", "not-json")
    assert ar.has_credentials_for_slug("openai/gpt") is False
    monkeypatch.setenv("CODEX_AUTH_JSON", CODEX_SUBSCRIPTION_JSON)
    assert ar.has_credentials_for_slug("openai/gpt") is True
    monkeypatch.delenv("CODEX_AUTH_JSON")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    assert ar.has_credentials_for_slug("openai/gpt") is True


def test_google_and_cursor_credentials(monkeypatch: MonkeyPatch) -> None:
    assert ar.has_credentials_for_slug("google/gemini-3-pro") is False
    assert ar.has_credentials_for_slug("cursor/composer") is False
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "g-key")
    monkeypatch.setenv("CURSOR_API_KEY", "c-key")
    assert ar.has_credentials_for_slug("google/gemini-3-pro") is True
    assert ar.has_credentials_for_slug("cursor/composer") is True


def test_bedrock_needs_both_aws_auth_and_a_pinned_model_id(
    monkeypatch: MonkeyPatch,
) -> None:
    """Either half alone is a misconfiguration, not a usable Bedrock setup."""
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "aws-bearer")
    assert ar.has_credentials_for_slug("bedrock/byok") is False
    monkeypatch.setenv(BEDROCK_MODEL_ID_ENV, "anthropic.claude-3-5-sonnet")
    assert ar.has_credentials_for_slug("bedrock/byok") is True
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK")
    assert ar.has_credentials_for_slug("bedrock/byok") is False
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA")
    assert ar.has_credentials_for_slug("bedrock/byok") is False
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
    assert ar.has_credentials_for_slug("bedrock/byok") is True


def test_vertex_needs_both_service_account_and_a_pinned_model_id(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("VERTEX_SERVICE_ACCOUNT_JSON", "{}")
    assert ar.has_credentials_for_slug("vertex/byok") is False
    monkeypatch.setenv(VERTEX_MODEL_ID_ENV, "claude-sonnet-4")
    assert ar.has_credentials_for_slug("vertex/byok") is True


def test_gateway_providers_read_their_preset_key_and_the_custom_alias(
    monkeypatch: MonkeyPatch,
) -> None:
    """``nous``/``tokenhub``/``minimax`` all route through the gateway helper."""
    assert ar.has_credentials_for_slug("nous/deepseek-v4") is False
    assert ar.has_credentials_for_slug("tokenhub/hy3") is False
    assert ar.has_credentials_for_slug("minimax/MiniMax-M3") is False

    monkeypatch.setenv("NOUS_API_KEY", "nous-key")
    assert ar.has_credentials_for_slug("nous/deepseek-v4") is True
    assert ar.has_credentials_for_slug("tokenhub/hy3") is False

    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY", "custom-key")
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_BASE_URL", "https://example.invalid/v1")
    assert ar.has_credentials_for_slug("minimax/MiniMax-M3") is True
    assert ar.has_credentials_for_slug("tokenhub/hy3") is True


def test_unknown_provider_prefix_has_no_credentials(monkeypatch: MonkeyPatch) -> None:
    """A parseable but uncatalogued prefix falls off the end of the matrix."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    assert ar.has_credentials_for_slug("acme/private-1") is False


# ---------------------------------------------------------------------------
# _agent_binary_available / is_runnable_model_slug
# ---------------------------------------------------------------------------


def test_binary_gate_short_circuits_for_env_driven_harness_providers(
    monkeypatch: MonkeyPatch,
) -> None:
    """``nous``/``minimax`` map to ``None`` — no CLI on PATH is required."""
    monkeypatch.setattr(ar.shutil, "which", lambda _name: None)
    assert ar._agent_binary_available("nous/deepseek-v4") is True
    assert ar._agent_binary_available("minimax/MiniMax-M3") is True
    # An unmapped provider still needs no binary (``binary_by_provider`` miss).
    assert ar._agent_binary_available("acme/private-1") is True


def test_binary_gate_rejects_an_unparseable_slug() -> None:
    assert ar._agent_binary_available("claude-sonnet") is False


def test_binary_gate_falls_back_to_the_node_modules_bin_when_path_misses(
    monkeypatch: MonkeyPatch, tmp_path: Any
) -> None:
    """No ``claude`` on PATH still runs when the vendored binary exists."""
    monkeypatch.setattr(ar.shutil, "which", lambda _name: None)
    monkeypatch.setenv("MERGECRAFT_TEMP_DIR", str(tmp_path))
    assert ar._agent_binary_available("anthropic/claude-sonnet") is False

    vendored = tmp_path / "node_modules" / ".bin" / "claude"
    vendored.parent.mkdir(parents=True)
    vendored.write_text("#!/bin/sh\n", encoding="utf-8")
    assert ar._agent_binary_available("anthropic/claude-sonnet") is True
    assert ar._local_agent_binary("claude") == vendored


def test_binary_gate_accepts_a_binary_found_on_path(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(ar.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert ar._agent_binary_available("openai/gpt") is True


def test_is_runnable_requires_credentials_before_the_binary_gate(
    monkeypatch: MonkeyPatch,
) -> None:
    """The binary gate is never consulted when credentials are missing."""
    calls: list[str] = []
    monkeypatch.setattr(ar, "_agent_binary_available", lambda slug: calls.append(slug) or True)
    assert ar.is_runnable_model_slug("google/gemini-3-pro") is False
    assert calls == []
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    assert ar.is_runnable_model_slug("google/gemini-3-pro") is True
    assert calls == ["google/gemini-3-pro"]


# ---------------------------------------------------------------------------
# configured slugs / env promotion / effective resolution
# ---------------------------------------------------------------------------


def test_effective_model_slugs_promotes_the_env_override_and_dedupes(
    monkeypatch: MonkeyPatch,
) -> None:
    settings = RepoSettings.model_validate({"models": ["openai/gpt", "google/gemini-3-pro"]})
    assert ar.effective_model_slugs(settings) == ["openai/gpt", "google/gemini-3-pro"]
    monkeypatch.setenv("MERGECRAFT_MODEL", "google/gemini-3-pro")
    assert ar.effective_model_slugs(settings) == ["google/gemini-3-pro", "openai/gpt"]


def test_effective_model_slugs_falls_back_to_single_model_then_empty() -> None:
    assert ar.effective_model_slugs(RepoSettings.model_validate({"model": "openai/gpt"})) == [
        "openai/gpt"
    ]
    assert ar.effective_model_slugs(RepoSettings.model_validate({})) == []


def test_resolve_effective_model_slug_prefers_env_then_credentialled_then_first(
    monkeypatch: MonkeyPatch,
) -> None:
    settings = RepoSettings.model_validate({"models": ["openai/gpt", "google/gemini-3-pro"]})
    # No credentials anywhere → first configured entry regardless.
    assert ar.resolve_effective_model_slug(settings) == "openai/gpt"
    # Credentials for the second entry only → that entry wins.
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    assert ar.resolve_effective_model_slug(settings) == "google/gemini-3-pro"
    # Env override beats config outright.
    monkeypatch.setenv("MERGECRAFT_MODEL", "cursor/composer")
    assert ar.resolve_effective_model_slug(settings) == "cursor/composer"


def test_resolve_effective_model_slug_falls_through_to_the_alias_catalog() -> None:
    """No ``models:`` list — ``model:`` resolves through ``resolve_model``."""
    settings = RepoSettings.model_validate({"model": "acme/private-1"})
    assert ar.resolve_effective_model_slug(settings) == "acme/private-1"
    assert ar.resolve_effective_model_slug(RepoSettings.model_validate({})) is None


# ---------------------------------------------------------------------------
# chain construction
# ---------------------------------------------------------------------------


def test_catalog_fallback_tail_walks_the_alias_chain() -> None:
    assert ar._catalog_fallback_tail("openai/gpt-codex")[0] == "openai/gpt"
    assert ar._catalog_fallback_tail("acme/private-1") == []


def test_catalog_fallback_tail_stops_on_a_cycle(monkeypatch: MonkeyPatch) -> None:
    """A self-referential alias table must terminate, not spin to the depth cap."""
    from mergecraft.models import ModelAlias

    a = ModelAlias(
        slug="loop/a", provider="loop", display_name="A", resolve="loop-a", fallback="loop/b"
    )
    b = ModelAlias(
        slug="loop/b", provider="loop", display_name="B", resolve="loop-b", fallback="loop/a"
    )
    monkeypatch.setattr(ar, "MODEL_ALIASES", [a, b])
    assert ar._catalog_fallback_tail("loop/a") == ["loop/b", "loop/a"]


def test_single_model_chain_appends_the_catalog_fallback_tail() -> None:
    """One configured slug and no ``modelFallbacks`` → catalog tail is expanded."""
    settings = RepoSettings.model_validate({"model": "openai/gpt-codex"})
    assert ar.effective_model_chain(settings) == ["openai/gpt-codex", "openai/gpt"]


def test_explicit_chain_suppresses_the_catalog_tail() -> None:
    """Two configured slugs mean the operator owns the chain — no catalog tail."""
    settings = RepoSettings.model_validate({"models": ["openai/gpt-codex", "google/gemini-3-pro"]})
    assert ar.effective_model_chain(settings) == ["openai/gpt-codex", "google/gemini-3-pro"]


def test_explicit_chain_expands_configured_model_fallbacks() -> None:
    settings = RepoSettings.model_validate(
        {
            "models": ["openai/gpt-codex"],
            "modelFallbacks": {"openai/gpt-codex": ["cursor/composer", "cursor/composer"]},
        }
    )
    assert ar.effective_model_chain(settings) == ["openai/gpt-codex", "cursor/composer"]


def test_env_override_is_prepended_and_expanded_against_model_fallbacks(
    monkeypatch: MonkeyPatch,
) -> None:
    settings = RepoSettings.model_validate(
        {
            "models": ["openai/gpt-codex"],
            "modelFallbacks": {"google/gemini-3-pro": ["cursor/composer"]},
        }
    )
    monkeypatch.setenv("MERGECRAFT_MODEL", "google/gemini-3-pro")
    assert ar.effective_model_chain(settings) == [
        "google/gemini-3-pro",
        "cursor/composer",
        "openai/gpt-codex",
    ]


def test_head_moves_to_the_front_without_duplicating_a_configured_entry() -> None:
    settings = RepoSettings.model_validate({"models": ["openai/gpt-codex", "google/gemini-3-pro"]})
    assert ar.effective_model_chain(settings, head="google/gemini-3-pro") == [
        "google/gemini-3-pro",
        "openai/gpt-codex",
    ]


def test_pin_collapses_to_the_head_or_the_first_configured_entry() -> None:
    settings = RepoSettings.model_validate({"models": ["openai/gpt-codex", "google/gemini-3-pro"]})
    assert ar.effective_model_chain(settings, head="cursor/composer", pin=True) == [
        "cursor/composer"
    ]
    assert ar.effective_model_chain(settings, pin=True) == ["openai/gpt-codex"]
    assert ar.effective_model_chain(RepoSettings.model_validate({}), pin=True) == []


def _bind_allowed_regions(monkeypatch: MonkeyPatch, *, permitted: set[str]) -> None:
    """Pretend an ``enterprise.allowedRegions`` block is bound, permitting ``permitted``."""
    from mergecraft.enterprise import runtime as ent

    class _Settings:
        allowed_regions = ("eu",)

    def _enforce(slug: str, **_kwargs: Any) -> None:
        if slug not in permitted:
            msg = f"{slug} outside allowedRegions"
            raise PermissionError(msg)

    monkeypatch.setattr(ent, "current_enterprise_settings", lambda: _Settings())
    monkeypatch.setattr(ent, "enforce_routed_model_residency", _enforce)


def test_residency_filter_drops_disallowed_chain_entries(monkeypatch: MonkeyPatch) -> None:
    _bind_allowed_regions(monkeypatch, permitted={"google/gemini-3-pro"})
    settings = RepoSettings.model_validate({"models": ["openai/gpt-codex", "google/gemini-3-pro"]})
    assert ar.effective_model_chain(settings) == ["google/gemini-3-pro"]


def test_residency_filter_raises_when_no_entry_survives(monkeypatch: MonkeyPatch) -> None:
    _bind_allowed_regions(monkeypatch, permitted=set())
    settings = RepoSettings.model_validate({"models": ["openai/gpt-codex", "google/gemini-3-pro"]})
    with pytest.raises(PermissionError, match=r"enterprise\.allowedRegions"):
        ar.effective_model_chain(settings)


# ---------------------------------------------------------------------------
# pick_runnable_slug_from_chain
# ---------------------------------------------------------------------------


def test_empty_chain_names_the_config_keys_the_operator_must_set() -> None:
    with pytest.raises(RuntimeError, match=r"set models: or model: in \.mergecraft/config\.yaml"):
        ar.pick_runnable_slug_from_chain([])


def test_chain_skips_entries_without_credentials_or_binary(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("CURSOR_API_KEY", "c-key")
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    # Cursor has credentials but no binary; Gemini has both.
    monkeypatch.setattr(ar, "_agent_binary_available", lambda slug: not slug.startswith("cursor/"))
    chain = ["openai/gpt", "cursor/composer", "google/gemini-3-pro"]
    assert ar.pick_runnable_slug_from_chain(chain) == "google/gemini-3-pro"


def test_chain_with_no_runnable_entry_says_to_configure_credentials(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(ar, "_agent_binary_available", lambda _slug: True)
    with pytest.raises(RuntimeError, match="no runnable model slug in chain"):
        ar.pick_runnable_slug_from_chain(["openai/gpt", "google/gemini-3-pro"])


def test_allow_fallback_false_rejects_a_primary_missing_credentials() -> None:
    with pytest.raises(ar.ModelFallbackPolicyError, match="missing credentials"):
        ar.pick_runnable_slug_from_chain(
            ["openai/gpt", "google/gemini-3-pro"], allow_fallback=False
        )


def test_allow_fallback_false_rejects_a_primary_missing_its_binary(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setattr(ar, "_agent_binary_available", lambda _slug: False)
    with pytest.raises(ar.ModelFallbackPolicyError, match="agent binary missing"):
        ar.pick_runnable_slug_from_chain(
            ["openai/gpt", "google/gemini-3-pro"], allow_fallback=False
        )


def test_allow_fallback_false_returns_the_primary_and_never_the_backup(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    monkeypatch.setattr(ar, "_agent_binary_available", lambda _slug: True)
    assert (
        ar.pick_runnable_slug_from_chain(
            ["openai/gpt", "google/gemini-3-pro"], allow_fallback=False
        )
        == "openai/gpt"
    )


def test_select_runnable_model_slug_honours_allow_fallback_from_settings(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    monkeypatch.setattr(ar, "_agent_binary_available", lambda _slug: True)
    settings = RepoSettings.model_validate(
        {"models": ["openai/gpt", "google/gemini-3-pro"], "allowFallback": False}
    )
    with pytest.raises(ar.ModelFallbackPolicyError):
        ar.select_runnable_model_slug(settings=settings)

    permissive = RepoSettings.model_validate(
        {"models": ["openai/gpt", "google/gemini-3-pro"], "allowFallback": True}
    )
    assert ar.select_runnable_model_slug(settings=permissive) == "google/gemini-3-pro"


# ---------------------------------------------------------------------------
# result classification
# ---------------------------------------------------------------------------


def test_retryable_failure_reason_reads_error_text_then_metadata() -> None:
    timeout_by_text = AgentResult(success=False, error="provider TIMEOUT after 300s")
    assert ar._retryable_failure_reason(timeout_by_text) is ar.FallbackReason.timeout

    crash_by_meta = AgentResult(success=False, error="boom", metadata={"crash": True})
    assert ar._retryable_failure_reason(crash_by_meta) is ar.FallbackReason.crash

    generic = AgentResult(success=False, error=None)
    assert ar._retryable_failure_reason(generic) is ar.FallbackReason.provider_error


def test_is_retryable_failure_requires_the_literal_true_flag() -> None:
    assert (
        ar._is_retryable_failure(AgentResult(success=False, metadata={"retryable": True})) is True
    )
    assert (
        ar._is_retryable_failure(AgentResult(success=False, metadata={"retryable": "yes"})) is False
    )
    assert ar._is_retryable_failure(AgentResult(success=False)) is False


def test_classify_skip_reason_covers_stale_malformed_and_missing_verdict() -> None:
    stale = AgentResult(
        success=True, terminal_submission_received=True, diagnostics={"attempt_id": 0}
    )
    assert ar._classify_skip_reason(stale, 1) is ar.FallbackReason.stale_attempt

    usable = AgentResult(
        success=True, terminal_submission_received=True, diagnostics={"attempt_id": 1}
    )
    assert ar._classify_skip_reason(usable, 1) is None

    failed = AgentResult(success=False, error="connection reset")
    assert ar._classify_skip_reason(failed, 0) is ar.FallbackReason.provider_error

    malformed = AgentResult(success=True, diagnostics={"malformed_submission": True})
    assert ar._classify_skip_reason(malformed, 0) is ar.FallbackReason.malformed_submission

    silent = AgentResult(success=True)
    assert ar._classify_skip_reason(silent, 0) is ar.FallbackReason.no_terminal_verdict


def _tool_state(**kwargs: Any) -> Any:
    from mergecraft.mcp.tool_state import ToolState

    return ToolState(repos={}, primary_repo_key="main", **kwargs)


def test_incomplete_review_success_ignores_scripted_calls_without_tool_state() -> None:
    result = AgentResult(success=True)
    assert ar._is_incomplete_review_success(result, None) is False
    assert ar._is_incomplete_review_success(AgentResult(success=False), _tool_state()) is False


def test_incomplete_review_success_is_false_outside_review_modes() -> None:
    state = _tool_state(selected_mode="Plan")
    assert ar._is_incomplete_review_success(AgentResult(success=True), state) is False


def test_incremental_review_with_a_final_summary_is_complete() -> None:
    state = _tool_state(selected_mode="IncrementalReview", final_summary_written=True)
    assert ar._is_incomplete_review_success(AgentResult(success=True), state) is False


def test_review_without_any_submission_is_incomplete() -> None:
    state = _tool_state(selected_mode="Review")
    assert ar._is_incomplete_review_success(AgentResult(success=True), state) is True


def test_prepare_chain_attempt_clears_a_prior_terminal_submission() -> None:
    state = _tool_state(selected_mode="Review")
    state.terminal_submission = object()  # type: ignore[assignment]  # — opaque sentinel; only cleared
    state.terminal_submission_conflict = True
    ar._prepare_chain_attempt(state, 2)
    assert state.terminal_submission is None
    assert state.terminal_submission_conflict is False
    assert (state.attempt_id, state.fallback_index) == (2, 2)
    # ``None`` tool state is a no-op rather than an AttributeError.
    ar._prepare_chain_attempt(None, 3)


def test_attach_model_evidence_stamps_fallback_fields() -> None:
    stamped = ar._attach_model_evidence(
        AgentResult(success=True, metadata={"keep": 1}),
        requested_model="openai/gpt-codex",
        executed_model="google/gemini-3-pro",
        fallback_index=1,
        fallback_reason=ar.FallbackReason.timeout,
    )
    assert stamped.metadata == {
        "keep": 1,
        "requested_model": "openai/gpt-codex",
        "executed_model": "google/gemini-3-pro",
        "provider": "google",
        "fallback_index": 1,
        "fallback_occurred": True,
        "fallback_reason": ar.FallbackReason.timeout,
    }


def test_attach_model_evidence_omits_the_reason_when_nothing_was_skipped() -> None:
    stamped = ar._attach_model_evidence(
        AgentResult(success=True),
        requested_model="openai/gpt",
        executed_model="openai/gpt",
        fallback_index=0,
    )
    assert "fallback_reason" not in stamped.metadata
    assert stamped.metadata["fallback_occurred"] is False


def test_promote_model_evidence_keeps_existing_values_for_blank_inputs() -> None:
    state = _tool_state()
    state.requested_model = "openai/gpt"
    state.model = "openai/gpt"
    ar.promote_model_evidence(state, requested_model=None, executed_model="", fallback_index=2)
    assert state.requested_model == "openai/gpt"
    assert state.model == "openai/gpt"
    assert state.fallback_index == 2
    assert state.fallback_occurred is True


def test_empty_chain_result_is_a_flagged_failure() -> None:
    result = ar._empty_chain_result()
    assert result.success is False
    assert result.error == "no model chain configured"
    assert result.metadata["empty_chain"] is True


# ---------------------------------------------------------------------------
# harness resolution
# ---------------------------------------------------------------------------


def test_agent_mode_for_slug_maps_each_native_provider_and_defaults_to_opencode() -> None:
    assert ar._agent_mode_for_slug("anthropic/claude-sonnet") == "claude"
    assert ar._agent_mode_for_slug("openai/gpt") == "codex"
    assert ar._agent_mode_for_slug("google/gemini-3-pro") == "gemini"
    assert ar._agent_mode_for_slug("cursor/composer") == "cursor"
    assert ar._agent_mode_for_slug("nous/deepseek-v4") == "opencode"
    assert ar._agent_provider_for_slug("no-slash-here") == "unknown"


def test_resolve_harness_infers_when_unset_and_validates_when_set() -> None:
    inferred = RepoSettings.model_validate({})
    assert ar.resolve_harness(inferred, "openai/gpt") == "codex"

    explicit = RepoSettings.model_validate({"harness": "opencode"})
    assert ar.resolve_harness(explicit, "openai/gpt") == "opencode"
    # Uncatalogued prefixes route through OpenCode too.
    assert ar.resolve_harness(explicit, "acme/private-1") == "opencode"


def test_opencode_refuses_a_catalogued_provider_it_does_not_serve() -> None:
    explicit = RepoSettings.model_validate({"harness": "opencode"})
    with pytest.raises(ar.ModelFallbackPolicyError, match="incompatible"):
        ar.resolve_harness(explicit, "google/gemini-3-pro")


def test_native_harness_refuses_a_foreign_provider() -> None:
    explicit = RepoSettings.model_validate({"harness": "claude"})
    assert ar.resolve_harness(explicit, "anthropic/claude-sonnet") == "claude"
    with pytest.raises(ar.ModelFallbackPolicyError, match=r"provider 'openai'"):
        ar.resolve_harness(explicit, "openai/gpt")


def test_attempt_harness_label_prefers_the_explicit_override() -> None:
    explicit = RepoSettings.model_validate({"harness": "opencode"})
    # A tail slug the harness could not actually run still stamps the override
    # rather than re-validating.
    assert ar._attempt_harness_label(explicit, "google/gemini-3-pro") == "opencode"
    assert ar._attempt_harness_label(None, "google/gemini-3-pro") == "gemini"
    assert ar._attempt_harness_label(RepoSettings.model_validate({}), "openai/gpt") == "codex"


# ---------------------------------------------------------------------------
# cost attrs
# ---------------------------------------------------------------------------


class _Usage:
    def __init__(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


def test_cost_attrs_emit_both_mergecraft_and_genai_names() -> None:
    attrs = ar._cost_attrs_from_usage(
        _Usage(
            input_tokens=10,
            output_tokens=4,
            cache_read_tokens=2,
            cache_write_tokens=1,
            cost_usd=0.5,
        )
    )
    assert attrs["cost.tokens_in"] == 10
    assert attrs["cost.tokens_out"] == 4
    assert attrs["cost.cache_read"] == 2
    assert attrs["cost.cache_write"] == 1
    assert attrs["cost.usd"] == 0.5
    assert attrs["gen_ai.usage.input_tokens"] == 10
    assert attrs["gen_ai.usage.cache_creation_input_tokens"] == 1
    assert attrs["gen_ai.usage.cost_usd"] == 0.5


def test_cost_attrs_drop_missing_and_non_numeric_fields() -> None:
    assert ar._cost_attrs_from_usage(_Usage()) == {}
    attrs = ar._cost_attrs_from_usage(_Usage(input_tokens="12", cost_usd=None))
    assert attrs == {}


# ---------------------------------------------------------------------------
# _slug_runnable
# ---------------------------------------------------------------------------


def test_slug_runnable_accepts_custom_prefixes_but_not_uncredentialled_natives() -> None:
    assert ar._slug_runnable("openai/gpt") is False
    assert ar._slug_runnable("acme/private-1") is True
    assert ar._slug_runnable("no-slash") is False


def test_slug_runnable_accepts_a_native_slug_once_credentials_exist(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    assert ar._slug_runnable("openai/gpt") is True


# ---------------------------------------------------------------------------
# resolve_model / _resolve_slug
# ---------------------------------------------------------------------------


def test_bedrock_alias_requires_the_pinned_model_id(monkeypatch: MonkeyPatch) -> None:
    with pytest.raises(ValueError, match=BEDROCK_MODEL_ID_ENV):
        ar.resolve_model(slug="bedrock/byok")
    monkeypatch.setenv(BEDROCK_MODEL_ID_ENV, "anthropic.claude-3-5-sonnet-v2")
    assert ar.resolve_model(slug="bedrock/byok") == "anthropic.claude-3-5-sonnet-v2"


def test_vertex_alias_requires_the_pinned_model_id(monkeypatch: MonkeyPatch) -> None:
    with pytest.raises(ValueError, match=VERTEX_MODEL_ID_ENV):
        ar.resolve_model(slug="vertex/byok")
    monkeypatch.setenv(VERTEX_MODEL_ID_ENV, "claude-sonnet-4@20250514")
    assert ar.resolve_model(slug="vertex/byok") == "claude-sonnet-4@20250514"


def test_resolve_model_explicit_slug_outranks_the_env_override(
    monkeypatch: MonkeyPatch,
) -> None:
    """CLI beats ENV, matching ``ConfigLayer`` (issue #468)."""
    monkeypatch.setenv("MERGECRAFT_MODEL", "acme/private-1")
    assert ar.resolve_model(slug="acme/other-1") == "acme/other-1"
    assert ar.resolve_model(slug="acme/other-1", respect_env_override=False) == "acme/other-1"


def test_resolve_model_falls_back_to_the_env_override_without_a_slug(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("MERGECRAFT_MODEL", "acme/private-1")
    assert ar.resolve_model() == "acme/private-1"
    assert ar.resolve_model(slug="  ") == "acme/private-1"
    assert ar.resolve_model(respect_env_override=False) is None


def test_resolve_model_reports_an_unknown_explicit_slug_instead_of_using_env(
    monkeypatch: MonkeyPatch,
) -> None:
    """An explicit request is never silently swapped for the env value."""
    monkeypatch.setenv("MERGECRAFT_MODEL", "acme/private-1")
    assert ar.resolve_model(slug="gpt-4o-latest") is None


def test_resolve_model_passes_through_a_raw_specifier_but_drops_a_bare_name() -> None:
    assert ar.resolve_model(slug="acme/private-1") == "acme/private-1"
    assert ar.resolve_model(slug="gpt-4o-latest") is None
    assert ar.resolve_model(slug="   ") is None
    assert ar.resolve_model() is None


# ---------------------------------------------------------------------------
# resolve_runtime_agent
# ---------------------------------------------------------------------------


def test_env_agent_override_wins_and_an_unknown_one_falls_through(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("MERGECRAFT_AGENT", "gemini")
    assert ar.resolve_runtime_agent(model="openai/gpt").name == "gemini"
    monkeypatch.setenv("MERGECRAFT_AGENT", "not-an-agent")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    assert ar.resolve_runtime_agent(model="openai/gpt").name == "codex"


def test_explicit_harness_setting_overrides_provider_inference(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    settings = RepoSettings.model_validate({"harness": "opencode"})
    assert ar.resolve_runtime_agent(model="openai/gpt", settings=settings).name == "opencode"
    # No model to validate against — the configured harness is returned as-is.
    assert ar.resolve_runtime_agent(model=None, settings=settings).name == "opencode"


def test_bedrock_routing_splits_anthropic_ids_from_the_rest(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "aws-bearer")
    monkeypatch.setenv(BEDROCK_MODEL_ID_ENV, "anthropic.claude-3-5-sonnet")
    assert ar.resolve_runtime_agent(model="anthropic.claude-3-5-sonnet").name == "claude"
    monkeypatch.setenv(BEDROCK_MODEL_ID_ENV, "meta.llama3-70b")
    assert ar.resolve_runtime_agent(model="meta.llama3-70b").name == "opencode"


def test_vertex_routing_splits_claude_ids_from_the_rest(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "sa.json")
    monkeypatch.setenv(VERTEX_MODEL_ID_ENV, "claude-sonnet-4")
    assert ar.resolve_runtime_agent(model="claude-sonnet-4").name == "claude"
    monkeypatch.setenv(VERTEX_MODEL_ID_ENV, "gemini-3-pro")
    assert ar.resolve_runtime_agent(model="gemini-3-pro").name == "opencode"


def test_openai_without_a_credential_fails_loud_naming_both_env_vars() -> None:
    with pytest.raises(ValueError, match="CODEX_AUTH_JSON, OPENAI_API_KEY"):
        ar.resolve_runtime_agent(model="openai/gpt")


def test_google_and_cursor_fail_loud_without_credentials() -> None:
    with pytest.raises(ValueError, match="GEMINI_API_KEY, GOOGLE_GENERATIVE_AI_API_KEY"):
        ar.resolve_runtime_agent(model="google/gemini-3-pro")
    with pytest.raises(ValueError, match="CURSOR_API_KEY"):
        ar.resolve_runtime_agent(model="cursor/composer")


def test_credentialled_native_providers_resolve_to_their_agent(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    monkeypatch.setenv("CURSOR_API_KEY", "c-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.setenv("CODEX_AUTH_JSON", CODEX_SUBSCRIPTION_JSON)
    assert ar.resolve_runtime_agent(model="google/gemini-3-pro").name == "gemini"
    assert ar.resolve_runtime_agent(model="cursor/composer").name == "cursor"
    assert ar.resolve_runtime_agent(model="anthropic/claude-sonnet").name == "claude"
    assert ar.resolve_runtime_agent(model="openai/gpt").name == "codex"


def test_anthropic_without_credentials_falls_through_to_opencode() -> None:
    """Anthropic is the one native provider with no fail-loud arm."""
    assert ar.resolve_runtime_agent(model="anthropic/claude-sonnet").name == "opencode"


def test_gateway_providers_fail_loud_with_their_own_auth_command() -> None:
    with pytest.raises(ValueError, match="mergecraft auth nous"):
        ar.resolve_runtime_agent(model="nous/deepseek-v4")
    with pytest.raises(ValueError, match="mergecraft auth tokenhub"):
        ar.resolve_runtime_agent(model="tokenhub/hy3")
    with pytest.raises(ValueError, match="mergecraft auth minimax"):
        ar.resolve_runtime_agent(model="minimax/MiniMax-M3")


def test_gateway_providers_resolve_to_opencode_once_credentialled(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOUS_API_KEY", "nous-key")
    monkeypatch.setenv("TOKENHUB_API_KEY", "th-key")
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY", "custom-key")
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_BASE_URL", "https://example.invalid/v1")
    assert ar.resolve_runtime_agent(model="nous/deepseek-v4").name == "opencode"
    assert ar.resolve_runtime_agent(model="tokenhub/hy3").name == "opencode"
    assert ar.resolve_runtime_agent(model="minimax/MiniMax-M3").name == "opencode"


def test_unknown_provider_and_no_model_both_land_on_opencode() -> None:
    assert ar.resolve_runtime_agent(model="acme/private-1").name == "opencode"
    assert ar.resolve_runtime_agent(model=None).name == "opencode"
