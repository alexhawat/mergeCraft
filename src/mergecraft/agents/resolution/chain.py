"""Build and run ordered model chains with attempt evidence and tracing.

Module: mergecraft.agents.resolution.chain
Depends: mergecraft.{agents,config,enterprise,errors,mcp,models,run_outcome,tracing,utils}, loguru

Exports:
    Classes:
        FallbackReason — Why a model-chain entry was skipped.
    Functions:
        effective_model_chain — Build the ordered chain under current policy.
        pick_runnable_slug_from_chain — Select a runnable entry from a chain.
        run_with_model_chain — Execute attempts and advance on eligible failures.
"""

from __future__ import annotations

import sys
import time
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.agents.resolution import credentials, runtime
from mergecraft.agents.shared import AgentResult
from mergecraft.config.env import AgentRuntimeEnv
from mergecraft.errors import ModelFallbackPolicyError
from mergecraft.models import MAX_FALLBACK_DEPTH, MODEL_ALIASES, ModelAlias
from mergecraft.run_outcome import is_incremental_review, is_review_mode
from mergecraft.tracing.genai import (
    input_messages_attrs,
    output_messages_attrs,
    request_attrs,
    resolve_capture_policy,
    response_attrs,
    usage_attrs_from_agent_usage,
    usage_unavailable_attrs,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from mergecraft.config.settings import RepoSettings
    from mergecraft.mcp.tool_state import ToolState


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


def is_runnable_model_slug(slug: str) -> bool:
    """Return whether ``slug`` has credentials and an agent CLI available."""
    if not credentials.has_credentials_for_slug(slug):
        return False
    return runtime.agent_binary_available(slug)


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
    env_model = AgentRuntimeEnv().model or ""
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
    ``MERGECRAFT_MODEL`` (``runtime.resolve_model(slug=None)`` alone never reads
    config — it only checks an explicit slug and the env override;
    mergeCraft self-review, PR #216, caught `mergecraft eval bench`
    advertising config-only resolution while never actually consulting it).

    Precedence: ``MERGECRAFT_MODEL`` env override, else the first
    configured slug with detected credentials, else the first configured
    slug regardless, else ``settings.model`` resolved through the alias
    catalog.
    """
    env_model = AgentRuntimeEnv().model or ""
    if env_model:
        return env_model

    configured = _configured_model_slugs(settings)
    for slug in configured:
        if credentials.has_credentials_for_slug(slug):
            return slug

    if configured:
        return configured[0]

    return runtime.resolve_model(slug=settings.model)


def _alias_for_slug(slug: str) -> ModelAlias | None:
    return next(
        (alias for alias in MODEL_ALIASES if alias.slug == slug or alias.resolve == slug), None
    )


def catalog_fallback_tail(slug: str) -> list[str]:
    tail: list[str] = []
    current = slug
    visited: set[str] = set()
    for _ in range(MAX_FALLBACK_DEPTH):
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
    for fallback in catalog_fallback_tail(slug):
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

    env_model = AgentRuntimeEnv().model or ""
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

    return _filter_chain_for_residency(chain[:MAX_FALLBACK_DEPTH])


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
        if not credentials.has_credentials_for_slug(slug):
            msg = (
                f"configuration error: allow_fallback is false and primary model "
                f"{slug!r} is unavailable (missing credentials)"
            )
            raise ModelFallbackPolicyError(msg)
        if not runtime.agent_binary_available(slug):
            msg = (
                f"configuration error: allow_fallback is false and primary model "
                f"{slug!r} is unavailable (agent binary missing)"
            )
            raise ModelFallbackPolicyError(msg)
        logger.info("» model chain selected slug={} (allow_fallback=false)", slug)
        return slug

    skipped: list[str] = []
    from mergecraft.config.settings import load_repo_settings

    probe_settings = load_repo_settings(root=Path.cwd(), load_learnings_files=False)
    probe_cwd = Path.cwd()
    for slug in chain:
        if not credentials.has_credentials_for_slug(slug):
            status = credentials.credential_status_for_slug(
                slug,
                settings=probe_settings,
                cwd=probe_cwd,
                wired=True,
            )
            envs = ", ".join(status.looked_for) or "credential env vars"
            skipped.append(f"{slug} (missing credentials; consult {envs})")
            continue
        if not runtime.agent_binary_available(slug):
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


def chain_deadline() -> float | None:
    """Monotonic wall-clock ceiling for the whole chain, or ``None`` when unset.

    Retryable failures are what make the chain useful, but a retryable
    *timeout* costs a full external-operation budget each time it recurs, so an
    attempt-count cap alone is not a bound: ten 1500s timeouts is a four-hour
    run. This ceiling reuses the existing per-run ``run_timeout_s`` budget
    rather than introducing a second notion of "too long" (#444).

    A malformed run-bounds override (``resolve_run_bounds`` raises
    ``ValueError`` when an env value does not parse) keeps the chain bounded:
    it falls back to the default run timeout and logs a warning.
    """
    from mergecraft.utils.run_bounds import DEFAULT_RUN_TIMEOUT_S, resolve_run_bounds

    try:
        run_timeout_s = resolve_run_bounds().run_timeout_s
    except ValueError as exc:
        logger.warning(
            "chain deadline: run bounds unresolvable ({}); using the default run timeout {}s",
            exc,
            DEFAULT_RUN_TIMEOUT_S,
        )
        run_timeout_s = DEFAULT_RUN_TIMEOUT_S
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


def is_retryable_failure(result: AgentResult) -> bool:
    """Decide whether a failed attempt may advance the chain (#447).

    Precedence, and the only decision path — ``retryable_failure_reason``
    labels a skip that this function has already decided:

    1. An explicit ``metadata["retryable"]`` (``True`` or ``False``) wins. A
       driver that states its intent is always believed.
    2. Unset means *infer* from the failure.

    Unset used to mean "permanent", which made a driver's omission silently
    fatal rather than merely imprecise: #444 was exactly that shape — an
    opencode timeout whose error text said "timed out", which
    ``retryable_failure_reason`` duly labelled ``FallbackReason.timeout``,
    terminating the run at attempt 1 because the deciding classifier read only
    the absent flag. Inference keeps a forgotten flag from costing a review.
    """
    metadata = result.metadata or {}
    declared = metadata.get("retryable")
    if isinstance(declared, bool):
        return declared
    return _inferred_retryable(result)


def is_failover_eligible(result: AgentResult) -> bool:
    """Whether a driver declared this failure a reason to move to the next vendor (#1009).

    ``metadata["failover_eligible"] is True`` is distinct from ``retryable``: it
    says the *next* chain entry may succeed even though re-issuing the call
    against this one cannot (an expired subscription login). Only the literal
    ``True`` counts, as with ``retryable``.
    """
    from mergecraft.agents.shared import FAILOVER_ELIGIBLE_KEY

    return (result.metadata or {}).get(FAILOVER_ELIGIBLE_KEY) is True


def may_advance_chain(result: AgentResult) -> bool:
    """Whether a failed attempt may hand the review to the next chain entry.

    A retryable failure may (the next entry can only do better than a retry of
    this one), and so may a failover-eligible one that is not retryable. Only
    :func:`is_retryable_failure` licenses an in-place retry at the chain tail,
    so a failover-eligible failure there is the run's answer, not a retry.
    """
    return is_retryable_failure(result) or is_failover_eligible(result)


def retryable_failure_reason(result: AgentResult) -> FallbackReason:
    """Label a failure for tracing. Never decides — see ``is_retryable_failure``."""
    error = (result.error or "").lower()
    metadata = result.metadata or {}
    if "timeout" in error or "timed out" in error or metadata.get("timeout") is True:
        return FallbackReason.timeout
    if "crash" in error or metadata.get("crash") is True:
        return FallbackReason.crash
    return FallbackReason.provider_error


def classify_skip_reason(result: AgentResult, chain_index: int) -> FallbackReason | None:
    """Return why ``result`` cannot be the chain winner, or ``None`` when usable."""
    diagnostics = result.diagnostics or {}
    attempt_id = diagnostics.get("attempt_id")
    if attempt_id is not None and attempt_id != chain_index:
        return FallbackReason.stale_attempt

    if result.terminal_submission_received:
        # #1132 — an accepted verdict from this attempt is the answer even when
        # the CLI then exited non-zero; advancing the chain would spend another
        # rung re-reviewing a PR that already has its verdict.
        if not result.success:
            logger.warning(
                "» model chain attempt exited unsuccessfully after an accepted verdict; "
                "keeping its verdict: {}",
                result.error or "unknown error",
            )
        return None

    if not result.success:
        return retryable_failure_reason(result)

    if diagnostics.get("malformed_submission"):
        return FallbackReason.malformed_submission
    return FallbackReason.no_terminal_verdict


def is_incomplete_review_success(
    result: AgentResult,
    tool_state: ToolState | None,
) -> bool:
    """True when a successful provider result is not a usable review winner.

    Scripted chain tests that omit ``tool_state`` keep success=True winner
    semantics. The live orchestrator always passes ``tool_state``.
    """
    if tool_state is None or not result.success or result.terminal_submission_received:
        return False

    mode = tool_state.selected_mode
    if mode is not None and not is_review_mode(mode):
        return False
    if is_incremental_review(mode) and tool_state.final_summary_written:
        return False
    submission = tool_state.terminal_submission
    if submission is not None and not tool_state.terminal_submission_conflict:
        return bool((result.diagnostics or {}).get("rejection_reason"))
    return True


def attach_model_evidence(
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
            "provider": runtime.agent_provider_for_slug(executed_model),
            "fallback_index": fallback_index,
            "fallback_occurred": fallback_index > 0,
        }
    )
    if fallback_reason is not None:
        meta["fallback_reason"] = fallback_reason
    result.metadata = meta
    return result


def _stamp_chain_llm_call(
    span: Any,
    *,
    slug: str,
    requested_model: str | None,
    chain_index: int,
    result: AgentResult,
    trust_tier: str | None,
) -> None:
    """Stamp usage, identity, and policy-gated prompt/completion on ``llm.call``."""
    span.set_attribute("model.id", slug)
    span.set_attribute("model.requested", requested_model or slug)
    span.set_attribute("model.resolved", slug)
    span.set_attribute("model.fallback_index", chain_index)
    span.set_attribute("gen_ai.operation.name", "chat")
    span.set_attribute("gen_ai.system", runtime.agent_provider_for_slug(slug))
    for key, value in request_attrs(model=slug).items():
        span.set_attribute(key, value)
    for key, value in response_attrs(model=slug).items():
        span.set_attribute(key, value)
    usage = result.usage
    if usage is not None:
        for key, value in usage_attrs_from_agent_usage(
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            cache_read_tokens=getattr(usage, "cache_read_tokens", None),
            cache_write_tokens=getattr(usage, "cache_write_tokens", None),
            cost_usd=getattr(usage, "cost_usd", None),
        ).items():
            span.set_attribute(key, value)
        for key, value in cost_attrs_from_usage(usage).items():
            if key.startswith("cost."):
                span.set_attribute(key, value)
    else:
        for key, value in usage_unavailable_attrs().items():
            span.set_attribute(key, value)
    policy = resolve_capture_policy(trust_tier)
    if result.prompt:
        for key, value in input_messages_attrs(
            [{"role": "user", "content": result.prompt}],
            policy=policy,
        ).items():
            span.set_attribute(key, value)
    if result.output:
        for key, value in output_messages_attrs(
            [{"role": "assistant", "content": result.output}],
            policy=policy,
        ).items():
            span.set_attribute(key, value)


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

    Used for both the chain path (after :func:`attach_model_evidence`) and the
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


def prepare_chain_attempt(tool_state: ToolState | None, fallback_index: int) -> None:
    """Stamp the active chain index and drop the prior attempt's submission and packet.

    The prepared evidence packet is built from the attempt that submitted; a
    fallback attempt rebuilds it, so the run record describes the final attempt
    rather than the one before it.
    """
    if tool_state is None:
        return
    stamp_attempt_id(tool_state, attempt_id=fallback_index, fallback_index=fallback_index)
    tool_state.terminal_submission = None
    tool_state.terminal_submission_conflict = False
    tool_state.prepared_run_packet = None
    tool_state.driver_reports_reads = False


async def run_with_model_chain(
    *,
    settings: RepoSettings,
    run_once: Callable[[str], Awaitable[AgentResult]],
    max_attempts: int = MAX_FALLBACK_DEPTH,
    correlation: dict[str, Any] | None = None,
    head: str | None = None,
    pin: bool = False,
    tool_state: ToolState | None = None,
) -> tuple[str, AgentResult]:
    """Walk the model chain, advancing on retryable or failover-eligible failures.

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
    from mergecraft.tracing.tracer import (
        get_tracer_from_settings,
        resolve_correlation_from_env,
        run_root_span,
    )

    tracer = get_tracer_from_settings(settings, new_run=True)
    correlation_attrs = (
        dict(correlation) if correlation is not None else resolve_correlation_from_env()
    )

    chain = effective_model_chain(settings, head=head, pin=pin)
    requested_model = chain[0] if chain else (head or "")

    # Action and offline orchestration own the lifecycle root. Standalone
    # callers still get a complete trace, while nested chain dispatch reuses
    # the active run instead of creating a second root.
    with run_root_span(tracer, attrs_source=lambda: dict(correlation_attrs)) as _root:
        if not chain:
            _empty_result = empty_chain_result()
            _root.set_status("error", _empty_result.error or "empty model chain")
            return "", _empty_result

        chain_index = 0
        attempts = 0
        last_skip_reason: FallbackReason | None = None
        deadline = chain_deadline()
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
            if runtime.agent_mode_for_slug(slug, settings=settings) == "opencode":
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
                    spent = attach_model_evidence(
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
            prepare_chain_attempt(tool_state, chain_index)
            logger.info("» model chain attempt {}/{} slug={}", attempts, max_attempts, slug)
            from mergecraft.enterprise.runtime import enforce_routed_model_residency

            enforce_routed_model_residency(slug)

            resolved_harness = runtime.resolve_harness(settings, slug)
            attempt_attrs = {
                "model.id": slug,
                "model.provider": runtime.agent_provider_for_slug(slug),
                "model.mode": resolved_harness,
                "model.fallback_index": chain_index,
                "model.attempt_number": attempts,
                "agent.provider": runtime.agent_provider_for_slug(slug),
                "agent.mode": resolved_harness,
                "harness": resolved_harness,
                "agent.harness": resolved_harness,
                # OTel GenAI semantic-convention names so Logfire's native
                # GenAI dashboard populates. ``gen_ai.system`` is the provider
                # slug (anthropic/openai/google/opencode/...).
                "gen_ai.system": runtime.agent_provider_for_slug(slug),
                "gen_ai.operation.name": "invoke_agent",
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
                attempt_parent_id = (
                    attempt_span.span_id if hasattr(attempt_span, "span_id") else None
                )
                with tracer.start_span(
                    "llm.call",
                    parent_span_id=attempt_parent_id,
                ) as call_span:
                    result = await run_once(slug)
                    last_result = result
                    last_executed_slug = slug
                    _stamp_chain_llm_call(
                        call_span,
                        slug=slug,
                        requested_model=requested_model,
                        chain_index=chain_index,
                        result=result,
                        trust_tier=(
                            getattr(tool_state, "trust_tier", None)
                            if tool_state is not None
                            else None
                        ),
                    )

                skip_reason = classify_skip_reason(result, chain_index)
                # Live path: IncrementalReview ``report_progress`` and
                # non-review modes are complete even without a terminal
                # submit. Scripted tests omit ``tool_state`` and keep D13
                # (success without a verdict still advances).
                if (
                    skip_reason == FallbackReason.no_terminal_verdict
                    and tool_state is not None
                    and not is_incomplete_review_success(result, tool_state)
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
                elif not result.success and not may_advance_chain(result):
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
                elif not result.success and is_retryable_failure(result):
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
                elif not result.success:
                    # Failover-eligible but not retryable, with nothing left to
                    # fail over to: re-running this entry against the same
                    # credential cannot succeed (#1009), so it is the answer.
                    attempt_span.set_status("error", result.error or "unknown error")
                    terminal_status = "error"
                    logger.warning(
                        "» model chain slug={} failed (failover-eligible, not retryable) "
                        "at the chain tail: {}",
                        slug,
                        result.error or "unknown error",
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
                stamped = attach_model_evidence(
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
                    exhausted = attach_model_evidence(
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


def cost_attrs_from_usage(usage: Any) -> dict[str, Any]:
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


def empty_chain_result() -> AgentResult:
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


def attempt_harness_label(settings: RepoSettings | None, slug: str) -> str:
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
        return runtime.agent_mode_for_slug(slug, settings=settings)
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
    harness = attempt_harness_label(settings, slug)
    attrs = {
        "model.id": slug,
        "model.provider": runtime.agent_provider_for_slug(slug),
        "model.mode": harness,
        "model.fallback_index": fallback_index,
        "agent.provider": runtime.agent_provider_for_slug(slug),
        "agent.mode": harness,
        "harness": harness,
        "agent.harness": harness,
        "gen_ai.system": runtime.agent_provider_for_slug(slug),
        "gen_ai.operation.name": "invoke_agent",
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


__all__ = [
    "FallbackReason",
    "attach_model_evidence",
    "attempt_harness_label",
    "catalog_fallback_tail",
    "chain_deadline",
    "classify_skip_reason",
    "configured_model_slugs",
    "cost_attrs_from_usage",
    "effective_model_chain",
    "effective_model_slugs",
    "empty_chain_result",
    "is_failover_eligible",
    "is_incomplete_review_success",
    "is_retryable_failure",
    "is_runnable_model_slug",
    "may_advance_chain",
    "pick_runnable_slug_from_chain",
    "prepare_chain_attempt",
    "promote_model_evidence",
    "resolve_effective_model_slug",
    "retryable_failure_reason",
    "run_with_model_chain",
    "select_runnable_model_slug",
    "stamp_attempt_id",
]
