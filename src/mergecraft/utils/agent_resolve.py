"""Resolve model slug + agent implementation for a run."""

from __future__ import annotations

import os
import shutil
import sys
import time
from enum import StrEnum
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
from mergecraft.tracing.genai import (
    request_attrs,
    response_attrs,
    usage_attrs_from_agent_usage,
    usage_unavailable_attrs,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from mergecraft.agents.shared import Agent
    from mergecraft.config.settings import RepoSettings
    from mergecraft.mcp.tool_state import ToolState


class ModelFallbackPolicyError(RuntimeError):
    """Raised when ``allow_fallback=false`` blocks advancing the model chain (W10.1).

    Mapped to ``RunOutcome.configuration_error`` by ``main._classify_error_outcome``.
    Message always names configuration/fallback so operators and RED tests can
    match the policy without inspecting the exception type alone.
    """


class FallbackReason(StrEnum):
    """Why a model-chain entry was skipped (HA2 / D13).

    Distinct from verdict content — a valid ``request_changes`` is a usable
    result and never appears here. Stamped on the **winner** as the reason the
    previous attempt was skipped (last skip wins when multiple advances).
    """

    provider_error = "provider_error"
    timeout = "timeout"
    crash = "crash"
    no_terminal_verdict = "no_terminal_verdict"
    malformed_submission = "malformed_submission"
    semantic_rejection = "semantic_rejection"
    stale_attempt = "stale_attempt"


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


def has_credentials_for_slug(slug: str) -> bool:
    """Return whether the current environment has credentials for ``slug``."""
    try:
        provider = get_model_provider(slug)
    except ValueError:
        return False

    from mergecraft.config.runtime_provider_registry import (
        _legacy_nous_api_key_present,
        indexed_credential_for_entry,
        lookup_registry_entry,
        warn_legacy_nous_api_key_once,
    )
    from mergecraft.config.settings import load_repo_settings

    settings = load_repo_settings(root=Path.cwd(), load_learnings_files=False)
    entry = lookup_registry_entry(settings, provider)
    if entry is not None and indexed_credential_for_entry(entry):
        return True

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

    if provider == "nous" and _legacy_nous_api_key_present():
        warn_legacy_nous_api_key_once()
        return True
    from mergecraft.agents.openai_compatible_gateways import _legacy_gateway_preset_credentials

    return _legacy_gateway_preset_credentials(provider)


def _ctx_tmpdir_fallback() -> str:
    return os.environ.get("MERGECRAFT_TEMP_DIR") or "/tmp"


def _local_agent_binary(name: str) -> Path:
    return Path(_ctx_tmpdir_fallback()) / "node_modules" / ".bin" / name


def _agent_binary_available(slug: str) -> bool:
    try:
        provider = get_model_provider(slug)
    except ValueError:
        return False

    from mergecraft.config.runtime_provider_registry import lookup_registry_entry
    from mergecraft.config.settings import load_repo_settings

    settings = load_repo_settings(root=Path.cwd(), load_learnings_files=False)
    entry = lookup_registry_entry(settings, provider)
    if entry is not None and entry.harness == "opencode":
        return True

    binary_by_provider = {
        "anthropic": "claude",
        "openai": "codex",
        "google": "gemini",
        "cursor": "cursor",
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


def configured_model_slugs(settings: RepoSettings) -> list[str]:
    """Return the slugs configured in ``.mergecraft/config.yaml``, env excluded.

    The YAML precedence layer on its own — :func:`effective_model_slugs`
    promotes ``MERGECRAFT_MODEL`` to the front, which conflates the env layer
    with the YAML one for callers that report layers separately.
    """
    return _configured_model_slugs(settings)


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


def resolve_effective_model_slug(settings: RepoSettings) -> str | None:
    """Return the model slug that would actually run right now, or ``None``.

    The shared "what would win" resolution — originally ``mergecraft
    models show``'s private ``_winning_slug`` helper, promoted here so
    other CLI commands (e.g. ``mergecraft eval bench``) can resolve
    ``.mergecraft/config.yaml`` the same way rather than only checking
    ``MERGECRAFT_MODEL`` (``resolve_model(slug=None)`` alone never reads
    config — it only checks an explicit slug and the env override;
    mergeCraft self-review, PR #216, caught `mergecraft eval bench`
    advertising config-only resolution while never actually consulting it).

    Precedence: ``MERGECRAFT_MODEL`` env override, else the first
    configured slug with detected credentials, else the first configured
    slug regardless, else ``settings.model`` resolved through the alias
    catalog.
    """
    env_model = os.environ.get("MERGECRAFT_MODEL", "").strip()
    if env_model:
        return env_model

    configured = _configured_model_slugs(settings)
    for slug in configured:
        if has_credentials_for_slug(slug):
            return slug

    if configured:
        return configured[0]

    return resolve_model(slug=settings.model)


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
            return _filter_chain_for_residency([head])
        return _filter_chain_for_residency(chain[:1] if chain else [])

    if head:
        # Chain-preserving: head first, then the configured tail minus the
        # head (so a slug that the operator named in both surfaces is not
        # listed twice).
        tail = [entry for entry in chain if entry != head]
        chain = [head, *tail]

    return _filter_chain_for_residency(chain[:_MAX_FALLBACK_DEPTH])


def _filter_chain_for_residency(chain: list[str]) -> list[str]:
    """Drop chain entries outside the bound residency allow-list.

    Raises:
        PermissionError: Every remaining slug is outside the allow-list.
    """
    from mergecraft.enterprise.runtime import (
        current_enterprise_settings,
        enforce_routed_model_residency,
    )

    if not chain or not current_enterprise_settings().allowed_regions:
        return chain
    allowed: list[str] = []
    for slug in chain:
        try:
            enforce_routed_model_residency(slug)
        except PermissionError:
            continue
        allowed.append(slug)
    if not allowed:
        msg = "no model in the chain is permitted by enterprise.allowedRegions"
        raise PermissionError(msg)
    return allowed


def pick_runnable_slug_from_chain(
    chain: list[str],
    *,
    allow_fallback: bool = True,
) -> str:
    """Pick the first runnable entry from an already-computed model chain.

    Shared by :func:`select_runnable_model_slug` and ``main()`` so W10
    ``allow_fallback`` policy cannot drift across call sites.
    """
    if not chain:
        msg = "no model chain configured — set models: or model: in .mergecraft/config.yaml"
        raise RuntimeError(msg)

    if not allow_fallback:
        slug = chain[0]
        if not has_credentials_for_slug(slug):
            msg = (
                f"configuration error: allow_fallback is false and primary model "
                f"{slug!r} is unavailable (missing credentials)"
            )
            raise ModelFallbackPolicyError(msg)
        if not _agent_binary_available(slug):
            msg = (
                f"configuration error: allow_fallback is false and primary model "
                f"{slug!r} is unavailable (agent binary missing)"
            )
            raise ModelFallbackPolicyError(msg)
        logger.info("» model chain selected slug={} (allow_fallback=false)", slug)
        return slug

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


def select_runnable_model_slug(*, settings: RepoSettings) -> str:
    """Pick the first chain entry with credentials and an available agent binary."""
    return pick_runnable_slug_from_chain(
        effective_model_chain(settings),
        allow_fallback=settings.allow_fallback,
    )


# OpenCode attempts are the expensive ones: each retryable failure on that
# harness can cost a full external-operation timeout before it returns. Allow
# the initial attempt plus exactly one retry, then stop spending the run's
# wall clock on it and let the chain move on (#444).
_OPENCODE_MAX_ATTEMPTS: int = 2

# In-place retries at the chain tail, where there is no next entry to fail over
# to. Re-issuing against the model that just refused has little value and no
# backoff, so one retry is the whole allowance; past that the failure is the
# run's answer. Widening what counts as retryable (#447) made this branch far
# easier to reach, and unbounded it would spend the attempt cap re-asking a
# provider that already said no.
_MAX_TAIL_RETRIES: int = 1


def _chain_deadline() -> float | None:
    """Monotonic wall-clock ceiling for the whole chain, or ``None`` when unset.

    Retryable failures are what make the chain useful, but a retryable
    *timeout* costs a full external-operation budget each time it recurs, so an
    attempt-count cap alone is not a bound: ten 1500s timeouts is a four-hour
    run. This ceiling reuses the existing per-run ``run_timeout_s`` budget
    rather than introducing a second notion of "too long" (#444).
    """
    from mergecraft.utils.run_bounds import resolve_run_bounds

    try:
        run_timeout_s = resolve_run_bounds().run_timeout_s
    except Exception as exc:  # pragma: no cover - defensive: never block a run
        logger.debug("chain deadline unavailable, continuing unbounded: {}", exc)
        return None
    if run_timeout_s <= 0:
        return None
    return time.monotonic() + run_timeout_s


def _inferred_retryable(result: AgentResult) -> bool:
    """Best-effort retryability from the failure itself, ignoring metadata."""
    from mergecraft.utils.provider_failure import is_retryable_cli_failure

    metadata = result.metadata or {}
    if metadata.get("timeout") is True or metadata.get("crash") is True:
        return True
    error = result.error or ""
    lowered = error.lower()
    if "timeout" in lowered or "timed out" in lowered or "crash" in lowered:
        return True
    return is_retryable_cli_failure(returncode=None, stderr=error)


def _is_retryable_failure(result: AgentResult) -> bool:
    """Decide whether a failed attempt may advance the chain (#447).

    Precedence, and the only decision path — ``_retryable_failure_reason``
    labels a skip that this function has already decided:

    1. An explicit ``metadata["retryable"]`` (``True`` or ``False``) wins. A
       driver that states its intent is always believed.
    2. Unset means *infer* from the failure.

    Unset used to mean "permanent", which made a driver's omission silently
    fatal rather than merely imprecise: #444 was exactly that shape — an
    opencode timeout whose error text said "timed out", which
    ``_retryable_failure_reason`` duly labelled ``FallbackReason.timeout``,
    terminating the run at attempt 1 because the deciding classifier read only
    the absent flag. Inference keeps a forgotten flag from costing a review.
    """
    metadata = result.metadata or {}
    declared = metadata.get("retryable")
    if isinstance(declared, bool):
        return declared
    return _inferred_retryable(result)


def _retryable_failure_reason(result: AgentResult) -> FallbackReason:
    """Label a failure for tracing. Never decides — see ``_is_retryable_failure``."""
    error = (result.error or "").lower()
    metadata = result.metadata or {}
    if "timeout" in error or "timed out" in error or metadata.get("timeout") is True:
        return FallbackReason.timeout
    if "crash" in error or metadata.get("crash") is True:
        return FallbackReason.crash
    return FallbackReason.provider_error


def _classify_skip_reason(result: AgentResult, chain_index: int) -> FallbackReason | None:
    """Return why ``result`` cannot be the chain winner, or ``None`` when usable."""
    diagnostics = result.diagnostics or {}
    attempt_id = diagnostics.get("attempt_id")
    if attempt_id is not None and attempt_id != chain_index:
        return FallbackReason.stale_attempt

    if result.success and result.terminal_submission_received:
        return None

    if not result.success:
        return _retryable_failure_reason(result)

    if diagnostics.get("malformed_submission"):
        return FallbackReason.malformed_submission
    return FallbackReason.no_terminal_verdict


def _is_incomplete_review_success(
    result: AgentResult,
    tool_state: ToolState | None,
) -> bool:
    """True when a successful provider result is not a usable review winner.

    Scripted chain tests that omit ``tool_state`` keep success=True winner
    semantics. The live orchestrator always passes ``tool_state``.
    """
    if tool_state is None or not result.success or result.terminal_submission_received:
        return False
    from mergecraft.main_outcome import _is_incremental_review, _is_review_mode

    mode = tool_state.selected_mode
    if mode is not None and not _is_review_mode(mode):
        return False
    if _is_incremental_review(mode) and tool_state.final_summary_written:
        return False
    submission = tool_state.terminal_submission
    if submission is not None and not tool_state.terminal_submission_conflict:
        return bool((result.diagnostics or {}).get("rejection_reason"))
    return True


def _attach_model_evidence(
    result: AgentResult,
    *,
    requested_model: str,
    executed_model: str,
    fallback_index: int,
    fallback_reason: FallbackReason | None = None,
) -> AgentResult:
    """Stamp requested/executed/fallback fields onto ``result.metadata`` (W10.2/W10.3).

    Operators read these via the evidence packet and Action ``result`` surfaces;
    the stamp is unconditional so fallback is never silent.
    """
    meta = dict(result.metadata or {})
    meta.update(
        {
            "requested_model": requested_model,
            "executed_model": executed_model,
            "provider": _agent_provider_for_slug(executed_model),
            "fallback_index": fallback_index,
            "fallback_occurred": fallback_index > 0,
        }
    )
    if fallback_reason is not None:
        meta["fallback_reason"] = fallback_reason
    result.metadata = meta
    return result


def stamp_attempt_id(
    tool_state: ToolState,
    *,
    attempt_id: int,
    fallback_index: int,
) -> None:
    """Stamp the active model-chain attempt on ``tool_state`` (V7 / VP3).

    Called when a model-chain attempt starts so ``submit_review_verdict`` can
    copy the same id onto ``TerminalSubmission`` instead of inferring one at
    submit time.
    """
    tool_state.attempt_id = attempt_id
    tool_state.fallback_index = fallback_index


def promote_model_evidence(
    tool_state: ToolState,
    *,
    requested_model: str | None,
    executed_model: str | None,
    fallback_index: int,
) -> None:
    """Write W10 model-evidence fields onto ``tool_state`` (single promotion path).

    Used for both the chain path (after :func:`_attach_model_evidence`) and the
    single-slug path so ``main`` never re-infers ``fallback_index`` from a
    requested≠executed heuristic.
    """
    if requested_model:
        tool_state.requested_model = requested_model
    if executed_model:
        tool_state.model = executed_model
    tool_state.fallback_index = fallback_index
    tool_state.fallback_occurred = fallback_index > 0
    if tool_state.fallback_occurred:
        logger.warning(
            "model fallback in review metadata: requested={} executed={} fallback_index={}",
            tool_state.requested_model,
            executed_model,
            tool_state.fallback_index,
        )


def _prepare_chain_attempt(tool_state: ToolState | None, fallback_index: int) -> None:
    """Stamp the active chain index and drop any prior attempt's terminal submit."""
    if tool_state is None:
        return
    stamp_attempt_id(tool_state, attempt_id=fallback_index, fallback_index=fallback_index)
    tool_state.terminal_submission = None
    tool_state.terminal_submission_conflict = False


async def run_with_model_chain(
    *,
    settings: RepoSettings,
    run_once: Callable[[str], Awaitable[AgentResult]],
    max_attempts: int = _MAX_FALLBACK_DEPTH,
    correlation: dict[str, Any] | None = None,
    head: str | None = None,
    pin: bool = False,
    tool_state: ToolState | None = None,
) -> tuple[str, AgentResult]:
    """Walk the model chain, advancing on retryable failures.

    The chain visits every configured entry in order, calling ``run_once`` on each.
    ``run_once`` is responsible for surfacing credential or availability errors as
    retryable / non-retryable failures; the chain loop itself does not pre-filter
    by credentials or binary availability. This keeps the chain loop testable in
    environments that lack agent binaries or provider credentials, while preserving
    production semantics (``run_once`` fails fast when the agent cannot run).

    When ``settings.allow_fallback`` is ``False`` (W10.1), a retryable failure of
    the primary (or current) entry raises :class:`ModelFallbackPolicyError`
    instead of advancing — operators who pin the reviewer model get a
    ``configuration_error`` rather than a silent review under a different slug.

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
        tool_state (ToolState | None, optional): Shared MCP state for this run.
            When supplied, ``fallback_index`` is updated *before* ``run_once``
            and any terminal submission from a prior chain entry is cleared so
            a fallback cannot inherit or conflict-reject the failed attempt.

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
    requested_model = chain[0] if chain else (head or "")

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
        last_skip_reason: FallbackReason | None = None
        deadline = _chain_deadline()
        opencode_attempts = 0
        tail_retries = 0
        last_result: AgentResult | None = None
        # The slug that actually produced ``last_result``. The loop variable
        # ``slug`` can point at an entry being *skipped*, so evidence must be
        # stamped from this instead.
        last_executed_slug: str | None = None

        root_parent_id = _root.span_id if hasattr(_root, "span_id") else None

        cli_argv = _redacted_cli_argv()

        while attempts < max_attempts:
            slug = chain[chain_index]
            if _agent_mode_for_slug(slug, settings=settings) == "opencode":
                if opencode_attempts >= _OPENCODE_MAX_ATTEMPTS:
                    logger.warning(
                        "» model chain skipping slug={} (fallback_index={}): opencode "
                        "retry allowance of {} attempts already spent",
                        slug,
                        chain_index,
                        _OPENCODE_MAX_ATTEMPTS,
                    )
                    if chain_index < len(chain) - 1:
                        chain_index += 1
                        continue
                    # Last entry and the allowance is gone: surface the failure
                    # the spent attempts already produced rather than raising a
                    # cap error that hides it. The allowance cannot be spent
                    # before an attempt has run, so ``last_result`` is set.
                    if last_result is None or last_executed_slug is None:
                        break  # pragma: no cover - allowance implies an attempt
                    # ``slug`` here is the entry being skipped — it never ran.
                    # Stamp the slug that actually produced ``last_result`` so
                    # the evidence packet names the model that really failed.
                    spent = _attach_model_evidence(
                        last_result,
                        requested_model=requested_model or last_executed_slug,
                        executed_model=last_executed_slug,
                        fallback_index=chain_index,
                        fallback_reason=last_skip_reason,
                    )
                    _root.set_status("error", last_result.error or "opencode retries exhausted")
                    return last_executed_slug, spent
                opencode_attempts += 1
            attempts += 1
            _prepare_chain_attempt(tool_state, chain_index)
            logger.info("» model chain attempt {}/{} slug={}", attempts, max_attempts, slug)
            from mergecraft.enterprise.runtime import enforce_routed_model_residency

            enforce_routed_model_residency(slug)

            resolved_harness = resolve_harness(settings, slug)
            attempt_attrs = {
                "model.id": slug,
                "model.provider": _agent_provider_for_slug(slug),
                "model.mode": resolved_harness,
                "model.fallback_index": chain_index,
                "model.attempt_number": attempts,
                "agent.provider": _agent_provider_for_slug(slug),
                "agent.mode": resolved_harness,
                "harness": resolved_harness,
                "agent.harness": resolved_harness,
                # OTel GenAI semantic-convention names so Logfire's native
                # GenAI dashboard populates. ``gen_ai.system`` is the provider
                # slug (anthropic/openai/google/opencode/...).
                "gen_ai.system": _agent_provider_for_slug(slug),
                "gen_ai.agent.name": resolved_harness,
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
                last_result = result
                last_executed_slug = slug

                call_attrs: dict[str, Any] = {
                    "model.id": slug,
                    "model.requested": requested_model or slug,
                    "model.resolved": slug,
                    "model.fallback_index": chain_index,
                    "gen_ai.operation.name": "chat",
                    "gen_ai.system": _agent_provider_for_slug(slug),
                }
                call_attrs.update(request_attrs(model=slug))
                call_attrs.update(response_attrs(model=slug))
                usage = result.usage
                if usage is not None:
                    call_attrs.update(
                        usage_attrs_from_agent_usage(
                            input_tokens=getattr(usage, "input_tokens", None),
                            output_tokens=getattr(usage, "output_tokens", None),
                            cache_read_tokens=getattr(usage, "cache_read_tokens", None),
                            cache_write_tokens=getattr(usage, "cache_write_tokens", None),
                            cost_usd=getattr(usage, "cost_usd", None),
                        )
                    )
                    for key, value in _cost_attrs_from_usage(usage).items():
                        if key.startswith("cost."):
                            call_attrs[key] = value
                else:
                    call_attrs.update(usage_unavailable_attrs())

                attempt_parent_id = (
                    attempt_span.span_id if hasattr(attempt_span, "span_id") else None
                )
                with tracer.start_span(
                    "llm.call",
                    parent_span_id=attempt_parent_id,
                    attrs_source=_snapshot_attrs(call_attrs),
                ) as _call_span:
                    pass

                skip_reason = _classify_skip_reason(result, chain_index)
                # Live path: IncrementalReview ``report_progress`` and
                # non-review modes are complete even without a terminal
                # submit. Scripted tests omit ``tool_state`` and keep D13
                # (success without a verdict still advances).
                if (
                    skip_reason == FallbackReason.no_terminal_verdict
                    and tool_state is not None
                    and not _is_incomplete_review_success(result, tool_state)
                ):
                    skip_reason = None
                elif skip_reason == FallbackReason.no_terminal_verdict and (
                    result.diagnostics or {}
                ).get("rejection_reason"):
                    skip_reason = FallbackReason.semantic_rejection
                if skip_reason is None:
                    attempt_span.set_status("ok")
                    terminal_status = "ok"
                    logger.info("» model chain succeeded slug={}", slug)
                elif not result.success and not _is_retryable_failure(result):
                    attempt_span.set_status("error", result.error or "unknown error")
                    terminal_status = "error"
                    logger.warning(
                        "» model chain slug={} failed (non-retryable): {}",
                        slug,
                        result.error or "unknown error",
                    )
                elif chain_index < len(chain) - 1:
                    if not settings.allow_fallback:
                        attempt_span.set_status("error", result.error or "fallback forbidden")
                        msg = (
                            "configuration error: allow_fallback is false — refusing "
                            f"model fallback from unavailable primary {slug!r}: "
                            f"{result.error or 'incomplete review result'}"
                        )
                        raise ModelFallbackPolicyError(msg)
                    last_skip_reason = skip_reason
                    nxt = chain[chain_index + 1]
                    attempt_span.set_status(
                        "retryable",
                        result.error or skip_reason.value,
                    )
                    terminal_status = "retryable"
                    logger.warning(
                        "model fallback occurred: requested={} skipped ({}) — "
                        "advancing to executed={} (fallback_index={})",
                        requested_model or slug,
                        skip_reason.value,
                        nxt,
                        chain_index + 1,
                    )
                elif not result.success and _is_retryable_failure(result):
                    if tail_retries >= _MAX_TAIL_RETRIES:
                        # No fallback left and the retry is spent: this failure
                        # is the answer. Returning it beats spending the attempt
                        # cap and then raising, which hides the real error.
                        attempt_span.set_status("error", result.error or "unknown error")
                        terminal_status = "error"
                        logger.warning(
                            "» model chain slug={} failed (retryable) at the chain tail "
                            "with its retry spent: {}",
                            slug,
                            result.error or "unknown error",
                        )
                    else:
                        tail_retries += 1
                        attempt_span.set_status("retryable", result.error or "unknown error")
                        terminal_status = "retryable"
                        logger.warning(
                            "» model chain slug={} failed (retryable): {} — retrying ({}/{})",
                            slug,
                            result.error or "unknown error",
                            attempts,
                            max_attempts,
                        )
                else:
                    attempt_span.set_status("error", skip_reason.value)
                    terminal_status = "error"
                    logger.warning(
                        "» model chain slug={} unusable at chain tail: {}",
                        slug,
                        skip_reason.value,
                    )

            # The ``agent.attempt`` span has now closed and emitted. Emit
            # "would-have-advanced" synthetic spans for any chain entries
            # that come after the winner so the trace tree reflects the
            # configured chain, not just the entries the runtime loop
            # happened to visit. W4.3 / issue §4 — visibility into why
            # an earlier entry was skipped.
            if terminal_status in {"ok", "error"}:
                winner_index = chain_index
                for follow_on_slug in chain[chain_index + 1 :]:
                    chain_index += 1
                    _emit_advanced_attempt(
                        tracer,
                        parent_span_id=root_parent_id,
                        slug=follow_on_slug,
                        fallback_index=chain_index,
                        settings=settings,
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
                stamped = _attach_model_evidence(
                    result,
                    requested_model=requested_model or slug,
                    executed_model=slug,
                    fallback_index=winner_index,
                    fallback_reason=last_skip_reason,
                )
                if terminal_status == "ok":
                    _root.set_status("ok")
                    return slug, stamped
                _root.set_status("error", result.error or "unknown error")
                return slug, stamped

            if chain_index < len(chain) - 1:
                if deadline is not None and time.monotonic() >= deadline:
                    # Budget spent. Stop advancing and surface the failure we
                    # already have — a further attempt cannot finish inside the
                    # run's own ceiling, and pretending otherwise just burns
                    # the job's remaining wall clock (#444).
                    logger.warning(
                        "» model chain stopped at slug={} (fallback_index={}): run budget "
                        "exhausted with {} chain entries unvisited",
                        slug,
                        chain_index,
                        len(chain) - chain_index - 1,
                    )
                    exhausted = _attach_model_evidence(
                        result,
                        requested_model=requested_model or slug,
                        executed_model=slug,
                        fallback_index=chain_index,
                        fallback_reason=last_skip_reason,
                    )
                    _root.set_status("error", "chain budget exhausted")
                    return slug, exhausted
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


def _agent_mode_for_slug(slug: str, *, settings: RepoSettings | None = None) -> str:
    """Return the agent mode name (e.g. ``claude``) that would serve ``slug``."""
    from mergecraft.config.runtime_provider_registry import infer_harness_for_slug
    from mergecraft.config.settings import load_repo_settings

    resolved_settings = settings or load_repo_settings(root=Path.cwd(), load_learnings_files=False)
    try:
        return infer_harness_for_slug(slug, settings=resolved_settings)
    except ValueError as exc:
        raise ModelFallbackPolicyError(str(exc)) from exc


_NATIVE_HARNESS_PROVIDERS: dict[str, frozenset[str]] = {
    "codex": frozenset({"openai"}),
    "claude": frozenset({"anthropic"}),
    "gemini": frozenset({"google"}),
    "cursor": frozenset({"cursor"}),
}

# OpenCode natively serves OpenAI-compatible slugs for these built-in prefixes when
# explicitly overridden to ``harness: opencode`` in the operator registry.
_OPENCODE_NATIVE_PROVIDERS = frozenset({"openai", "anthropic"})
_KNOWN_CATALOG_PROVIDERS = frozenset(
    {
        "anthropic",
        "openai",
        "google",
        "cursor",
        "bedrock",
        "vertex",
        "xai",
        "deepseek",
        "moonshotai",
        "opencode",
        "opencode-go",
        "openrouter",
    }
)


def _harness_supports_provider(harness: str, provider: str) -> bool:
    """Return whether ``harness`` may run models from ``provider``."""
    if harness == "opencode":
        return provider in _OPENCODE_NATIVE_PROVIDERS
    native = _NATIVE_HARNESS_PROVIDERS.get(harness)
    return native is not None and provider in native


def resolve_harness(settings: RepoSettings, slug: str) -> str:
    """Resolve the agent harness for ``slug`` under ``settings`` (HA3 / D11).

    Registry rows win over built-in inference. Unsupported combinations raise
    :class:`ModelFallbackPolicyError` so ``main._classify_error_outcome`` maps
    them to ``configuration_error``.
    """
    from mergecraft.config.runtime_provider_registry import registry_harness_for_provider

    provider = _agent_provider_for_slug(slug)

    if settings.harness is None:
        registry_harness = registry_harness_for_provider(settings, provider)
        if registry_harness is not None:
            if registry_harness == "opencode" or _harness_supports_provider(
                registry_harness, provider
            ):
                return registry_harness
            msg = (
                f"configuration error: harness {registry_harness!r} is incompatible with "
                f"model {slug!r} (provider {provider!r})"
            )
            raise ModelFallbackPolicyError(msg)
        return _agent_mode_for_slug(slug, settings=settings)

    harness = settings.harness
    if _harness_supports_provider(harness, provider):
        return harness

    msg = (
        f"configuration error: harness {harness!r} is incompatible with "
        f"model {slug!r} (provider {provider!r})"
    )
    raise ModelFallbackPolicyError(msg)


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


def _attempt_harness_label(settings: RepoSettings | None, slug: str) -> str:
    """Harness name stamped on an attempt span, including synthetic follow-ons.

    Visited attempts validate via :func:`resolve_harness`. Not-visited
    follow-ons must not re-validate (an unused tail slug can be an
    unsupported combo) but still stamp the operator's explicit ``harness:``
    so the trace does not mix override labels with inferred ones.

    When inference fails (unregistered provider, missing credentials), degrade
    to ``opencode`` so best-effort follow-on spans never abort a completed run.
    """
    if settings is not None and settings.harness is not None:
        return settings.harness
    try:
        return _agent_mode_for_slug(slug, settings=settings)
    except ModelFallbackPolicyError:
        return "opencode"


def _emit_advanced_attempt(
    tracer: Any,
    *,
    parent_span_id: str | None,
    slug: str,
    fallback_index: int,
    settings: RepoSettings | None = None,
) -> None:
    """Emit a synthetic ``agent.attempt`` span for a chain entry the runtime loop skipped past.

    Once the chain picks a winner (or hits a non-retryable failure), the
    loop emits follow-on synthetic spans for the remaining chain entries
    so the trace tree reflects the configured chain, not just the
    entries the runtime visited. The synthetic span's ``status`` is
    ``"not_visited"`` so consumers can distinguish it from a real
    ``"skipped"`` (no credentials/binary) entry.
    """
    harness = _attempt_harness_label(settings, slug)
    attrs = {
        "model.id": slug,
        "model.provider": _agent_provider_for_slug(slug),
        "model.mode": harness,
        "model.fallback_index": fallback_index,
        "agent.provider": _agent_provider_for_slug(slug),
        "agent.mode": harness,
        "harness": harness,
        "agent.harness": harness,
        "gen_ai.system": _agent_provider_for_slug(slug),
        "gen_ai.agent.name": harness,
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
    """Resolve the effective model string for this run.

    Precedence matches :class:`mergecraft.cli.config_precedence.ConfigLayer`:
    an explicit ``slug`` (the CLI layer) outranks ``MERGECRAFT_MODEL`` (the
    env layer). ``respect_env_override=False`` drops the env layer entirely
    for callers that have already applied their own precedence (the Action
    chain in :mod:`mergecraft.main` resolves a winning slug up front).

    An explicit slug is never discarded silently — when it is dropped in
    favour of the env override, or when it resolves to nothing, that is
    reported.
    """
    cleaned = (slug or "").strip()
    env_model = os.environ.get("MERGECRAFT_MODEL", "").strip() if respect_env_override else ""

    if cleaned:
        _enforce_resolved_model_residency(cleaned)
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

    if env_model:
        _enforce_resolved_model_residency(env_model)
        return _resolve_slug(env_model) or env_model
    return None


def _enforce_resolved_model_residency(model_id: str) -> None:
    from mergecraft.enterprise.runtime import enforce_routed_model_residency

    enforce_routed_model_residency(model_id)


def resolve_runtime_agent(
    *,
    model: str | None = None,
    settings: RepoSettings | None = None,
) -> Agent:
    """Pick the runtime agent from model, credentials, and optional ``harness:``.

    ``MERGECRAFT_AGENT`` still wins when set. When ``settings.harness`` is
    set, the explicit harness is validated against the model (D11) and
    returned — so ``harness: opencode`` with an OpenAI slug runs OpenCode
    instead of Codex. When unset, today's provider/credential inference
    applies, including fail-loud for missing native-harness credentials.
    """
    env_agent = os.environ.get("MERGECRAFT_AGENT", "").strip()
    if env_agent:
        if env_agent in agents:
            return resolve_agent(env_agent)
        logger.warning(
            '» unknown MERGECRAFT_AGENT="{}" — falling through to auto-select', env_agent
        )

    if settings is not None and settings.harness is not None:
        harness = resolve_harness(settings, model) if model else settings.harness
        return resolve_agent(harness)

    if model and _has_bedrock_auth() and os.environ.get(BEDROCK_MODEL_ID_ENV, "").strip() == model:
        return agents["claude"] if is_bedrock_anthropic_id(model) else agents["opencode"]

    if model and _has_vertex_auth() and os.environ.get(VERTEX_MODEL_ID_ENV, "").strip() == model:
        return agents["claude"] if is_vertex_anthropic_id(model) else agents["opencode"]

    if model:
        from mergecraft.config.runtime_provider_registry import (
            indexed_credential_for_entry,
            lookup_registry_entry,
        )
        from mergecraft.config.settings import load_repo_settings

        try:
            provider = get_model_provider(model)
        except ValueError:
            provider = None

        resolved_settings = settings or load_repo_settings(
            root=Path.cwd(), load_learnings_files=False
        )

        if provider == "openai":
            if _has_codex_subscription_auth() or _has_openai_api_key_auth():
                return agents["codex"]
            openai_entry = lookup_registry_entry(resolved_settings, provider)
            if openai_entry is not None:
                if indexed_credential_for_entry(openai_entry):
                    return resolve_agent(openai_entry.harness)
                msg = (
                    f"configuration error: provider {provider!r} is registered but missing "
                    f"credentials — run `mergecraft provider auth {provider}`"
                )
                raise ModelFallbackPolicyError(msg)
            _fail_loud_for_openai(model=model)

        if provider == "google":
            if _has_gemini_auth():
                return agents["gemini"]
            google_entry = lookup_registry_entry(resolved_settings, provider)
            if google_entry is not None:
                if indexed_credential_for_entry(google_entry):
                    return resolve_agent(google_entry.harness)
                msg = (
                    f"configuration error: provider {provider!r} is registered but missing "
                    f"credentials — run `mergecraft provider auth {provider}`"
                )
                raise ModelFallbackPolicyError(msg)
            _fail_loud_for_google(model=model)

        if provider == "cursor":
            if _has_cursor_auth():
                return agents["cursor"]
            cursor_entry = lookup_registry_entry(resolved_settings, provider)
            if cursor_entry is not None:
                if indexed_credential_for_entry(cursor_entry):
                    return resolve_agent(cursor_entry.harness)
                msg = (
                    f"configuration error: provider {provider!r} is registered but missing "
                    f"credentials — run `mergecraft provider auth {provider}`"
                )
                raise ModelFallbackPolicyError(msg)
            _fail_loud_for_cursor(model=model)

        if provider == "anthropic":
            if _has_claude_code_auth():
                return agents["claude"]
            anthropic_entry = lookup_registry_entry(resolved_settings, provider)
            if anthropic_entry is not None:
                if indexed_credential_for_entry(anthropic_entry):
                    return resolve_agent(anthropic_entry.harness)
                msg = (
                    f"configuration error: provider {provider!r} is registered but missing "
                    f"credentials — run `mergecraft provider auth {provider}`"
                )
                raise ModelFallbackPolicyError(msg)
            msg = (
                f"configuration error: provider {provider!r} is not registered — "
                "add it with `mergecraft provider add`"
            )
            raise ModelFallbackPolicyError(msg)

        entry = lookup_registry_entry(resolved_settings, provider) if provider else None
        if entry is not None:
            if indexed_credential_for_entry(entry):
                return resolve_agent(entry.harness)
            from mergecraft.config.runtime_provider_registry import (
                legacy_opencode_harness_for_provider,
            )

            assert provider is not None
            legacy_harness = legacy_opencode_harness_for_provider(provider)
            if legacy_harness is not None:
                return resolve_agent(legacy_harness)
            msg = (
                f"configuration error: provider {provider!r} is registered but missing "
                f"credentials — run `mergecraft provider auth {provider}`"
            )
            raise ModelFallbackPolicyError(msg)

        if provider is not None:
            from mergecraft.config.runtime_provider_registry import (
                legacy_opencode_harness_for_unregistered_provider,
            )

            legacy_harness = legacy_opencode_harness_for_unregistered_provider(
                resolved_settings,
                provider,
            )
            if legacy_harness is not None:
                return resolve_agent(legacy_harness)

            msg = (
                f"configuration error: provider {provider!r} is not registered — "
                "add it with `mergecraft provider add`"
            )
            raise ModelFallbackPolicyError(msg)

    return agents["opencode"]


__all__ = [
    "FallbackReason",
    "ModelFallbackPolicyError",
    "configured_model_slugs",
    "effective_model_chain",
    "effective_model_slugs",
    "has_credentials_for_slug",
    "is_runnable_model_slug",
    "pick_runnable_slug_from_chain",
    "promote_model_evidence",
    "resolve_effective_model_slug",
    "resolve_harness",
    "resolve_model",
    "resolve_runtime_agent",
    "run_with_model_chain",
    "select_runnable_model_slug",
    "stamp_attempt_id",
]
