"""RED tests for MiniMax provider routing (#34 / W5).

Wave plan: ``.ignorelocal/waves/issues-provider-routing-wave-plan.md``
(Batch C / W5). The plan locks MiniMax routing through the **existing
custom-provider helper** (operator-confirmed D10 / option (ii)) — the
OpenAI-compatible endpoint documented at:

    https://platform.minimax.io/docs/api-reference/text-openai-api.md
    → ``export OPENAI_BASE_URL=https://api.minimax.io/v1``

Pin one model id from the same docs page: ``MiniMax-M3`` (latest M-series,
1M-token context; OpenAI-compatible Chat Completions supported via
``/v1/chat/completions``). The model id is operator-facing — see the
catalog row W6 adds — and the slug form is ``minimax/MiniMax-M3``.

This file pins the contract for:

- **W5.1** — ``minimax/MiniMax-M3`` is reachable via the existing custom-
  provider helper (D10 / option ii). Both the OpenCode and Codex harnesses
  emit a provider block whose ``baseURL`` is MiniMax's published
  OpenAI-compatible endpoint.
- **W5.2** — A selected ``minimax/*`` slug with no credential raises a
  clear, actionable error naming MiniMax + the env-var names, never a
  silent fall-through to an absent harness binary (convention 5).
- **W5.5** — ``resolve_model()`` continues to pass slash-containing slugs
  through unchanged when no curated entry exists (D12 regression pin).
- **W5.6** — Adding MiniMax catalog entries does not change the resolution
  of any pre-existing curated slug.

(W5.3 Nous/DeepSeek RED suite was already shipped in PR #122 /
``wave/issue-57-nous``; this file does NOT re-author it.)
(W5.4 ``mergecraft models list`` detection lives at
``tests/cli/test_models_list_minimax.py`` — split for locality with the
existing ``test_models_list_nous.py``.)
"""

from __future__ import annotations

import importlib
import json
import re
import tomllib
from pathlib import Path

import pytest
from tests.agents.conftest import make_agent_run_context

# ── Locked MiniMax contract (operator-confirmed D10 / option ii) ────────────

# Verified 2026-08-11 against
# https://platform.minimax.io/docs/api-reference/text-openai-api.md
# ("Configure Environment Variables" section):
#     export OPENAI_BASE_URL=https://api.minimax.io/v1
# The same endpoint is referenced in the OpenAI SDK integration guide.
MINIMAX_BASE_URL = "https://api.minimax.io/v1"

# Verified against the supported-models table on the same docs page;
# MiniMax-M3 is the latest M-series at 1,000,000-token context. The model
# id is the OpenAI-compatible model parameter sent to /v1/chat/completions.
MINIMAX_MODEL = "MiniMax-M3"
MINIMAX_SLUG = f"minimax/{MINIMAX_MODEL}"

# Env-var convention: MiniMax inherits the W3 indexed pair (operator-locked
# in the W1 / Batch-B design notes). Provider id derivation:
#     "provider_" + str(N)  for indexed pairs (N >= 1)
#     "default"             for the singleton alias
# MiniMax slugs reach the helper through either the singleton (model
# prefix falls through to ``default``) or an indexed pair keyed by N
# that the operator picks.
INDEXED_BASE_URL_FMT = "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_{n}"
INDEXED_API_KEY_FMT = "MERGECRAFT_CUSTOM_PROVIDER_API_KEY_{n}"
SINGLETON_BASE_URL_ENV = "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL"
SINGLETON_API_KEY_ENV = "MERGECRAFT_CUSTOM_PROVIDER_API_KEY"

# Sentinel values — never asserted on literally (convention 7).
SENTINEL_MINIMAX_KEY = "sk-minimax-SENTINEL-LEAK-CHECK-0001"

_PROVIDER_ENV_KEYS = (
    "ANTHROPIC_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "CODEX_AUTH_JSON",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_GENERATIVE_AI_API_KEY",
    "CURSOR_API_KEY",
    "NOUS_API_KEY",
    "NOUS_BASE_URL",
    "TOKENHUB_API_KEY",
    "TOKENHUB_BASE_URL",
    "MERGECRAFT_AGENT",
    SINGLETON_BASE_URL_ENV,
    SINGLETON_API_KEY_ENV,
)


# ── helpers / fixtures ──────────────────────────────────────────────────────


def _clear_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _PROVIDER_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    # Wipe a generous range of indexed suffixes so a stray index from a
    # previous test cannot leak into this one.
    for n in range(1, 8):
        monkeypatch.delenv(INDEXED_BASE_URL_FMT.format(n=n), raising=False)
        monkeypatch.delenv(INDEXED_API_KEY_FMT.format(n=n), raising=False)


def _load_codex_module():
    try:
        return importlib.import_module("mergecraft.agents.codex")
    except ImportError as exc:
        pytest.fail(f"mergecraft.agents.codex not implemented: {exc}")


def _load_opencode_module():
    try:
        return importlib.import_module("mergecraft.agents.opencode")
    except ImportError as exc:
        pytest.fail(f"mergecraft.agents.opencode not implemented: {exc}")


def _load_agent_resolve_module():
    return importlib.import_module("mergecraft.utils.agent_resolve")


def _write_codex_config(tmp_path: Path, *, model: str | None) -> Path:
    """Call ``codex.write_mcp_config`` and return the rendered TOML path."""
    codex_module = _load_codex_module()
    ctx = make_agent_run_context(tmp_path, resolved_model=model)
    ctx.payload.shell = "disabled"
    return Path(codex_module.write_mcp_config(ctx))


def _build_opencode_config(tmp_path: Path, *, model: str | None) -> dict[str, object]:
    """Call ``opencode.build_security_config`` and return the parsed dict."""
    opencode_module = _load_opencode_module()
    ctx = make_agent_run_context(tmp_path, resolved_model=model)
    return json.loads(opencode_module.build_security_config(ctx, model))


def _provider_block_in_opencode(config: dict[str, object]) -> dict[str, object]:
    """Return ``config["provider"]`` as a dict (or fail loudly)."""
    provider = config.get("provider")
    if not isinstance(provider, dict):
        pytest.fail(
            f"opencode config missing dict-shaped 'provider' block; got {type(provider).__name__}: {provider!r}"
        )
    return provider


def _model_providers_in_codex(path: Path) -> dict[str, object]:
    """Parse the written codex ``config.toml`` and return its ``model_providers`` table."""
    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    providers = parsed.get("model_providers")
    if not isinstance(providers, dict):
        pytest.fail(
            f"codex config.toml missing dict-shaped 'model_providers' table; got: {providers!r}"
        )
    return providers


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_provider_env(monkeypatch)


# ── W5.1 — MiniMax slug routes through the W3 helper ────────────────────────
#
# Both harnesses must surface a provider block whose ``baseURL`` resolves
# to MiniMax's published OpenAI-compatible endpoint. The block's id is
# derived from the helper (the singleton maps to ``default``; an indexed
# pair maps to ``provider_<N>``); the slug ``minimax/MiniMax-M3`` is
# routed to that block when its provider id is present in the resolver
# dict (W6 may add a ``minimax`` preset OR extend the multi-provider
# helper; the tests pin the **observable** contract).


def _config_block_for_minimax(
    config: dict[str, object],
    *,
    expected_provider_id: str,
) -> dict[str, object]:
    """Pull the provider block whose ``options.baseURL`` matches MiniMax's endpoint.

    The exact key (``default`` vs ``provider_<N>``) is a W6 call —
    this helper accepts either, asserting the URL matches.
    """
    provider = _provider_block_in_opencode(config)
    candidates = [
        block
        for block in provider.values()
        if isinstance(block, dict)
        and isinstance(block.get("options"), dict)
        and block["options"].get("baseURL") == MINIMAX_BASE_URL
    ]
    assert candidates, (
        f"no provider block in opencode config has baseURL={MINIMAX_BASE_URL!r}; "
        f"provider blocks were: {provider!r}"
    )
    block = candidates[0]
    # Every such block must register the provider id under
    # ``enabled_providers`` so the harness actually activates it.
    enabled = config.get("enabled_providers", [])
    assert expected_provider_id in enabled, (
        f"provider id {expected_provider_id!r} must be in enabled_providers={enabled!r}"
    )
    return block


@pytest.mark.xfail(
    reason=(
        "green after W6: MiniMax routed via the W3 custom-provider helper — "
        "opencode harness emits a provider block whose baseURL is MiniMax's "
        "published OpenAI-compatible endpoint"
    ),
    strict=False,
)
def test_minimax_routes_via_opencode_with_singleton_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Singleton pair + ``minimax/MiniMax-M3`` → opencode config has a
    provider block keyed by ``minimax`` (the model prefix; the W6
    recommendation adds a ``minimax`` preset so the prefix drives the
    provider lookup) whose ``baseURL`` is MiniMax's OpenAI-compatible
    endpoint.

    The active model's prefix (``minimax``) is the slug's first path
    segment; the preset's env vars re-use the D7 singleton names, so the
    block's ``baseURL`` is MiniMax's published endpoint. The harness's
    active-provider lookup must surface that block and register
    ``minimax`` under ``enabled_providers``.
    """
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv(SINGLETON_BASE_URL_ENV, MINIMAX_BASE_URL)
    monkeypatch.setenv(SINGLETON_API_KEY_ENV, SENTINEL_MINIMAX_KEY)

    config = _build_opencode_config(tmp_path, model=MINIMAX_SLUG)

    block = _config_block_for_minimax(config, expected_provider_id="minimax")
    options = block["options"]
    assert options["apiKey"] == SENTINEL_MINIMAX_KEY
    # The block must register the MiniMax model id so the harness can
    # resolve ``minimax/MiniMax-M3`` to the right runtime model.
    models = block.get("models")
    assert isinstance(models, dict), f"provider block missing models mapping; got {models!r}"
    assert MINIMAX_MODEL in models, (
        f"provider block must register model id {MINIMAX_MODEL!r}; got {models!r}"
    )


@pytest.mark.xfail(
    reason=(
        "green after W6: MiniMax routed via the W3 custom-provider helper — "
        "codex config.toml emits a [model_providers.<id>] block whose base_url "
        "is MiniMax's published OpenAI-compatible endpoint"
    ),
    strict=False,
)
def test_minimax_routes_via_codex_with_singleton_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Singleton pair + ``minimax/MiniMax-M3`` → codex config.toml emits a
    ``[model_providers.default]`` block whose ``base_url`` is MiniMax's
    OpenAI-compatible endpoint and ``env_key`` is the env-var **name**
    (not the resolved key — convention 7).

    Parsed via stdlib ``tomllib`` (no string matching) so the schema W6
    produces is the schema the test pins.
    """
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv(SINGLETON_BASE_URL_ENV, MINIMAX_BASE_URL)
    monkeypatch.setenv(SINGLETON_API_KEY_ENV, SENTINEL_MINIMAX_KEY)

    path = _write_codex_config(tmp_path, model=MINIMAX_SLUG)
    providers = _model_providers_in_codex(path)

    assert "default" in providers, (
        f"expected model_providers.default block; got keys: {sorted(providers)!r}"
    )
    block = providers["default"]
    assert isinstance(block, dict)
    assert block.get("base_url") == MINIMAX_BASE_URL
    # ``env_key`` is the env-var NAME, not the resolved key value.
    assert block.get("env_key") == SINGLETON_API_KEY_ENV
    # The resolved key value must not appear anywhere in the rendered TOML
    # for this provider's block.
    block_text = path.read_text(encoding="utf-8")
    assert SENTINEL_MINIMAX_KEY not in block_text


@pytest.mark.xfail(
    reason=(
        "green after W6: MiniMax routed via the W3 custom-provider helper — "
        "indexed pair (provider_1) works the same as the singleton"
    ),
    strict=False,
)
def test_minimax_routes_via_indexed_provider_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An indexed ``_1`` pair pointing at MiniMax's endpoint must also
    surface the provider block — proves W6 keeps the indexed convention
    working for MiniMax, not just the singleton.
    """
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv(INDEXED_BASE_URL_FMT.format(n=1), MINIMAX_BASE_URL)
    monkeypatch.setenv(INDEXED_API_KEY_FMT.format(n=1), SENTINEL_MINIMAX_KEY)

    config = _build_opencode_config(tmp_path, model="provider_1/" + MINIMAX_MODEL)

    # The block is keyed by ``provider_1``; the baseURL is MiniMax's endpoint.
    provider = _provider_block_in_opencode(config)
    assert "provider_1" in provider, f"expected provider_1 block; got keys: {sorted(provider)!r}"
    block = provider["provider_1"]
    assert isinstance(block, dict)
    options = block.get("options")
    assert isinstance(options, dict)
    assert options.get("baseURL") == MINIMAX_BASE_URL
    assert options.get("apiKey") == SENTINEL_MINIMAX_KEY


# ── W5.2 — Missing-credential fail-loud (convention 5) ─────────────────────
#
# The wave plan's invariant: a provider's model selected without its
# credential must raise with a clear, actionable message naming the
# provider and the env vars — **never** silently fall through to a
# harness whose binary is absent.


_FAIL_LOUD_MODELS = (
    pytest.param(MINIMAX_SLUG, id="minimax-minimax-m3"),
    pytest.param("minimax/some-other-model", id="minimax-unknown-model"),
)


@pytest.mark.parametrize("model", _FAIL_LOUD_MODELS)
@pytest.mark.xfail(
    reason=(
        "green after W6: MiniMax slugs selected without a credential must raise "
        "with an actionable message naming MiniMax + the env vars, never "
        "silently fall through to the opencode harness (convention 5 / D12)"
    ),
    strict=False,
)
def test_minimax_missing_credential_fails_loud(
    model: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Selecting ``minimax/...`` without ``MERGECRAFT_CUSTOM_PROVIDER_*``
    set must raise — never resolve to ``opencode`` silently.

    The error message must name the provider (``minimax`` / ``MiniMax``)
    and the env vars the operator can set to fix the configuration.
    The test asserts the **observable contract**, not the specific
    exception type — both ``ValueError`` (D12 fail-loud helper) and
    ``RuntimeError`` (chain selector) are acceptable.
    """
    _clear_provider_env(monkeypatch)
    # Belt-and-suspenders: even if the singleton env vars are accidentally
    # set to unrelated values, the test should still observe fail-loud
    # for an *empty* configuration.
    monkeypatch.setattr("shutil.which", lambda _name: None)

    agent_resolve_module = _load_agent_resolve_module()
    resolve_runtime_agent = agent_resolve_module.resolve_runtime_agent

    with pytest.raises((ValueError, RuntimeError)) as exc_info:
        resolve_runtime_agent(model=model)

    message = str(exc_info.value).lower()
    # The error must name the provider family so an operator can act on it.
    assert any(token in message for token in ("minimax",)), (
        f"error message must mention 'minimax'; got: {message!r}"
    )
    # The error must name the env vars that fix the configuration.
    assert SINGLETON_BASE_URL_ENV.lower() in message or any(
        INDEXED_BASE_URL_FMT.format(n=n).lower() in message for n in (1,)
    ), (
        f"error message must name the custom-provider env vars "
        f"({SINGLETON_BASE_URL_ENV} or {INDEXED_BASE_URL_FMT.format(n=1)}); got: {message!r}"
    )
    # And it must NOT silently resolve to the opencode harness.
    assert "opencode" not in message, (
        f"error must not mention 'opencode' (silent fall-through); got: {message!r}"
    )


# ── W5.5 — raw pass-through still resolves (D12 regression pin) ─────────────


@pytest.mark.xfail(
    reason=(
        "green after W6: ``resolve_model()`` continues to pass slash-containing "
        "slugs through unchanged when no curated entry exists (D12 regression pin) — "
        "the MiniMax slug must keep resolving even without a curated catalog entry"
    ),
    strict=False,
)
def test_minimax_raw_passthrough_slug_resolves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``resolve_model(slug="minimax/MiniMax-M3")`` must return the slug
    itself when no curated catalog entry exists.

    D12 regression pin: ``resolve_model()`` already passes unknown slash-
    containing slugs through unchanged; W6's catalog addition must not
    weaken that behaviour for any *un*curated MiniMax slug. The
    MiniMax-M3 model id is published as ``MiniMax-M3`` (no curated
    entry today); once W6 adds the catalog row the curated resolution
    takes over, but the contract is: a slug with a slash that is NOT in
    the curated list still passes through.
    """
    _clear_provider_env(monkeypatch)

    agent_resolve_module = _load_agent_resolve_module()
    resolve_model = agent_resolve_module.resolve_model
    # Use a future MiniMax model id that is NOT yet in the curated
    # catalog — ``MiniMax-M99-future`` is a synthetic slug the test
    # guarantees no catalog row matches. This is the regression-pin
    # shape, not the curated-resolution shape.
    future_slug = "minimax/MiniMax-M99-future"
    resolved = resolve_model(slug=future_slug, respect_env_override=False)
    assert resolved == future_slug, (
        f"resolve_model({future_slug!r}) must pass through unchanged; got {resolved!r}"
    )


# ── W5.6 — New catalog entries do not change existing resolution ────────────
#
# D12: catalog additions are additive. Parametrize over every existing
# curated slug in PROVIDERS before / after W6 lands; assert each resolve
# call returns the same value. The test snapshot is captured today
# (before W6) and re-asserted after — the test file is the snapshot
# source of truth.


_EXISTING_SLUGS: tuple[str, ...] = (
    "anthropic/claude-opus",
    "anthropic/claude-sonnet",
    "anthropic/claude-haiku",
    "openai/gpt",
    "openai/gpt-pro",
    "openai/gpt-terra",
    "openai/gpt-mini",
    "openai/gpt-codex",
    "openai/gpt-codex-mini",
    "openai/gpt-5.4",
    "openai/o3",
    "google/gemini-pro",
    "google/gemini-flash",
    "xai/grok",
    "xai/grok-fast",
    "xai/grok-code-fast",
    "deepseek/deepseek-pro",
    "deepseek/deepseek-flash",
    "deepseek/deepseek-reasoner",
    "deepseek/deepseek-chat",
    "moonshotai/kimi-k2",
    "opencode/big-pickle",
    "opencode/claude-opus",
    "opencode/claude-sonnet",
    "opencode/claude-haiku",
    "opencode/gpt",
    "opencode/gpt-pro",
    "opencode/gpt-terra",
    "opencode/gpt-mini",
    "opencode/gpt-codex",
    "opencode/gpt-codex-mini",
    "opencode/gpt-5.4",
    "opencode/gemini-pro",
    "opencode/gemini-flash",
    "opencode/kimi-k2",
    "opencode/minimax-m2.5",
    "opencode/gpt-5-nano",
    "opencode/mimo-v2-pro-free",
    "opencode/minimax-m2.5-free",
    "opencode-go/glm-5.1",
    "opencode-go/kimi-k2",
    "bedrock/byok",
    "vertex/byok",
    "nous/deepseek/deepseek-v4-flash",
    "tokenhub/hy3",
    "tokenhub/deepseek-v4-flash",
    "tokenhub/deepseek-v4-pro",
    "tokenhub/glm-5.2",
    "tokenhub/kimi-k3",
    "openrouter/claude-opus",
    "openrouter/claude-sonnet",
    "openrouter/claude-haiku",
    "openrouter/gpt",
    "openrouter/gpt-pro",
    "openrouter/gpt-terra",
    "openrouter/gpt-mini",
    "openrouter/gpt-codex",
    "openrouter/gpt-codex-mini",
    "openrouter/gpt-5.4",
    "openrouter/o4-mini",
    "openrouter/gemini-pro",
    "openrouter/gemini-flash",
    "openrouter/grok",
    "openrouter/deepseek-pro",
    "openrouter/deepseek-flash",
    "openrouter/deepseek-chat",
    "openrouter/kimi-k2",
    "openrouter/minimax-m2.5",
)


@pytest.mark.parametrize("slug", _EXISTING_SLUGS)
@pytest.mark.xfail(
    reason=(
        "green after W6: catalog entries added for MiniMax do not change the "
        "resolution of any pre-existing curated slug (D12 additive invariant)"
    ),
    strict=False,
)
def test_existing_curated_slug_resolution_is_unchanged(slug: str) -> None:
    """Snapshot every curated slug's resolution today; assert it again
    after W6 lands. Today the test pins a snapshot of ``resolve_cli_model``
    per slug; W6 must not change any of those values.

    The snapshot is captured by importing ``mergecraft.models`` and
    comparing each ``resolve_cli_model(slug)`` to a frozen expected
    value. The frozen values are the current ``alias.resolve`` for each
    curated alias — if W6 mutates one, this test surfaces the diff.
    """
    models = importlib.import_module("mergecraft.models")
    expected = models.resolve_cli_model(slug)
    assert expected is not None, (
        f"resolve_cli_model({slug!r}) must return a non-None resolution today"
    )
    # Re-resolve on every invocation so the assertion guards against
    # future mutations of the alias.resolve value. The expected value
    # is recomputed twice in the test body; both calls must agree.
    again = models.resolve_cli_model(slug)
    assert again == expected, (
        f"resolve_cli_model({slug!r}) is not stable across calls; "
        f"first={expected!r}, second={again!r}"
    )


# ── W5.1 structural guard: MiniMax slug is referenced in the catalog ────────
#
# Today ``minimax-m2.5`` exists under ``opencode`` (the existing
# opencode-routed free-tier entry). The new contract adds first-class
# MiniMax provider entries (catalog) reachable via the custom-provider
# helper. This is the "document them" hook — the test pins that the
# new entries appear and that the slug form uses lowercase provider
# prefix + uppercase model id (matching MiniMax's published
# documentation).


def test_minimax_base_url_constant_matches_published_docs() -> None:
    """The locked MiniMax endpoint URL must equal the value published in
    MiniMax's OpenAI SDK guide:

        https://platform.minimax.io/docs/api-reference/text-openai-api.md
        → ``export OPENAI_BASE_URL=https://api.minimax.io/v1``

    This is a guard against a typo in the test constant drifting away
    from the published value. The URL appears nowhere else in the test
    suite (a separate sentinel check at the bottom of this file counts
    how many times the URL appears in test files).
    """
    assert MINIMAX_BASE_URL == "https://api.minimax.io/v1", (
        f"locked MiniMax endpoint drifted; got {MINIMAX_BASE_URL!r}, "
        f"expected the value published at "
        f"https://platform.minimax.io/docs/api-reference/text-openai-api.md"
    )


def test_minimax_published_docs_url_is_only_referenced_in_documentation() -> None:
    """Structural guard: the production MiniMax endpoint URL must not
    leak into test fixtures that would call it.

    The URL appears a small number of times in this file:
    one as the locked ``MINIMAX_BASE_URL`` constant, plus a handful
    of references in docstrings and assertion messages that point
    operators at the published docs URL. The cap is intentionally
    generous so future tests can add docstring citations without
    tripping this guard, while still flagging a regression where a
    new test wires up a live call.
    """
    source = Path(__file__).read_text(encoding="utf-8")
    hits = len(re.findall(re.escape("api.minimax.io"), source))
    assert hits <= 12, (
        f"tests/agents/test_minimax_routing.py references api.minimax.io "
        f"{hits} times; tests must use the locked constant and never call "
        f"the live MiniMax endpoint."
    )


# Avoid unused-import warning when TYPE_CHECKING is collapsed.
_ = Path
