"""HA3 suite — explicit ``harness:`` selection (D11).

Wave plan: ``.ignorelocal/01-review-integrity-wave-plan.md`` (PR HA3).
Locked decision **D11**: ``harness:`` set → use it. Unset → today's
provider/model inference. Unsupported combination → configuration error,
never silent routing. Existing ``nous/deepseek-*`` configs must keep
working untouched.

Target API (HA3.2): ``RepoSettings.harness`` is
    ``Literal["opencode", "codex", "claude", "gemini", "cursor"] | None = None``.
``resolve_harness(settings, slug)`` honours the explicit value (validated
against HA1 capabilities) and otherwise delegates to
``_agent_mode_for_slug``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mergecraft.config.settings import RepoSettings
from mergecraft.utils.agent_resolve import (
    _NATIVE_HARNESS_PROVIDERS,
    _OPENCODE_NATIVE_PROVIDERS,
    _agent_mode_for_slug,
    _harness_supports_provider,
    resolve_harness,
)

if TYPE_CHECKING:
    from pathlib import Path

NOUS_CATALOG_SLUG = "nous/deepseek/deepseek-v4-flash"
NOUS_SHORT_SLUG = "nous/deepseek-v4-flash"
OPENAI_SLUG = "openai/gpt-5.3-codex"
ANTHROPIC_SLUG = "anthropic/claude-sonnet"
GEMINI_SLUG = "google/gemini-3.1-pro-preview"
CURSOR_SLUG = "cursor/cloud-agent"

_ALLOWED_HARNESSES = ("opencode", "codex", "claude", "gemini", "cursor")

# Today's inference (``_agent_mode_for_slug``): anthropic→claude, openai→codex,
# google→gemini, cursor→cursor, else opencode. ``nous/*`` therefore already
# selects opencode.
_INFERENCE_MATRIX: tuple[tuple[str, str], ...] = (
    (NOUS_SHORT_SLUG, "opencode"),
    (NOUS_CATALOG_SLUG, "opencode"),
    (OPENAI_SLUG, "codex"),
    (ANTHROPIC_SLUG, "claude"),
    (GEMINI_SLUG, "gemini"),
    (CURSOR_SLUG, "cursor"),
)


def _configuration_error_types() -> tuple[type[BaseException], ...]:
    """Exception types ``main._classify_error_outcome`` already maps to
    ``configuration_error``. HA3.2 must reuse one of these — not a new branch.
    """
    from pydantic import ValidationError

    from mergecraft.main import _ConfigurationError
    from mergecraft.utils.agent_resolve import ModelFallbackPolicyError

    return (_ConfigurationError, ModelFallbackPolicyError, ValidationError)


# ── Pins that pass today (harness unset → existing inference) ────────────────


def test_existing_nous_config_still_selects_opencode(tmp_path: Path) -> None:
    """Compatibility pin — a ``nous/deepseek-*`` YAML with harness unset
    still resolves to the opencode harness via today's inference.

    Guard: deleting ``_agent_mode_for_slug``'s else-opencode path (or
    special-casing ``nous`` away from opencode) fails this test.
    """
    from mergecraft.config.settings import load_repo_settings

    config = tmp_path / ".mergecraft" / "config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(f"model: {NOUS_CATALOG_SLUG}\n", encoding="utf-8")
    settings = load_repo_settings(path=config, root=tmp_path, load_learnings_files=False)

    assert settings.model == NOUS_CATALOG_SLUG
    assert getattr(settings, "harness", None) is None
    assert _agent_mode_for_slug(NOUS_CATALOG_SLUG) == "opencode"
    assert _agent_mode_for_slug(NOUS_SHORT_SLUG) == "opencode"


def test_codex_remains_selectable() -> None:
    """Pin — openai slugs with harness unset still infer the Codex harness."""
    from mergecraft.agents import resolve_agent

    assert getattr(RepoSettings.model_validate({"model": OPENAI_SLUG}), "harness", None) is None
    assert _agent_mode_for_slug(OPENAI_SLUG) == "codex"
    assert _NATIVE_HARNESS_PROVIDERS["codex"] == frozenset({"openai"})
    assert resolve_agent("codex").name == "codex"


def test_claude_gemini_cursor_remain_selectable() -> None:
    """Pin — anthropic/google/cursor slugs with harness unset still infer
    their native harnesses.
    """
    from mergecraft.agents import resolve_agent

    expected = (
        (ANTHROPIC_SLUG, "claude"),
        (GEMINI_SLUG, "gemini"),
        (CURSOR_SLUG, "cursor"),
    )
    for slug, harness in expected:
        assert getattr(RepoSettings.model_validate({"model": slug}), "harness", None) is None
        assert _agent_mode_for_slug(slug) == harness, (
            f"{slug!r} must infer {harness!r}; got {_agent_mode_for_slug(slug)!r}"
        )
        assert resolve_agent(harness).name == harness
    assert {
        "codex": frozenset({"openai"}),
        "claude": frozenset({"anthropic"}),
        "gemini": frozenset({"google"}),
        "cursor": frozenset({"cursor"}),
    } == _NATIVE_HARNESS_PROVIDERS


def test_inference_path_unchanged_when_harness_unset() -> None:
    """Regression pin over today's model-slug → harness inference matrix.

    ``harness`` omitted (or default ``None``) must keep ``_agent_mode_for_slug``
    behaviour byte-for-byte: anthropic→claude, openai→codex, google→gemini,
    cursor→cursor, else opencode.
    """
    for slug, expected in _INFERENCE_MATRIX:
        settings = RepoSettings.model_validate({"model": slug})
        assert getattr(settings, "harness", None) is None, (
            f"{slug!r}: harness must be unset for the inference pin"
        )
        assert _agent_mode_for_slug(slug) == expected, (
            f"{slug!r} inferred {_agent_mode_for_slug(slug)!r}, expected {expected!r}"
        )


# ── Explicit harness, validation, telemetry ──────────────────────────────────


def test_explicit_harness_overrides_inference() -> None:
    """D11 — ``harness:`` set wins over provider/model inference.

    Fails if the override is deleted and the resolver falls through to
    ``_agent_mode_for_slug`` alone: openai infers ``codex``, anthropic infers
    ``claude``; explicit ``opencode`` must win in both cases (vice versa).
    """
    assert (
        frozenset({"nous", "tokenhub", "minimax", "openai", "anthropic"})
        == _OPENCODE_NATIVE_PROVIDERS
    )
    assert _harness_supports_provider("opencode", "openai") is True
    assert _harness_supports_provider("opencode", "anthropic") is True
    cases = (
        (OPENAI_SLUG, "codex", "opencode"),
        (ANTHROPIC_SLUG, "claude", "opencode"),
    )
    for slug, inferred, explicit in cases:
        assert _agent_mode_for_slug(slug) == inferred
        settings = RepoSettings.model_validate({"model": slug, "harness": explicit})
        assert settings.harness == explicit
        resolved = resolve_harness(settings, slug)
        assert resolved == explicit, (
            f"D11: {slug!r} with harness={explicit!r} must resolve to {explicit!r} "
            f"(inferred {inferred!r}); got {resolved!r}"
        )


def test_opencode_with_non_nous_provider_resolves() -> None:
    """OpenAI-compatible model under OpenCode — no review-logic duplication.

    An openai-prefixed slug infers Codex today. Explicit ``harness: opencode``
    must select the same ``opencode`` agent the Nous path already uses.
    """
    from mergecraft.agents import agents, resolve_agent

    assert _agent_mode_for_slug(OPENAI_SLUG) == "codex"
    settings = RepoSettings.model_validate({"model": OPENAI_SLUG, "harness": "opencode"})
    resolved = resolve_harness(settings, OPENAI_SLUG)
    assert resolved == "opencode"
    agent = resolve_agent(resolved)
    assert agent.name == "opencode"
    assert agent is agents["opencode"]
    assert agent is resolve_agent("opencode")


def test_unsupported_combination_is_a_configuration_error() -> None:
    """D11 — unsupported (harness, provider/model) is a configuration error
    naming both halves. Never silent routing.

    Fails if the combo check is deleted and ``harness: claude`` on a Nous
    slug quietly resolves to claude (or opencode). The raised type must
    already map through ``main._classify_error_outcome`` — do not invent a
    new exception branch.
    """
    from mergecraft.main import _classify_error_outcome
    from mergecraft.run_outcome import RunOutcome

    harness = "claude"
    slug = NOUS_CATALOG_SLUG
    assert _harness_supports_provider(harness, "nous") is False
    settings = RepoSettings.model_validate({"model": slug, "harness": harness})

    with pytest.raises(_configuration_error_types()) as exc_info:
        resolve_harness(settings, slug)

    message = str(exc_info.value)
    lowered = message.lower()
    assert harness in lowered, f"error must name the harness {harness!r}: {message}"
    assert "nous" in lowered or "deepseek" in lowered or slug.lower() in lowered, (
        f"error must name the provider/model half ({slug!r}): {message}"
    )
    assert _classify_error_outcome(exc_info.value) is RunOutcome.configuration_error, (
        "unsupported combo must reuse an existing configuration_error mapping; "
        f"got {_classify_error_outcome(exc_info.value)!r} for {exc_info.value!r}"
    )


def test_unknown_harness_value_fails_closed() -> None:
    """Unknown ``harness`` *value* is a ValidationError naming the key.

    ``RepoSettings`` already forbids unknown *keys*; an unknown *value* for
    the new field needs the Literal. A valid member must be accepted first
    so this cannot pass today via extra-forbid on the key itself.
    """
    from pydantic import ValidationError

    assert "harness" in RepoSettings.model_fields
    assert RepoSettings.model_validate({}).harness is None
    for value in _ALLOWED_HARNESSES:
        parsed = RepoSettings.model_validate({"harness": value})
        assert parsed.harness == value

    with pytest.raises(ValidationError) as exc_info:
        RepoSettings.model_validate({"harness": "foo"})
    text = str(exc_info.value)
    assert "harness" in text, f"error must name the key: {text}"


def test_harness_reaches_telemetry() -> None:
    """Resolved harness is recorded on the attempt (span attr or result metadata).

    Drive a real ``run_with_model_chain`` stamp. openai infers ``codex``;
    explicit ``harness: opencode`` must appear on the attempt so deleting
    the stamp cannot hide the override.
    """
    import asyncio

    from mergecraft.agents.shared import AgentResult
    from mergecraft.tracing.sinks import sink_factory
    from mergecraft.utils.agent_resolve import run_with_model_chain

    settings = RepoSettings.model_validate(
        {
            "harness": "opencode",
            "model": OPENAI_SLUG,
            "tracing": {"enabled": True, "sinks": [{"type": "memory"}]},
        }
    )
    wrapper = sink_factory(settings.tracing)
    memory = wrapper.inner.sinks[0]

    async def run_once(_slug: str) -> AgentResult:
        return AgentResult(success=True)

    _slug, result = asyncio.run(run_with_model_chain(settings=settings, run_once=run_once))

    attempts = [event for event in memory.events if getattr(event, "kind", None) == "agent.attempt"]
    assert attempts, "expected at least one agent.attempt span"
    attrs = attempts[0].attrs
    recorded = {
        attrs.get("agent.mode"),
        attrs.get("model.mode"),
        attrs.get("gen_ai.agent.name"),
        attrs.get("harness"),
        attrs.get("agent.harness"),
        (result.metadata or {}).get("harness"),
    }
    assert "opencode" in recorded, (
        "resolved harness opencode must appear on the attempt span or result "
        f"metadata; got attrs={attrs!r} metadata={result.metadata!r}"
    )
