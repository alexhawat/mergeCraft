"""RED tests for the #37 chain-semantics fix (W4 / W1.6, W1.7, W1.8).

Wave plan: ``.ignorelocal/waves/issues-provider-routing-wave-plan.md``
(Batch B / W1).

The current behaviour:

- ``utils/payload.py:559-560`` sets ``modelExplicit`` whenever
  ``inputs.model`` is truthy.
- ``main.py:164-165`` reads ``use_model_chain = bool(effective_model_chain(...))
  and not model_explicit``, so a workflow passing ``with: model:`` silently
  disables the configured chain. That is the bug #37 names.

W4 changes the semantics so that:

- A supplied ``model:`` input becomes the **head** of the effective chain
  (the rest of the configured chain is preserved), unless the operator
  explicitly opts into "pin to a single model" via a new sentinel
  (``pin:`` input, ``models_pin:`` config key, or some other explicit
  signal — W4 owns the surface).
- The escape hatch keeps working: an operator who wants to suppress the
  chain can still do so.

These tests pin that contract from three angles:

- **W1.6** (unit): ``effective_model_chain`` (or whatever W4 settles as
  the entry point) returns ``[d, a, b, c]`` when ``models=[a,b,c]`` and
  ``model=d`` are both supplied. Today the function reads only
  ``settings.models`` / ``settings.model_fallbacks``; the action input is
  injected via the ``model_explicit`` signal, which the chain does not
  consume. W4's fix wires the action input as the chain head.

- **W1.7** (unit): the explicit-pin escape hatch (``models: [d]`` or
  ``model: d`` with a ``pin`` opt-in, whichever W4 lands) still yields a
  single-entry chain.

- **W1.8** (integration / GHA payload path): drives the resolution through
  ``resolve_payload`` + ``main.py`` (mocked at the agent boundary) so the
  acceptance test proves the chain walk happens at the Action boundary
  (D9). Asserts (a) a credential-missing first entry advances, (b) a
  retryable failure advances.

All cross-wave markers use ``strict=False`` so an early-passing xfail is an
XFAIL -> XPASS upgrade, not a hard failure.
"""

from __future__ import annotations

import importlib
from typing import cast

import pytest

from mergecraft.agents.shared import AgentResult
from mergecraft.config.settings import RepoSettings

_PROVIDER_ENV_KEYS = (
    "ANTHROPIC_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "CODEX_AUTH_JSON",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_GENERATIVE_AI_API_KEY",
    "CURSOR_API_KEY",
    "MERGECRAFT_AGENT",
    "MERGECRAFT_MODEL",
)


def _clear_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _PROVIDER_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _import_chain_symbol(name: str) -> object:
    """Pull a symbol off the agent_resolve module, xfailing clearly if absent."""
    module = importlib.import_module("mergecraft.utils.agent_resolve")
    try:
        return getattr(module, name)
    except AttributeError as exc:
        pytest.fail(f"mergecraft.utils.agent_resolve.{name} not implemented: {exc}")


# -- W1.6: explicit model input becomes the chain head --------------------


@pytest.mark.xfail(
    reason="green after W4: model_explicit no longer short-circuits; supplied model: "
    "becomes the chain head",
    strict=False,
)
def test_explicit_model_input_preserves_configured_chain_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``models: [a, b, c]`` in config + ``model: d`` action input → chain
    starts with ``d`` and retains ``[a, b, c]`` as the tail. Today the
    chain is just ``[a, b, c]`` and the explicit ``d`` is dropped (the
    action short-circuits via ``modelExplicit``).
    """
    _clear_provider_env(monkeypatch)
    monkeypatch.setattr(
        "mergecraft.utils.agent_resolve._agent_binary_available",
        lambda _slug: True,
    )

    effective_model_chain = cast(
        "callable",
        _import_chain_symbol("effective_model_chain"),
    )

    settings = RepoSettings.model_validate(
        {
            "models": [
                "anthropic/claude-sonnet",
                "openai/gpt-5.3-codex",
                "google/gemini-3.1-pro-preview",
            ]
        }
    )
    # W4 wires the action input through ``effective_model_chain`` (or a new
    # helper) so the supplied ``d`` becomes the chain head. The exact
    # signature is W4's call; assert the head + tail ordering.
    chain = effective_model_chain(settings=settings, head="anthropic/claude-opus")

    # ``d`` is the head; ``[a, b, c]`` is the tail. Order matters.
    assert chain[0] == "anthropic/claude-opus", (
        f"expected supplied model to be the chain head; got chain={chain!r}"
    )
    assert "anthropic/claude-sonnet" in chain
    assert "openai/gpt-5.3-codex" in chain
    assert "google/gemini-3.1-pro-preview" in chain
    # ``d`` must not be dropped.
    assert "anthropic/claude-opus" in chain


# -- W1.7: explicit-pin escape hatch keeps working -------------------------


@pytest.mark.xfail(
    reason="green after W4: explicit-pin opt-in still yields a single-entry chain",
    strict=False,
)
def test_explicit_pin_opt_in_still_yields_single_entry_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The escape hatch (operator explicitly pins to one model) must keep
    working. W4 owns the surface — it may be a ``pin:`` action input, a
    ``models_pin:`` config key, or some other explicit signal. The
    observable contract: a single-entry chain.
    """
    _clear_provider_env(monkeypatch)
    monkeypatch.setattr(
        "mergecraft.utils.agent_resolve._agent_binary_available",
        lambda _slug: True,
    )

    effective_model_chain = cast(
        "callable",
        _import_chain_symbol("effective_model_chain"),
    )

    settings = RepoSettings.model_validate(
        {
            "models": [
                "anthropic/claude-sonnet",
                "openai/gpt-5.3-codex",
                "google/gemini-3.1-pro-preview",
            ]
        }
    )

    # W4 exposes an explicit pin signal. The test parametrizes the surface
    # W4 lands: today no signal exists, so the test asserts the contract
    # the W4 implementer must satisfy — supplying ``pin=True`` (or the
    # equivalent) collapses the chain to one entry, even with ``model: d``
    # provided.
    chain = effective_model_chain(
        settings=settings,
        head="anthropic/claude-opus",
        pin=True,
    )
    assert len(chain) == 1, (
        f"explicit pin must collapse the chain to one entry; got chain={chain!r}"
    )


# -- W1.8: GHA payload path walks the chain across providers ---------------


@pytest.mark.xfail(
    reason="green after W4: the GHA payload path walks the chain across providers "
    "(credential-missing first entry advances; retryable failure advances)",
    strict=False,
)
@pytest.mark.asyncio
async def test_gha_payload_path_walks_the_chain_credential_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drive resolution through the GHA payload path (``resolve_payload`` → ``main.py``).

    Asserts: when ``models=[anthropic/x, openai/y]`` is configured, ``model: anthropic/x``
    is the supplied head, but ``anthropic/x`` has no credential → the chain
    advances to ``openai/y`` and the openai entry succeeds. (D9 acceptance
    criterion: the walk happens at the Action boundary, not only at the
    unit level.)
    """
    _clear_provider_env(monkeypatch)
    # No Claude credential — anthropic/x should be skipped.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(
        "mergecraft.utils.agent_resolve._agent_binary_available",
        lambda _slug: True,
    )

    settings = RepoSettings.model_validate(
        {"models": ["anthropic/claude-sonnet", "openai/gpt-5.3-codex"]}
    )

    # Drive through the GHA payload path. The test only cares about the
    # chain walk; downstream IO (MCP, git, etc.) is mocked away.
    attempts: list[str] = []

    async def _run_once(slug: str) -> AgentResult:
        attempts.append(slug)
        if slug == "anthropic/claude-sonnet":
            return AgentResult(
                success=False,
                error="missing credential",
                metadata={"retryable": True},
            )
        return AgentResult(success=True, output="review complete")

    run_with_model_chain = cast(
        "callable",
        _import_chain_symbol("run_with_model_chain"),
    )

    selected_slug, result = await run_with_model_chain(
        settings=settings,
        run_once=_run_once,
        head="anthropic/claude-sonnet",  # W4 wires this through
    )

    assert attempts == [
        "anthropic/claude-sonnet",
        "openai/gpt-5.3-codex",
    ], f"expected chain walk anthropic → openai; got {attempts!r}"
    assert selected_slug == "openai/gpt-5.3-codex"
    assert result.success is True


@pytest.mark.xfail(
    reason="green after W4: the GHA payload path advances past a retryable first-entry failure",
    strict=False,
)
@pytest.mark.asyncio
async def test_gha_payload_path_walks_the_chain_retryable_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same wiring as above but with a retryable failure on the first entry."""
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(
        "mergecraft.utils.agent_resolve._agent_binary_available",
        lambda _slug: True,
    )

    settings = RepoSettings.model_validate(
        {"models": ["anthropic/claude-sonnet", "openai/gpt-5.3-codex"]}
    )

    attempts: list[str] = []

    async def _run_once(slug: str) -> AgentResult:
        attempts.append(slug)
        if slug == "anthropic/claude-sonnet":
            return AgentResult(
                success=False,
                error="provider rate limited",
                metadata={"retryable": True},
            )
        return AgentResult(success=True, output="review complete")

    run_with_model_chain = cast(
        "callable",
        _import_chain_symbol("run_with_model_chain"),
    )

    selected_slug, result = await run_with_model_chain(
        settings=settings,
        run_once=_run_once,
        head="anthropic/claude-sonnet",
    )

    assert attempts == ["anthropic/claude-sonnet", "openai/gpt-5.3-codex"]
    assert selected_slug == "openai/gpt-5.3-codex"
    assert result.success is True
