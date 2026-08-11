"""Resolve model slug + agent implementation for a run."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.agents import agents, resolve_agent
from mergecraft.agents.shared import AgentResult
from mergecraft.models import (
    _MAX_FALLBACK_DEPTH,
    BEDROCK_MODEL_ID_ENV,
    MODEL_ALIASES,
    VERTEX_MODEL_ID_ENV,
    ModelAlias,
    get_model_provider,
    is_bedrock_anthropic_id,
    is_vertex_anthropic_id,
    resolve_cli_model,
    resolve_display_alias,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from mergecraft.agents.shared import Agent
    from mergecraft.config.settings import RepoSettings


def _has_env(name: str) -> bool:
    val = os.environ.get(name)
    return isinstance(val, str) and bool(val.strip())


def _has_claude_code_auth() -> bool:
    return _has_env("CLAUDE_CODE_OAUTH_TOKEN") or _has_env("ANTHROPIC_API_KEY")


def _has_bedrock_auth() -> bool:
    return _has_env("AWS_BEARER_TOKEN_BEDROCK") or (
        _has_env("AWS_ACCESS_KEY_ID") and _has_env("AWS_SECRET_ACCESS_KEY")
    )


def _has_vertex_auth() -> bool:
    return _has_env("GOOGLE_APPLICATION_CREDENTIALS") or _has_env("VERTEX_SERVICE_ACCOUNT_JSON")


def _has_codex_subscription_auth() -> bool:
    raw = os.environ.get("CODEX_AUTH_JSON", "").strip()
    if not raw:
        return False
    from mergecraft.agents.codex import _codex_subscription_auth_usable

    return _codex_subscription_auth_usable(raw)


def _has_openai_api_key_auth() -> bool:
    return _has_env("OPENAI_API_KEY")


def _has_gemini_auth() -> bool:
    return _has_env("GEMINI_API_KEY") or _has_env("GOOGLE_GENERATIVE_AI_API_KEY")


def _has_cursor_auth() -> bool:
    return _has_env("CURSOR_API_KEY")


def _has_gateway_auth(provider: str) -> bool:
    """Return whether the gateway credential for ``provider`` is configured.

    Covers Nous Portal (``NOUS_API_KEY``) and Tencent TokenHub
    (``TOKENHUB_API_KEY``) through the opencode harness. The
    ``MERGECRAFT_CUSTOM_PROVIDER_API_KEY`` env var acts as a back-compat alias
    for any named preset (D4): consumers that wired the opencode harness
    contract directly without ``mergecraft auth nous`` keep working.
    """
    from mergecraft.agents.openai_compatible_gateways import has_gateway_credentials

    return has_gateway_credentials(provider)


def has_credentials_for_slug(slug: str) -> bool:
    """Return whether the current environment has credentials for ``slug``."""
    try:
        provider = get_model_provider(slug)
    except ValueError:
        return False

    if provider == "anthropic":
        return _has_claude_code_auth()
    if provider == "openai":
        return _has_codex_subscription_auth() or _has_openai_api_key_auth()
    if provider == "google":
        return _has_gemini_auth()
    if provider == "cursor":
        return _has_cursor_auth()
    if provider == "bedrock":
        return _has_bedrock_auth() and bool(os.environ.get(BEDROCK_MODEL_ID_ENV, "").strip())
    if provider == "vertex":
        return _has_vertex_auth() and bool(os.environ.get(VERTEX_MODEL_ID_ENV, "").strip())
    if provider in {"nous", "tokenhub"}:
        return _has_gateway_auth(provider)
    if provider == "minimax":
        # W6 (#34): MiniMax is reachable through the existing custom-provider
        # helper (operator-locked D10 / option ii). The single pair that
        # surfaces a credential is the D7 singleton; the indexed
        # ``_N`` form is also accepted because the helper's multi-provider
        # resolver may surface the provider via ``provider_<N>``.
        return _has_gateway_auth(provider)
    return False


def _ctx_tmpdir_fallback() -> str:
    return os.environ.get("MERGECRAFT_TEMP_DIR") or "/tmp"


def _local_agent_binary(name: str) -> Path:
    return Path(_ctx_tmpdir_fallback()) / "node_modules" / ".bin" / name


def _agent_binary_available(slug: str) -> bool:
    try:
        provider = get_model_provider(slug)
    except ValueError:
        return False

    binary_by_provider = {
        "anthropic": "claude",
        "openai": "codex",
        "google": "gemini",
        "cursor": "cursor",
        # D5: the opencode harness consumes env vars directly for the Nous path,
        # so there is no required CLI on PATH. Explicit ``None`` short-circuits
        # the gate to ``True`` and pins the W1.7 regression pin.
        "nous": None,
        # W6 (#34): MiniMax rides the same env-var-driven opencode harness
        # path; no CLI binary is required on PATH.
        "minimax": None,
    }
    binary = binary_by_provider.get(provider)
    if binary is None:
        return True
    if shutil.which(binary):
        return True
    return _local_agent_binary(binary).exists()


def is_runnable_model_slug(slug: str) -> bool:
    """Return whether ``slug`` has credentials and an agent CLI available."""
    if not has_credentials_for_slug(slug):
        return False
    return _agent_binary_available(slug)


def _configured_model_slugs(settings: RepoSettings) -> list[str]:
    if settings.models:
        return list(settings.models)
    if settings.model:
        return [settings.model]
    return []


def effective_model_slugs(settings: RepoSettings) -> list[str]:
    """Config order with ``MERGECRAFT_MODEL`` promoted to the front when set."""
    base = _configured_model_slugs(settings)
    env_model = os.environ.get("MERGECRAFT_MODEL", "").strip()
    if not env_model:
        return base
    rest = [slug for slug in base if slug != env_model]
    return [env_model, *rest]


def _alias_for_slug(slug: str) -> ModelAlias | None:
    return next(
        (alias for alias in MODEL_ALIASES if alias.slug == slug or alias.resolve == slug), None
    )


def _catalog_fallback_tail(slug: str) -> list[str]:
    tail: list[str] = []
    current = slug
    visited: set[str] = set()
    for _ in range(_MAX_FALLBACK_DEPTH):
        alias = _alias_for_slug(current)
        if alias is None or not alias.fallback:
            break
        nxt = alias.fallback
        if nxt in visited:
            break
        visited.add(nxt)
        tail.append(nxt)
        current = nxt
    return tail


def _expand_slug_with_fallbacks(slug: str, settings: RepoSettings) -> list[str]:
    entries = [slug]
    configured = (settings.model_fallbacks or {}).get(slug, [])
    for fallback in configured:
        if fallback not in entries:
            entries.append(fallback)
    for fallback in _catalog_fallback_tail(slug):
        if fallback not in entries:
            entries.append(fallback)
    return entries


def effective_model_chain(
    settings: RepoSettings,
    *,
    head: str | None = None,
    pin: bool = False,
) -> list[str]:
    """Ordered chain: config ``models``/``modelFallbacks``, env override, catalog ``fallback:``.

    #37 / W4 — the ``head`` argument is the chain head: when supplied, the
    effective chain starts with ``head`` and the configured tail follows.
    This is what powers the new ``with: model:`` semantics — the action
    input becomes the head, the configured ``models:`` / ``modelFallbacks:``
    stays in place.

    When ``pin`` is ``True`` the chain collapses to ``[head]`` (or the
    configured single entry when ``head`` is empty) and the fallback tail
    is dropped. The pin escape hatch keeps working for operators who
    explicitly want "use exactly this model" (#37 / D8).

    ``head`` is deduped against the configured tail so a slug that appears
    in both surfaces is not listed twice.
    """
    configured = _configured_model_slugs(settings)
    explicit_chain = len(configured) > 1 or bool(settings.model_fallbacks)

    chain: list[str] = []
    for slug in configured:
        if explicit_chain:
            entries = [slug]
            for fallback in (settings.model_fallbacks or {}).get(slug, []):
                if fallback not in entries:
                    entries.append(fallback)
        else:
            entries = _expand_slug_with_fallbacks(slug, settings)
        for entry in entries:
            if entry not in chain:
                chain.append(entry)

    env_model = os.environ.get("MERGECRAFT_MODEL", "").strip()
    if env_model:
        if explicit_chain:
            expanded = [env_model]
            for fallback in (settings.model_fallbacks or {}).get(env_model, []):
                if fallback not in expanded:
                    expanded.append(fallback)
        else:
            expanded = _expand_slug_with_fallbacks(env_model, settings)
        chain = expanded + [entry for entry in chain if entry not in expanded]

    if pin:
        # Pin: collapse to exactly the head, or — when no head is
        # supplied — to the first configured entry. The configured tail
        # is dropped; this is the explicit opt-out from chain behaviour.
        if head:
            return [head]
        return chain[:1] if chain else []

    if head:
        # Chain-preserving: head first, then the configured tail minus the
        # head (so a slug that the operator named in both surfaces is not
        # listed twice).
        tail = [entry for entry in chain if entry != head]
        chain = [head, *tail]

    return chain[:_MAX_FALLBACK_DEPTH]


def select_runnable_model_slug(*, settings: RepoSettings) -> str:
    """Pick the first chain entry with credentials and an available agent binary."""
    chain = effective_model_chain(settings)
    if not chain:
        msg = "no model chain configured — set models: or model: in .mergecraft/config.yaml"
        raise RuntimeError(msg)

    skipped: list[str] = []
    for slug in chain:
        if not has_credentials_for_slug(slug):
            skipped.append(f"{slug} (missing credentials)")
            continue
        if not _agent_binary_available(slug):
            skipped.append(f"{slug} (agent binary missing)")
            continue
        if skipped:
            logger.warning("» model chain skipped backups: {}", ", ".join(skipped))
        logger.info("» model chain selected slug={}", slug)
        return slug

    if skipped:
        logger.warning("» model chain skipped backups: {}", ", ".join(skipped))
    msg = "no runnable model slug in chain — configure credentials for at least one entry"
    raise RuntimeError(msg)


def _is_retryable_failure(result: AgentResult) -> bool:
    metadata = result.metadata or {}
    retryable = metadata.get("retryable")
    return retryable is True


async def run_with_model_chain(
    *,
    settings: RepoSettings,
    run_once: Callable[[str], Awaitable[AgentResult]],
    max_attempts: int = _MAX_FALLBACK_DEPTH,
    correlation: dict[str, Any] | None = None,
    head: str | None = None,
    pin: bool = False,
) -> tuple[str, AgentResult]:
    """Walk the model chain, advancing on retryable failures.

    The chain visits every configured entry in order, calling ``run_once`` on each.
    ``run_once`` is responsible for surfacing credential or availability errors as
    retryable / non-retryable failures; the chain loop itself does not pre-filter
    by credentials or binary availability. This keeps the chain loop testable in
    environments that lack agent binaries or provider credentials, while preserving
    production semantics (``run_once`` fails fast when the agent cannot run).

    Args:
        settings (RepoSettings): Resolved repository settings (drives tracing + chain).
        run_once (Callable[[str], Awaitable[AgentResult]]): Per-slug agent runner.
        max_attempts (int, optional): Maximum fallback attempts before giving up.
        correlation (dict[str, Any] | None, optional): Root-span correlation attributes
            (run_id, repo, pr_number, commit_sha, workflow_run_id, job_id). When ``None``,
            the values are derived from the GitHub Actions environment.
        head (str | None, optional): #37 / W4 — chain head. When supplied (and
            ``pin`` is False) the chain starts with ``head`` and the configured
            tail follows. The GHA payload path threads the ``with: model:``
            action input through this argument.
        pin (bool, optional): #37 / W4 — collapse to ``[head]`` (or the first
            configured entry) and skip the fallback tail. The escape hatch for
            operators who explicitly want "use exactly this model".

    Returns:
        tuple[str, AgentResult]: The winning slug and its agent result.

    Examples:
        >>> raise NotImplementedError  # covered by integration tests
    """
    # Local imports avoid a circular import — tracing imports ``mergecraft.config`` for
    # ``RepoSettings`` only at type-check time.
    from mergecraft.tracing.tracer import get_tracer_from_settings, resolve_correlation_from_env

    tracer = get_tracer_from_settings(settings)
    correlation_attrs = (
        dict(correlation) if correlation is not None else resolve_correlation_from_env()
    )

    chain = effective_model_chain(settings, head=head, pin=pin)

    # Always emit the root span — the trace tree is the run's, not the
    # chain's. An empty chain short-circuits with a flagged agent result;
    # callers inspect ``success`` to surface the misconfiguration upstream.
    with tracer.start_span(
        "mergecraft.run",
        attrs_source=lambda: dict(correlation_attrs),
    ) as _root:
        if not chain:
            _empty_result = _empty_chain_result()
            _root.set_status("error", _empty_result.error or "empty model chain")
            return "", _empty_result

        chain_index = 0
        attempts = 0

        root_parent_id = _root.span_id if hasattr(_root, "span_id") else None

        cli_argv = _redacted_cli_argv()

        while attempts < max_attempts:
            slug = chain[chain_index]
            attempts += 1
            logger.info("» model chain attempt {}/{} slug={}", attempts, max_attempts, slug)

            attempt_attrs = {
                "model.id": slug,
                "model.provider": _agent_provider_for_slug(slug),
                "model.mode": _agent_mode_for_slug(slug),
                "model.fallback_index": chain_index,
                "model.attempt_number": attempts,
                "agent.provider": _agent_provider_for_slug(slug),
                "agent.mode": _agent_mode_for_slug(slug),
                # OTel GenAI semantic-convention names so Logfire's native
                # GenAI dashboard populates. ``gen_ai.system`` is the provider
                # slug (anthropic/openai/google/opencode/...).
                "gen_ai.system": _agent_provider_for_slug(slug),
                "gen_ai.agent.name": _agent_mode_for_slug(slug),
                "gen_ai.request.model": slug,
                "agent.cli_argv": cli_argv,
            }
            attempt_kind = "agent.attempt"
            terminal_status = "retryable"  # default until set inside the span body
            with tracer.start_span(
                attempt_kind,
                parent_span_id=root_parent_id,
                attrs_source=_snapshot_attrs(attempt_attrs),
            ) as attempt_span:
                result = await run_once(slug)

                call_attrs: dict[str, Any] = {
                    "model.id": slug,
                    "model.requested": slug,
                    "model.resolved": slug,
                    "model.fallback_index": chain_index,
                    "gen_ai.operation.name": "chat",
                    "gen_ai.request.model": slug,
                    "gen_ai.response.model": slug,
                }
                usage = result.usage
                if usage is not None:
                    usage_cost = _cost_attrs_from_usage(usage)
                    call_attrs.update(usage_cost)

                attempt_parent_id = (
                    attempt_span.span_id if hasattr(attempt_span, "span_id") else None
                )
                with tracer.start_span(
                    "llm.call",
                    parent_span_id=attempt_parent_id,
                    attrs_source=_snapshot_attrs(call_attrs),
                ) as _call_span:
                    pass

                if result.success:
                    attempt_span.set_status("ok")
                    terminal_status = "ok"
                    logger.info("» model chain succeeded slug={}", slug)
                elif not _is_retryable_failure(result):
                    attempt_span.set_status("error", result.error or "unknown error")
                    terminal_status = "error"
                    logger.warning(
                        "» model chain slug={} failed (non-retryable): {}",
                        slug,
                        result.error or "unknown error",
                    )
                elif chain_index < len(chain) - 1:
                    nxt = chain[chain_index + 1]
                    attempt_span.set_status("retryable", result.error or "unknown error")
                    logger.warning(
                        "» model chain slug={} failed (retryable): {} — advancing to {}",
                        slug,
                        result.error or "unknown error",
                        nxt,
                    )
                else:
                    attempt_span.set_status("retryable", result.error or "unknown error")
                    logger.warning(
                        "» model chain slug={} failed (retryable): {} — retrying ({}/{})",
                        slug,
                        result.error or "unknown error",
                        attempts,
                        max_attempts,
                    )

            # The ``agent.attempt`` span has now closed and emitted. Emit
            # "would-have-advanced" synthetic spans for any chain entries
            # that come after the winner so the trace tree reflects the
            # configured chain, not just the entries the runtime loop
            # happened to visit. W4.3 / issue §4 — visibility into why
            # an earlier entry was skipped.
            if terminal_status in {"ok", "error"}:
                for follow_on_slug in chain[chain_index + 1 :]:
                    chain_index += 1
                    _emit_advanced_attempt(
                        tracer,
                        parent_span_id=root_parent_id,
                        slug=follow_on_slug,
                        fallback_index=chain_index,
                    )
                # Propagate the terminal status to the root span so the
                # trace tree's top-level ``mergecraft.run`` span reflects
                # whether the run succeeded or failed. Without this the
                # root span stays in its default "ok" state and operators
                # inspecting the trace lose the failure signal at a
                # glance. W5.3 (failure-mode) pins this. W4's
                # instrumentation emitted the root span but did not
                # propagate the attempt-level status; this is the W6
                # reconciliation.
                if terminal_status == "ok":
                    _root.set_status("ok")
                    return slug, result
                _root.set_status("error", result.error or "unknown error")
                return slug, result

            if chain_index < len(chain) - 1:
                chain_index += 1
                continue

        msg = f"model chain exhausted after {max_attempts} attempts (cap reached)"
        raise RuntimeError(msg) from None


def _agent_provider_for_slug(slug: str) -> str:
    """Return the provider slug (``anthropic`` / ``openai`` / ...) for ``slug``."""
    try:
        return get_model_provider(slug)
    except ValueError:
        return "unknown"


def _agent_mode_for_slug(slug: str) -> str:
    """Return the agent mode name (e.g. ``claude``) that would serve ``slug``."""
    provider = _agent_provider_for_slug(slug)
    if provider == "anthropic":
        return "claude"
    if provider == "openai":
        return "codex"
    if provider == "google":
        return "gemini"
    if provider == "cursor":
        return "cursor"
    return "opencode"


def _cost_attrs_from_usage(usage: Any) -> dict[str, Any]:
    """Map an ``AgentUsage`` to ``cost.*`` span attributes (D11)."""
    attrs: dict[str, Any] = {}
    tokens_in = getattr(usage, "input_tokens", None)
    tokens_out = getattr(usage, "output_tokens", None)
    cache_read = getattr(usage, "cache_read_tokens", None)
    cache_write = getattr(usage, "cache_write_tokens", None)
    cost_usd = getattr(usage, "cost_usd", None)
    if isinstance(tokens_in, int):
        attrs["cost.tokens_in"] = tokens_in
    if isinstance(tokens_out, int):
        attrs["cost.tokens_out"] = tokens_out
    if isinstance(cache_read, int):
        attrs["cost.cache_read"] = cache_read
    if isinstance(cache_write, int):
        attrs["cost.cache_write"] = cache_write
    if isinstance(cost_usd, (int, float)):
        attrs["cost.usd"] = float(cost_usd)
    # Mirror the mergeCraft cost.* names as OpenTelemetry GenAI semantic
    # conventions so Logfire's native GenAI dashboard populates. ``cache_write``
    # maps to ``cache_creation_input_tokens`` per the GenAI spec.
    if isinstance(tokens_in, int):
        attrs["gen_ai.usage.input_tokens"] = tokens_in
    if isinstance(tokens_out, int):
        attrs["gen_ai.usage.output_tokens"] = tokens_out
    if isinstance(cache_read, int):
        attrs["gen_ai.usage.cache_read_input_tokens"] = cache_read
    if isinstance(cache_write, int):
        attrs["gen_ai.usage.cache_creation_input_tokens"] = cache_write
    if isinstance(cost_usd, (int, float)):
        attrs["gen_ai.usage.cost_usd"] = float(cost_usd)
    return attrs


def _redacted_cli_argv() -> str:
    """Return the redacted CLI argv for the ``agent.cli_argv`` span attribute.

    D7 / TRACING.md §redaction: a span must never carry a credential. The
    helper masks token/secret-shaped values (``--api-key sk-…``, bearer
    substrings) while preserving the command shape.
    """
    from mergecraft.tracing.redaction import redact_cli_argv

    return redact_cli_argv(list(sys.argv))


def _empty_chain_result() -> AgentResult:
    """Return a failed ``AgentResult`` representing an empty model chain (D11/W4.5)."""
    return AgentResult(
        success=False,
        error="no model chain configured",
        metadata={"empty_chain": True},
    )


def _snapshot_attrs(
    source: dict[str, Any],
) -> Callable[[], dict[str, Any]]:
    """Return a no-arg callable that snapshots ``source`` for ``attrs_source``.

    The tracer evaluates ``attrs_source`` when a span closes; this indirection
    lets callers mutate ``source`` between ``start_span`` and ``__exit__``
    (e.g. to record the per-attempt cost) without losing type information.
    """

    def _snap() -> dict[str, Any]:
        return dict(source)

    return _snap


def _emit_advanced_attempt(
    tracer: Any,
    *,
    parent_span_id: str | None,
    slug: str,
    fallback_index: int,
) -> None:
    """Emit a synthetic ``agent.attempt`` span for a chain entry the runtime loop skipped past.

    Once the chain picks a winner (or hits a non-retryable failure), the
    loop emits follow-on synthetic spans for the remaining chain entries
    so the trace tree reflects the configured chain, not just the
    entries the runtime visited. The synthetic span's ``status`` is
    ``"not_visited"`` so consumers can distinguish it from a real
    ``"skipped"`` (no credentials/binary) entry.
    """
    attrs = {
        "model.id": slug,
        "model.provider": _agent_provider_for_slug(slug),
        "model.mode": _agent_mode_for_slug(slug),
        "model.fallback_index": fallback_index,
        "agent.provider": _agent_provider_for_slug(slug),
        "agent.mode": _agent_mode_for_slug(slug),
        "gen_ai.system": _agent_provider_for_slug(slug),
        "gen_ai.agent.name": _agent_mode_for_slug(slug),
        "gen_ai.request.model": slug,
        "agent.cli_argv": _redacted_cli_argv(),
    }
    with tracer.start_span(
        "agent.attempt",
        parent_span_id=parent_span_id,
        attrs_source=_snapshot_attrs(attrs),
    ) as span:
        span.set_status("not_visited", "chain decided on an earlier entry")


def _slug_runnable(slug: str) -> bool:
    """Return whether ``slug`` should enter the runnable chain.

    Combines the credential and binary gates (``select_runnable_model_slug``
    callers see the same answer) and accepts unknown provider prefixes —
    those are custom slugs the operator takes responsibility for; the
    chain still requires the agent binary to be available.
    """
    if has_credentials_for_slug(slug):
        return True
    try:
        provider = get_model_provider(slug)
    except ValueError:
        return False
    # Unknown provider prefix — pass through; the binary gate is the
    # real constraint and ``_agent_binary_available`` already covers it.
    return provider not in {"anthropic", "openai", "google", "cursor", "bedrock", "vertex"}


def _fail_loud_for_openai(*, model: str) -> None:
    hints = ("CODEX_AUTH_JSON", "OPENAI_API_KEY")
    env_list = ", ".join(hints)
    msg = (
        f"OpenAI model {model!r} selected but no credential is configured. "
        f"Set {env_list} (subscription via `mergecraft auth codex`, or an API key secret) "
        "or choose a different model."
    )
    raise ValueError(msg)


def _fail_loud_for_google(*, model: str) -> None:
    hints = ("GEMINI_API_KEY", "GOOGLE_GENERATIVE_AI_API_KEY")
    env_list = ", ".join(hints)
    msg = (
        f"Google model {model!r} selected but no credential is configured. "
        f"Set {env_list} (via `mergecraft auth gemini` or a GitHub Actions secret) "
        "or choose a different model."
    )
    raise ValueError(msg)


def _fail_loud_for_cursor(*, model: str) -> None:
    hints = ("CURSOR_API_KEY",)
    env_list = ", ".join(hints)
    msg = (
        f"Cursor model {model!r} selected but no credential is configured. "
        f"Set {env_list} (via `mergecraft auth cursor` or a GitHub Actions secret) "
        "or choose a different model."
    )
    raise ValueError(msg)


def _resolve_slug(slug: str) -> str | None:
    alias = resolve_display_alias(slug)
    if alias and alias.routing == "bedrock":
        bedrock_id = os.environ.get(BEDROCK_MODEL_ID_ENV, "").strip()
        if not bedrock_id:
            msg = f"{BEDROCK_MODEL_ID_ENV} env var is required when the model is set to {slug!r}."
            raise ValueError(msg)
        return bedrock_id
    if alias and alias.routing == "vertex":
        vertex_id = os.environ.get(VERTEX_MODEL_ID_ENV, "").strip()
        if not vertex_id:
            msg = f"{VERTEX_MODEL_ID_ENV} env var is required when the model is set to {slug!r}."
            raise ValueError(msg)
        return vertex_id
    return resolve_cli_model(slug)


def resolve_model(*, slug: str | None = None, respect_env_override: bool = True) -> str | None:
    """Resolve the effective model string for this run."""
    if respect_env_override:
        env_model = os.environ.get("MERGECRAFT_MODEL", "").strip()
        if env_model:
            return _resolve_slug(env_model) or env_model

    cleaned = (slug or "").strip()
    if cleaned:
        resolved = _resolve_slug(cleaned)
        if resolved:
            return resolved
        if "/" in cleaned:
            logger.info(
                '» "{}" is not a curated alias — passing through as a raw model specifier',
                cleaned,
            )
            return cleaned
        logger.warning('» unknown model slug "{}" — agent will auto-select', cleaned)
    return None


def resolve_runtime_agent(*, model: str | None = None) -> Agent:
    """Pick claude vs opencode based on model + available credentials."""
    env_agent = os.environ.get("MERGECRAFT_AGENT", "").strip()
    if env_agent:
        if env_agent in agents:
            return resolve_agent(env_agent)
        logger.warning(
            '» unknown MERGECRAFT_AGENT="{}" — falling through to auto-select', env_agent
        )

    if model and _has_bedrock_auth() and os.environ.get(BEDROCK_MODEL_ID_ENV, "").strip() == model:
        return agents["claude"] if is_bedrock_anthropic_id(model) else agents["opencode"]

    if model and _has_vertex_auth() and os.environ.get(VERTEX_MODEL_ID_ENV, "").strip() == model:
        return agents["claude"] if is_vertex_anthropic_id(model) else agents["opencode"]

    if model:
        try:
            provider = get_model_provider(model)
        except ValueError:
            provider = None

        if provider == "openai":
            if _has_codex_subscription_auth() or _has_openai_api_key_auth():
                return agents["codex"]
            _fail_loud_for_openai(model=model)

        if provider == "google":
            if _has_gemini_auth():
                return agents["gemini"]
            _fail_loud_for_google(model=model)

        if provider == "cursor":
            if _has_cursor_auth():
                return agents["cursor"]
            _fail_loud_for_cursor(model=model)

        if provider == "anthropic" and _has_claude_code_auth():
            return agents["claude"]

        if provider in {"nous", "tokenhub"}:
            if _has_gateway_auth(provider):
                return agents["opencode"]
            hints = (
                ("NOUS_API_KEY", "mergecraft auth nous")
                if provider == "nous"
                else ("TOKENHUB_API_KEY", "mergecraft auth tokenhub")
            )
            msg = (
                f"{provider} model {model!r} selected but no credential is configured. "
                f"Set {hints[0]} (via `{hints[1]}` or a GitHub Actions secret), "
                "or set MERGECRAFT_CUSTOM_PROVIDER_BASE_URL + "
                "MERGECRAFT_CUSTOM_PROVIDER_API_KEY, or choose a different model."
            )
            raise ValueError(msg)

        if provider == "minimax":
            # W6 (#34): MiniMax rides the custom-provider helper. Fail loud
            # (convention 5) rather than silently falling through to the
            # opencode harness when the env vars are missing — the harness
            # will not be able to reach MiniMax without them, and the
            # operator's CLI auth gate would mask the configuration error.
            if _has_gateway_auth(provider):
                return agents["opencode"]
            msg = (
                f"MiniMax model {model!r} selected but no credential is configured. "
                "Set MERGECRAFT_CUSTOM_PROVIDER_BASE_URL + "
                "MERGECRAFT_CUSTOM_PROVIDER_API_KEY "
                "(via `mergecraft auth minimax` or GitHub Actions secrets), "
                "or an indexed pair "
                "MERGECRAFT_CUSTOM_PROVIDER_{API_KEY,BASE_URL}_1, "
                "or choose a different model."
            )
            raise ValueError(msg)

    return agents["opencode"]


__all__ = [
    "effective_model_chain",
    "effective_model_slugs",
    "has_credentials_for_slug",
    "is_runnable_model_slug",
    "resolve_model",
    "resolve_runtime_agent",
    "run_with_model_chain",
    "select_runnable_model_slug",
]
