"""Main orchestration — local-config BYOK runtime (no mergecraft.com)."""

from __future__ import annotations

import asyncio
import contextlib
import os
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.action.inputs import (
    apply_setup_overrides,
    apply_tracing_overrides,
    collect_tracing_warnings_for_summary,
    export_tracing_env_from_action_inputs,
)
from mergecraft.agents.gates import subagent_denied_tool_names
from mergecraft.agents.post_run import finalize_agent_result
from mergecraft.agents.shared import Agent, AgentResult, AgentRunContext
from mergecraft.agents.verifier import verifier_denied_tool_names
from mergecraft.analyzers.redact import install_loguru_redaction_filter, redact_secrets
from mergecraft.analyzers.sarif_upload import resolve_sarif_upload_enabled
from mergecraft.analyzers.trust import (
    allow_repo_command_overrides,
    derive_trust_tier,
    resolve_analyzers_mode,
)
from mergecraft.ci.sarif_ingest import ingest_ci_sarif_from_action_env
from mergecraft.evidence.run_packet import emit_run_packet, resolve_prepared_run_packet
from mergecraft.main_outcome import (
    _classify_outcome,
    _publish_span_attrs,
    _verdict_protocol_publish,
)
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.dependencies import start_installation
from mergecraft.mcp.endpoints import mcp_role_url
from mergecraft.mcp.server import start_mcp_http_server
from mergecraft.mcp.tool_state import ProgressComment, ToolState, init_tool_state
from mergecraft.modes import _custom_modes, compute_modes
from mergecraft.prep.types import is_prep_install_failure
from mergecraft.review.engine import ReviewEngine
from mergecraft.review.snapshot import ReviewSnapshot, canonical_review_snapshot
from mergecraft.review_checks import StaticCheckConfig
from mergecraft.run_outcome import RUN_OUTCOME_CONCLUSION, RunOutcome, run_succeeded_for_outcome
from mergecraft.scm.github import (
    create_github_scm,
    github_client_from_scm,
)
from mergecraft.tracing.review_context import (
    ReviewContext,
    bind_review_context,
    correlation_key_for,
    resolve_review_id,
)
from mergecraft.tracing.tracer import resolve_correlation_from_env
from mergecraft.utils import gha_log
from mergecraft.utils.agent_resolve import (
    ModelFallbackPolicyError,
    effective_model_chain,
    pick_runnable_slug_from_chain,
    promote_model_evidence,
    resolve_model,
    resolve_runtime_agent,
    run_with_model_chain,
)
from mergecraft.utils.code_scanning import report_sarif_upload
from mergecraft.utils.git_setup import (
    cleanup_temp_directory,
    create_temp_directory,
    setup_git,
    wipe_runner_leak_surface,
)
from mergecraft.utils.github import GitHubClient, resolve_run_context_data
from mergecraft.utils.instructions import resolve_instructions
from mergecraft.utils.learnings import (
    persist_learnings,
    seed_learnings_file,
    seed_xrepo_learnings_file,
)
from mergecraft.utils.log import bind_run_context
from mergecraft.utils.normalize_env import normalize_env
from mergecraft.utils.payload import (
    TIMEOUT_DISABLED,
    JsonPayload,
    read_github_event,
    resolve_output_schema,
    resolve_payload,
    resolve_prompt_input,
    resolve_timeout_ms,
)
from mergecraft.utils.privilege import prepare_workspace_for_agent
from mergecraft.utils.process_group import (
    kill_all_active_process_groups,
    kill_process_group,
    register_process_group,
    unregister_process_group,
)
from mergecraft.utils.secrets import set_env_allowlist
from mergecraft.utils.skills import install_bundled_skills
from mergecraft.utils.status_checks import report_status_checks
from mergecraft.utils.token import TokenRef, get_job_token, resolve_tokens
from mergecraft.utils.workspace import (
    WorkspacePathError,
    ensure_github_workspace_registered,
    resolve_allowed_working_directory,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from mergecraft.analyzers.manifest import TrustTier
    from mergecraft.config.settings import RepoSettings, RunContextData
    from mergecraft.evidence.shadow import VerdictProtocolPrediction
    from mergecraft.mcp.verdict import VerdictDiagnostic
    from mergecraft.scm.protocol import ScmProvider


@dataclass(slots=True)
class MainResult:
    success: bool
    output: str | None = None
    error: str | None = None
    result: str | None = None
    # On-disk path of this run's merge evidence packet (#47 / #96), or None
    # when the run had no pull request to attest to. Surfaced as the action's
    # ``evidence_packet`` output by ``cli/gha_cmd.py`` (W5.4).
    evidence_packet_path: str | None = None
    # D3/W5.1-W5.2 — the closed six-value taxonomy this run landed in.
    # ``None`` only for call sites that predate W5 (tests constructing a
    # ``MainResult`` directly); every real ``main()`` return path sets it.
    outcome: RunOutcome | None = None
    # W8 / #265 — closed VerdictDiagnostic code for the terminal-verdict policy
    # path. ``None`` for early-exit paths that bypass ``_finalize``; the GHA
    # surface writes an empty string in that case (D10).
    verdict_diagnostic: VerdictDiagnostic | None = None


@dataclass
class RunContext:
    """Mutable state threaded across ``main()``'s phases (G4.2 extraction).

    Every field is optional/defaulted because the object is built empty at
    the top of :func:`main` and filled in incrementally by ``_setup_run`` →
    ``_resolve_credentials`` → ``_execute_agent``. This is the same
    local-variable sprawl ``main()`` threaded as bare locals before the
    split — carrying it explicitly is what lets the phases be separate
    functions instead of one 700-line body. Fields are grouped by the phase
    that first populates them; later phases only ever *add* fields, never
    remove or reinterpret ones set earlier.
    """

    # -- populated by ``_setup_run`` -----------------------------------------
    resolved_prompt: str | JsonPayload = ""
    job_token: str = ""
    scm: ScmProvider | None = None
    run_context: RunContextData | None = None
    settings: RepoSettings | None = None
    gh_event: dict[str, Any] | None = None
    pr_number: int | str | None = None
    tool_state: ToolState | None = None
    tmpdir: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    timeout_ms: int | None = None
    timeout_raw: Any = None
    timeout_error: str | None = None

    # -- populated by ``_resolve_credentials`` (security boundary) ----------
    trust_tier: TrustTier = "untrusted"
    authority_trust: TrustTier = "untrusted"
    trust_self_review_level: str = "off"
    token_ref: TokenRef | None = None
    # D7 — whether the run-start settings snapshot is operator-owned (the base
    # ref, on a ``pull_request_target`` run, before ``checkout_pr`` ever runs).
    # Carried forward so ``_build_run_tool_context`` doesn't take a second,
    # independent read of ``GITHUB_EVENT_NAME`` for the same decision.
    settings_snapshot_operator_owned: bool = False

    # -- populated by ``_execute_agent`` -------------------------------------
    model_pin: bool = False
    model_head: str | None = None
    chain_for_decision: list[str] = field(default_factory=list)
    use_model_chain: bool = False
    selected_slug: str | None = None
    resolved_model: str | None = None
    agent: Agent | None = None
    agent_id: Any = ""
    modes: list[Any] = field(default_factory=list)
    output_schema: dict[str, Any] | None = None
    ctx_payload: ResolvedPayload | None = None
    analyzers_mode: Any = None
    sarif_upload_enabled: bool = False
    tool_context: ToolContext | None = None
    setup_timeout_s: int = 0
    setup_hook_failure: str = ""
    setup_script_skip_reason: str = ""
    setup_elapsed_s: float = 0.0
    mcp_url: str = ""
    stop_mcp: Callable[[], None] | None = None
    subagent_denied: list[str] = field(default_factory=list)
    verifier_denied: list[str] = field(default_factory=list)
    instructions: Any = None
    run_ctx: AgentRunContext | None = None
    run_bounds: Any = None
    budget_tracker: Any = None
    budget_exhaustion: Any = None

    async def materialize(self) -> None:
        with gha_log.group("setup"):
            await _setup_run(self)
            await _resolve_credentials(self)
        if self.setup_script_skip_reason:
            gha_log.warning(self.setup_script_skip_reason)

    async def analyze(self) -> None:
        with gha_log.group("model-chain"):
            await _assemble_model_chain(self)
            await _build_run_tool_context(self)

    async def review(self) -> AgentResult | SkipAgentReview:
        return await _run_review_after_analyze(self)

    async def publish(self, review_out: AgentResult | SkipAgentReview) -> MainResult:
        with gha_log.group("publish"):
            return await _finalize(self, review_out)


@dataclass(frozen=True, slots=True)
class SkipAgentReview:
    """Review-stage outcome when setup-script policy skips the agent loop."""

    reason: str


def _first_runnable_in_chain(chain: list[str]) -> str:
    """Harness-patchable one-arg facade over :func:`pick_runnable_slug_from_chain`.

    ``allow_fallback`` lives on the function object (not a module global) so the
    harness can still replace this symbol with ``lambda chain: …`` while
    ``main`` stamps the policy before calling.
    """
    allow = bool(getattr(_first_runnable_in_chain, "allow_fallback", True))
    return pick_runnable_slug_from_chain(chain, allow_fallback=allow)


_first_runnable_in_chain.allow_fallback = True  # type: ignore[attr-defined]  # — allow_fallback is a runtime attribute added to the function object for chain control


def _payload_to_ctx(payload: dict[str, Any]) -> ResolvedPayload:
    event_val = payload.get("event")
    raw_event: dict[str, Any] = event_val if isinstance(event_val, dict) else {}
    event = PayloadEvent(
        trigger=str(raw_event.get("trigger") or "unknown"),
        issue_number=raw_event.get("issue_number"),
        is_pr=bool(raw_event.get("is_pr")),
        branch=raw_event.get("branch"),
        title=raw_event.get("title"),
        body=raw_event.get("body"),
    )
    return ResolvedPayload(
        event=event,
        shell=payload.get("shell") or "restricted",
        push=payload.get("push") or "restricted",
        triggerer=payload.get("triggerer"),
        model=payload.get("model"),
        cwd=payload.get("cwd"),
        generate_summary=bool(payload.get("generateSummary")),
        status_checks=bool(payload.get("statusChecks")),
        suggest_eval_add=bool(payload.get("suggestEvalAdd")),
        timeout=payload.get("timeout"),
        prompt=str(payload.get("prompt") or ""),
        xrepo=payload.get("xrepo"),
        extra=payload,
    )


class _AgentTimeoutError(RuntimeError):
    """Marks the ``asyncio.wait_for`` timeout path (D3/W5.2).

    A plain ``RuntimeError`` would be indistinguishable from any other agent
    crash once it reaches the outer catch-all; this subclass lets
    ``_classify_error_outcome`` tag it ``RunOutcome.timed_out`` instead of
    the generic ``infra_error`` default.
    """


class _ConfigurationError(RuntimeError):
    """Marks fail-closed configuration errors (D4/W6.3).

    Raised for unparseable Action inputs (e.g. ``timeout``) so the outer
    handler can tag ``RunOutcome.configuration_error`` without confusing
    them with infra crashes.
    """


def _classify_error_outcome(error: BaseException) -> RunOutcome:
    """Split the outer catch-all into timeout / config / infra buckets (D3, W5.2).

    Defaults to ``infra_error`` — that is the "infra never looks like
    success" invariant the taxonomy replaces the old plain boolean with.
    Only exceptions that already carry an unambiguous, distinct cause are
    reclassified; an unclassified agent crash stays ``infra_error``.
    """
    from pydantic import ValidationError

    if isinstance(error, (_AgentTimeoutError, TimeoutError, asyncio.TimeoutError)):
        return RunOutcome.timed_out
    if isinstance(
        error,
        (_ConfigurationError, ModelFallbackPolicyError, WorkspacePathError, ValidationError),
    ):
        return RunOutcome.configuration_error
    return RunOutcome.infra_error


def _short_circuit_setup_failure(
    setup_hook_failure: str,
    setup_failure_policy: str,
) -> tuple[str, _ConfigurationError | str | None]:
    """Decide whether a trusted-tier ``setup_script`` failure short-circuits the run (S1 / D10).

    Returns a 2-tuple ``(action, payload)`` consumed by :func:`main`:

    - ``("abort", _ConfigurationError(reason))`` — ``fail`` policy. Raise the
      exception so the outer handler maps the run to ``configuration_error``
      while still calling ``report_status_checks`` and ``persist_learnings``.
    - ``("skip_agent", reason)`` — ``inconclusive`` policy. The agent loop
      must NOT run (no review/mutation tools); ``main`` returns a
      ``MainResult(outcome=RunOutcome.inconclusive)`` after running the
      publish block.
    - ``("continue", None)`` — no failure, ``warn`` policy, or otherwise. The
      agent loop proceeds.

    The ``fail`` branch raises rather than returning ``RunOutcome`` directly
    so the operator gets the existing configuration-error semantics (same
    path as invalid action-input values). The ``inconclusive`` branch uses a
    sentinel return so ``main`` can run the publish block — skipping that
    would leave the run without a status check.
    """
    if not setup_hook_failure:
        return ("continue", None)
    if setup_failure_policy == "fail":
        return ("abort", _ConfigurationError(setup_hook_failure))
    if setup_failure_policy == "inconclusive":
        return ("skip_agent", setup_hook_failure)
    # ``warn`` and any other value fall through; the late outcome block at
    # the bottom of ``main`` handles them.
    return ("continue", None)


async def publish_deterministic_record(
    *,
    pull_number: int,
    packet: Any,
    rejection_reason: str | None = None,
    tmpdir: str | None = None,
    ctx: ToolContext | None = None,
    run_outcome: RunOutcome | None = None,
    verdict_diagnostic: Any | None = None,
) -> None:
    """Publish the deterministic sticky record for a resolved PR (D6, plan 13 A4).

    Plan 13 ``run_post_run_retry_loop`` routes non-retryable rejections here.
    Stable signature for cross-plan callers::

        publish_deterministic_record(
            *,
            pull_number: int,
            packet: MergeEvidencePacket,
            rejection_reason: str | None = None,
            tmpdir: str | None = None,
            ctx: ToolContext | None = None,
            run_outcome: RunOutcome | None = None,
            verdict_diagnostic: VerdictDiagnostic | None = None,
        ) -> None
    """
    from mergecraft.findings.ledger import (
        render_deterministic_review_block,
        upsert_sticky_progress_comment,
    )
    from mergecraft.scm.github import create_github_scm
    from mergecraft.utils.status_checks import _run_url

    resolved_ctx = ctx
    if resolved_ctx is None:
        tool_state = init_tool_state(owner="local", name="local", dir=tmpdir or ".")
        tool_state.pr_number = pull_number
        resolved_ctx = ToolContext(
            agent_id="claude",
            repo=RepoIdentity(owner="local", name="local"),
            payload=ResolvedPayload(
                event=PayloadEvent(trigger="pull_request", issue_number=pull_number, is_pr=True),
            ),
            scm=create_github_scm(""),
            modes=compute_modes("claude"),
            tool_state=tool_state,
            tmpdir=tmpdir or ".",
        )

    tool_state = resolved_ctx.tool_state
    submission = tool_state.terminal_submission
    analyzer_run = tool_state.analyzer_run
    block = render_deterministic_review_block(
        packet=packet,
        rejection_reason=rejection_reason,
        run_url=_run_url(resolved_ctx),
        run_outcome=run_outcome,
        verdict_diagnostic=verdict_diagnostic,
        analyzer_summary=analyzer_run.pre_merge_summary if analyzer_run is not None else None,
        agent_summary=submission.summary if submission is not None else None,
        trust_tier=resolved_ctx.trust_tier,
        attempt_count=len(tool_state.usage_entries) if tool_state.usage_entries else None,
        token_summary=_token_summary(
            tool_state.usage_entries,
            budget_tracker=resolved_ctx.budget_tracker,
        ),
        credential_degradations=list(tool_state.credential_degradations),
        agent_sandbox_decision=tool_state.agent_sandbox_decision,
    )
    await upsert_sticky_progress_comment(resolved_ctx, block)


def _token_summary(
    usage_entries: list[Any],
    *,
    budget_tracker: Any | None = None,
) -> str | None:
    from mergecraft.utils.run_bounds import BudgetTracker, token_summary_from_usage

    tracker = budget_tracker if isinstance(budget_tracker, BudgetTracker) else None
    return token_summary_from_usage(usage_entries, budget_tracker=tracker)


async def _publish(
    ctx: RunContext,
    *,
    outcome: RunOutcome,
    failure_reason: str | None,
    attrs_source: Callable[[], dict[str, Any]] | None = None,
    verdict_prediction: VerdictProtocolPrediction | None = None,
    actual_outcome: str | None = None,
    verdict_diagnostic: Any | None = None,
    emit: bool = True,
) -> str | None:
    """Prepare packet + persist learnings + status checks, then optionally emit.

    Shared by the setup-script "inconclusive" short-circuit (G4.2), the
    normal post-agent path in ``_finalize``, and the exception cleanup path
    (``emit=False`` — failure still reports status but skips SARIF/packet
    emit). Tracer span wraps the emit path only.
    """
    tool_context = ctx.tool_context
    if tool_context is None:
        return None
    run_ok = run_succeeded_for_outcome(outcome)
    prepared = resolve_prepared_run_packet(tool_context, run_succeeded=run_ok)

    async def _learnings_and_status() -> None:
        await persist_learnings(tool_context)
        await report_status_checks(
            tool_context,
            run_succeeded=run_ok,
            failure_reason=failure_reason,
            conclusion=RUN_OUTCOME_CONCLUSION[outcome],
            packet=prepared,
        )
        pull_number = tool_context.tool_state.pr_number
        if pull_number is None and tool_context.payload.event.issue_number is not None:
            pull_number = int(tool_context.payload.event.issue_number)
        # A refused terminal verdict (scope, schema, semantic or policy) is
        # recorded on ``tool_state``; it names the actual cause, so it wins over
        # the generic run failure reason. This is deliberately not gated on
        # ``prepared.decision is None``: ``decide_approval`` always returns a
        # ``PacketDecision``, so that condition never holds and the reason never
        # reached the record — a refused run read as a clean one (plan 13 D5).
        rejection_reason = tool_context.tool_state.last_terminal_rejection
        if rejection_reason is None and prepared is not None and prepared.decision is None:
            rejection_reason = failure_reason
        if pull_number is not None and prepared is not None:
            await publish_deterministic_record(
                pull_number=int(pull_number),
                packet=prepared,
                rejection_reason=rejection_reason,
                tmpdir=tool_context.tmpdir,
                ctx=tool_context,
                run_outcome=outcome,
                verdict_diagnostic=verdict_diagnostic,
            )
        if prepared is not None:
            from mergecraft.utils.status_checks import _run_url
            from mergecraft.utils.step_summary import append_step_summary, render_step_summary

            submission = tool_context.tool_state.terminal_submission
            analyzer_run = tool_context.tool_state.analyzer_run
            outcome_label = (
                "no_verdict" if prepared.decision is None else ("success" if run_ok else "failure")
            )
            summary_body = render_step_summary(
                packet=prepared,
                outcome_label=outcome_label,
                rejection_reason=rejection_reason,
                run_url=_run_url(tool_context),
                run_outcome=outcome,
                verdict_diagnostic=verdict_diagnostic,
                analyzer_summary=analyzer_run.pre_merge_summary
                if analyzer_run is not None
                else None,
                agent_summary=submission.summary if submission is not None else None,
                trust_tier=tool_context.trust_tier,
                token_summary=_token_summary(
                    tool_context.tool_state.usage_entries,
                    budget_tracker=tool_context.budget_tracker,
                ),
            )
            append_step_summary(summary_body)

    if not emit:
        await _learnings_and_status()
        return None

    from mergecraft.tracing.tracer import get_tracer_from_settings

    if ctx.settings is None:
        msg = "settings is required when emit=True"
        raise ValueError(msg)
    if attrs_source is None:
        msg = "attrs_source is required when emit=True"
        raise ValueError(msg)
    tracer = get_tracer_from_settings(ctx.settings)
    with tracer.start_span("mergecraft.publish", attrs_source=attrs_source) as _span:
        await _learnings_and_status()
        # #39 — opt-in, off by default, and never a gate: with `sarif_upload`
        # unset this returns before making any request.
        await report_sarif_upload(tool_context)
        written = await asyncio.to_thread(
            emit_run_packet,
            tool_context,
            packet=prepared,
            verdict_prediction=verdict_prediction,
            actual_outcome=actual_outcome,
        )
        return str(written) if written else None


async def _prep_failure_reason(tool_context: ToolContext) -> str | None:
    """Return a reason string when review-relevant dependency prep failed (W6.1).

    Awaits an in-progress install before inspecting status.

    Trusted-tier ``setup_script`` failures are **not** included here. They
    resolve through ``setup_failure_policy`` (S1 / D10 — closed vocabulary
    ``inconclusive`` | ``fail`` | ``warn``) at the post-run outcome block
    in :func:`main` — see :data:`mergecraft.action.inputs.SetupFailurePolicy`
    and ``docs/config-failure-policy.md``. This helper only emits a reason
    string; the ``fail`` policy short-circuits at the run-time guard above
    (so this branch never sees a ``fail``-mapped outcome). The ``warn`` and
    ``inconclusive`` policies carry their own resolution text via
    ``tool_state.setup_hook_failure`` and are deliberately kept off this
    helper's path so prep and setup failure reasons stay distinguishable
    to the operator.
    """
    state = tool_context.tool_state.dependency_installation
    if state is None:
        return None
    if state.status == "in_progress" and state.promise is not None:
        try:
            await state.promise
        except Exception as exc:
            return f"dependency installation failed: {exc}"
    if state.status != "failed":
        return None
    reasons: list[str] = []
    for result in state.results or []:
        if is_prep_install_failure(result):
            reasons.extend(str(item) for item in result.issues)
    if reasons:
        return "; ".join(reasons)
    return "dependency installation failed"


async def _setup_run(ctx: RunContext) -> RunContext:
    """Phase 1 — prompt resolution, run context, tool state, deadline inputs (G4.2).

    Populates everything ``_resolve_credentials`` and ``_execute_agent`` need
    but does not itself touch tokens or derive trust tier — that is the
    security boundary handled entirely by ``_resolve_credentials``.
    """
    resolved_prompt = resolve_prompt_input()
    ctx.resolved_prompt = resolved_prompt
    ctx.job_token = get_job_token()
    github_client = GitHubClient(ctx.job_token)
    ctx.scm = create_github_scm(ctx.job_token, client=github_client)
    run_context = await resolve_run_context_data(github_client)
    ctx.run_context = run_context
    export_tracing_env_from_action_inputs()
    settings = apply_tracing_overrides(run_context.repo_settings)
    for tracing_warning in collect_tracing_warnings_for_summary():
        logger.warning(tracing_warning)
        gha_log.warning(tracing_warning)
    ctx.settings = settings
    from mergecraft.utils.run_bounds import BudgetTracker, resolve_run_bounds

    ctx.run_bounds = resolve_run_bounds(settings=settings)
    ctx.budget_tracker = BudgetTracker(ctx.run_bounds)

    gh_event = read_github_event()
    ctx.gh_event = gh_event

    pr_number: int | str | None = None
    if isinstance(gh_event, dict):
        pr = gh_event.get("pull_request")
        if isinstance(pr, dict) and pr.get("number") is not None:
            pr_number = pr["number"]
        else:
            issue = gh_event.get("issue")
            if (
                isinstance(issue, dict)
                and isinstance(issue.get("pull_request"), dict)
                and issue.get("number") is not None
            ):
                pr_number = issue["number"]
    ctx.pr_number = pr_number
    bind_run_context(
        run_id=os.environ.get("GITHUB_RUN_ID"),
        repo=f"{run_context.repo.owner}/{run_context.repo.name}",
        pr=pr_number,
        phase="setup",
    )

    progress = None
    if not isinstance(resolved_prompt, str) and resolved_prompt.progress_comment:
        progress = ProgressComment(
            id=resolved_prompt.progress_comment.id,
            type=resolved_prompt.progress_comment.type,
        )

    tool_state = init_tool_state(
        owner=run_context.repo.owner,
        name=run_context.repo.name,
        dir=os.getcwd(),
        progress_comment=progress,
    )
    if pr_number is not None:
        tool_state.pr_number = int(pr_number)
    ctx.tool_state = tool_state
    tmpdir = create_temp_directory()
    ctx.tmpdir = tmpdir

    if settings.env_allowlist:
        set_env_allowlist(settings.env_allowlist)

    payload = resolve_payload(resolved_prompt, settings)
    ctx.payload = payload
    tool_state.model = payload.get("model")
    tool_state.oss = run_context.oss

    # Resolve the run deadline up front so the setup-script budget can
    # be capped against it (S1 / F6 — setup must never consume the
    # whole run budget). Invalid input is captured into a sentinel
    # ``timeout_error``; the actual ``_ConfigurationError`` raise is
    # deferred until AFTER ``tool_context`` is constructed so the
    # outer handler can still call ``report_status_checks`` for the
    # ``configuration_error`` outcome (S1 review / NEW1+NEW2 —
    # building the reporting context first, then validating, prevents
    # setup from running on bad inputs while preserving completion-
    # check reporting).
    timeout_raw = payload.get("timeout")
    ctx.timeout_raw = timeout_raw
    timeout_ms: int | None
    timeout_error: str | None = None
    if timeout_raw == TIMEOUT_DISABLED:
        timeout_ms = None
    elif timeout_raw:
        usable = resolve_timeout_ms(timeout_raw)
        if usable is None:
            timeout_ms = None
            timeout_error = (
                f'invalid timeout "{timeout_raw}" '
                "(use a duration like 10m/1h or --notimeout to disable)"
            )
        else:
            timeout_ms = usable
    else:
        timeout_ms = 3_600_000
    ctx.timeout_ms = timeout_ms
    ctx.timeout_error = timeout_error

    wipe_runner_leak_surface()

    if payload.get("shell") != "enabled":
        os.environ.pop("ACTIONS_ID_TOKEN_REQUEST_URL", None)
        os.environ.pop("ACTIONS_ID_TOKEN_REQUEST_TOKEN", None)

    return ctx


async def _resolve_credentials(ctx: RunContext) -> RunContext:
    """Phase 2 — token brokering + trust-tier derivation. Behaviour-frozen (S4).

    Security boundary: token precedence (``GH_TOKEN`` > job token; App-JWT
    mint wins when configured, degrades to the job token on mint failure;
    no token anywhere fails closed) and trust-tier derivation (fail-closed
    ``untrusted`` default) must survive this extraction byte-for-byte — see
    ``tests/test_main_phases.py::test_resolve_credentials_matches_current_precedence``.
    """
    assert ctx.tool_state is not None
    assert ctx.scm is not None

    from mergecraft.action.inputs import (
        ForkCredentialInvariantError,
        validate_fork_credential_invariant,
    )
    from mergecraft.agents.codex import CODEX_SANDBOX_ENV, CODEX_SANDBOX_UNSANDBOXED
    from mergecraft.config.settings_snapshot import capture_repo_settings_snapshot
    from mergecraft.config.trust_policy import (
        agent_sandbox_manifest_fields,
        bound_head_sha,
        default_branch_from_event,
        log_trust_policy_at_run_start,
        resolve_agent_sandbox_decision,
        resolve_trust_policy,
        trust_policy_manifest_fields,
    )

    repo_root = Path.cwd()
    gh_event = ctx.gh_event or {}
    try:
        validate_fork_credential_invariant(event=gh_event, env=os.environ)
    except ForkCredentialInvariantError as exc:
        raise _ConfigurationError(str(exc)) from exc

    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    # D7 — the same ``event_name`` read below for ``resolve_trust_policy``
    # also decides whether the settings this snapshot pins are operator-owned
    # (the base ref, which only a ``pull_request_target`` run checks out
    # before ``checkout_pr`` ever runs). Every downstream reader of this
    # snapshot's provenance (tracing's D7 cap included) must consult
    # ``snapshot.operator_owned`` rather than re-deriving its own opinion of
    # the event from the ambient environment — see
    # ``mergecraft.tracing.genai._yaml_export_untrusted_for_capture`` and
    # e656debc's lesson: two independent reads of the same env var can disagree.
    operator_owned_settings = event_name == "pull_request_target"
    ctx.settings_snapshot_operator_owned = operator_owned_settings
    snapshot = capture_repo_settings_snapshot(
        root=repo_root,
        settings=ctx.settings,
        operator_owned=operator_owned_settings,
    )
    shell = str(ctx.payload.get("shell") or "restricted")
    policy = resolve_trust_policy(
        event=gh_event,
        config_root=repo_root,
        event_name=event_name,
        settings_snapshot=snapshot,
        shell=shell,
    )
    log_trust_policy_at_run_start(policy)

    operator_override_requested = (
        os.environ.get(CODEX_SANDBOX_ENV, "").strip().lower() == CODEX_SANDBOX_UNSANDBOXED
    )
    sandbox_decision = resolve_agent_sandbox_decision(
        event=gh_event,
        event_name=event_name,
        config_root=repo_root,
        settings_snapshot=snapshot,
        head_sha=bound_head_sha(gh_event, event_name=event_name) or "unknown",
        default_branch=default_branch_from_event(gh_event),
        operator_override_requested=operator_override_requested,
    )

    trust_tier = policy.execution_trust
    authority_trust = policy.authority_trust
    ctx.trust_tier = trust_tier
    ctx.authority_trust = authority_trust
    ctx.trust_self_review_level = policy.level
    ctx.tool_state.trust_tier = trust_tier
    ctx.tool_state.authority_trust = authority_trust
    ctx.tool_state.trust_self_review_level = policy.level
    ctx.tool_state.agent_sandbox_decision = sandbox_decision
    ctx.tool_state.run_manifest_trust = {
        **trust_policy_manifest_fields(policy),
        **agent_sandbox_manifest_fields(sandbox_decision),
    }

    assert ctx.settings is not None
    from mergecraft.config.settings import (
        apply_trust_tier_to_repo_settings,
        build_executable_config_skip_reason,
    )

    event_name = os.environ.get("GITHUB_EVENT_NAME", "unknown")
    settings, drops = apply_trust_tier_to_repo_settings(
        ctx.settings,
        trust_tier,
        source_label=f"{event_name} event",
    )
    ctx.settings = settings
    from mergecraft.enterprise.runtime import bind_enterprise_after_trust

    bind_enterprise_after_trust(settings, trust_tier)
    if drops:
        for reason in drops.values():
            logger.warning("» {}", reason)
        skip_reason = build_executable_config_skip_reason(drops)
        if skip_reason:
            ctx.setup_script_skip_reason = skip_reason
            ctx.tool_state.setup_script_skip_reason = skip_reason

    token_ref = await resolve_tokens(
        push=ctx.payload.get("push") or "restricted", xrepo=ctx.payload.get("xrepo")
    )
    ctx.token_ref = token_ref
    # Prefer MCP token for API calls
    await ctx.scm.aclose()
    ctx.scm = create_github_scm(token_ref.mcp_token, client=GitHubClient(token_ref.mcp_token))

    return ctx


def _stamp_requested_model(ctx: RunContext, payload_model: object) -> None:
    """Record the chain head as the requested model (W10.2) and reset fallback bookkeeping.

    Split out of ``_assemble_model_chain`` (G4.2) purely to keep that
    function's complexity down — this is the tail of the same original
    contiguous block, called immediately after agent/model resolution.
    """
    assert ctx.tool_state is not None
    tool_state = ctx.tool_state
    # W10.2 — record the chain head as the requested model so the packet
    # can prove requested vs executed even when selection skipped ahead.
    if ctx.chain_for_decision:
        tool_state.requested_model = ctx.chain_for_decision[0]
    elif ctx.selected_slug:
        tool_state.requested_model = ctx.selected_slug
    elif isinstance(payload_model, str) and payload_model.strip():
        tool_state.requested_model = payload_model.strip()
    else:
        tool_state.requested_model = tool_state.model
    tool_state.fallback_index = 0
    tool_state.fallback_occurred = False


async def _assemble_model_chain(ctx: RunContext) -> None:
    """Model-chain assembly: resolve cwd, the effective chain, and the running agent.

    Local extraction out of ``_execute_agent`` (G4.2) — no behaviour change,
    only a name for this contiguous block of the original body.
    """
    assert ctx.settings is not None
    assert ctx.tool_state is not None
    settings = ctx.settings
    tool_state = ctx.tool_state
    payload = ctx.payload

    cwd = payload.get("cwd")
    if cwd:
        resolved_cwd = resolve_allowed_working_directory(cwd, default=os.getcwd())
        if os.getcwd() != resolved_cwd:
            os.chdir(resolved_cwd)

    payload_model = payload.get("model")
    # #37 / W4 / D8 — ``model_pin`` opts into the legacy "use exactly this
    # model" semantics: when True, ``model:`` collapses the chain to a
    # single entry. Default is chain-preserving — the supplied ``model:``
    # becomes the head of the effective chain and the configured ``models:``
    # tail follows. ``modelExplicit`` is retained as a back-compat alias
    # for the legacy pin signal so any consumer that branched on it still
    # behaves the same.
    model_pin = bool(
        payload.get("modelPin") or payload.get("modelExplicit")  # legacy alias
    )
    model_head = payload.get("modelHead") or (
        payload_model if isinstance(payload_model, str) else None
    )
    chain_for_decision = effective_model_chain(settings=settings, head=model_head, pin=model_pin)
    # ``use_model_chain`` is true whenever an effective chain has more
    # than one entry OR the operator asked for the chain explicitly. The
    # legacy ``not model_explicit`` short-circuit is gone — a supplied
    # ``model:`` no longer disables the chain.
    use_model_chain = len(chain_for_decision) > 1 or (
        bool(chain_for_decision) and model_head is not None and not model_pin
    )
    ctx.model_pin = model_pin
    ctx.model_head = model_head
    ctx.chain_for_decision = chain_for_decision
    ctx.use_model_chain = use_model_chain
    selected_slug: str | None

    if use_model_chain:
        _first_runnable_in_chain.allow_fallback = settings.allow_fallback  # type: ignore[attr-defined]  # — allow_fallback is a runtime attribute added to the function object for chain control
        selected_slug = _first_runnable_in_chain(chain_for_decision)
        if not selected_slug:
            msg = "no runnable model slug in chain — configure credentials for at least one entry"
            raise RuntimeError(msg)
        resolved_model = resolve_model(slug=selected_slug, respect_env_override=False)
    else:
        # Single-entry chain (or pin opt-in). The chain is collapsed to
        # exactly ``[model_head]`` when pinned; otherwise it is just the
        # first configured entry. Honour ``respect_env_override=False``
        # when the operator named a model explicitly — the action input
        # already wins.
        only_slug = (
            model_head if model_pin else (chain_for_decision[0] if chain_for_decision else None)
        )
        resolved_model = resolve_model(slug=only_slug, respect_env_override=False)
        selected_slug = only_slug
    agent = resolve_runtime_agent(model=resolved_model, settings=settings)
    agent_id = agent.name
    ctx.agent = agent
    ctx.agent_id = agent_id
    ctx.resolved_model = resolved_model
    ctx.selected_slug = selected_slug
    tool_state.model = payload.get("proxyModel") or resolved_model or payload.get("model")

    from mergecraft.utils.agent_resolve import collect_roster_credential_degradations

    degradations = collect_roster_credential_degradations(
        settings=settings,
        cwd=Path.cwd(),
    )
    if degradations:
        tool_state.credential_degradations = degradations
        for line in degradations:
            logger.warning("» {}", line)
        tool_state.run_manifest_trust = {
            **tool_state.run_manifest_trust,
            "credential_degradations": " | ".join(degradations),
        }

    _stamp_requested_model(ctx, payload_model)


async def _build_run_tool_context(ctx: RunContext) -> None:
    """Build ``tool_context`` — modes, output schema, analyzers mode, SARIF flag (S1/F3+F4).

    Built BEFORE the equal-deadline guard and the fail-policy short-circuit
    (both later, in ``_execute_agent``) so the outer handler can still call
    ``report_status_checks`` when those guards raise ``_ConfigurationError``.
    The MCP server URL is blank here; ``_prepare_agent_dispatch`` fills it
    in once ``start_mcp_http_server`` runs.
    """
    assert ctx.settings is not None
    assert ctx.run_context is not None
    assert ctx.tool_state is not None
    assert ctx.scm is not None
    assert ctx.token_ref is not None
    assert ctx.tmpdir is not None

    settings = ctx.settings
    run_context = ctx.run_context
    tool_state = ctx.tool_state
    token_ref = ctx.token_ref
    payload = ctx.payload

    modes = [
        *compute_modes(ctx.agent_id, settings.signed_commits),
        *_custom_modes(settings.modes),
    ]
    tool_state.modes = modes
    ctx.modes = modes
    output_schema = resolve_output_schema()
    ctx.output_schema = output_schema

    ctx_payload = _payload_to_ctx(payload)
    ctx.ctx_payload = ctx_payload
    analyzers_mode = resolve_analyzers_mode(os.environ.get("INPUT_ANALYZERS"))
    ctx.analyzers_mode = analyzers_mode
    sarif_upload_enabled = resolve_sarif_upload_enabled(
        action_input=os.environ.get("INPUT_SARIF_UPLOAD"),
        repo_setting=settings.analyzers.sarif_upload,
    )
    ctx.sarif_upload_enabled = sarif_upload_enabled
    from mergecraft.mcp.tool_state import primary_repo_state

    ctx.tool_context = ToolContext(
        agent_id=ctx.agent_id,
        repo=RepoIdentity(owner=run_context.repo.owner, name=run_context.repo.name),
        payload=ctx_payload,
        scm=ctx.scm,
        github=github_client_from_scm(ctx.scm),
        github_installation_token=token_ref.mcp_token,
        git_token=token_ref.git_token,
        api_token=run_context.api_token,
        modes=modes,
        tool_state=tool_state,
        mcp_server_url="",
        tmpdir=ctx.tmpdir,
        refresh_git_token=token_ref.refresh_git_token,
        read_token=token_ref.read_token,
        xrepo=payload.get("xrepo"),
        prepush_script=settings.prepush_script,
        pr_approve_enabled=settings.pr_approve_enabled,
        auto_merge_enabled=settings.auto_merge_enabled,
        signed_commits=settings.signed_commits,
        mode_instructions=settings.mode_instructions,
        static_checks=[
            StaticCheckConfig(
                name=check.name,
                command=check.command,
                suffixes=tuple(check.suffixes),
            )
            for check in settings.static_checks
        ],
        static_checks_enabled=(
            ctx_payload.shell != "disabled" and allow_repo_command_overrides(ctx.trust_tier)
        ),
        ci_gate_checks=dict(settings.ci_evidence.gates),
        ci_sarif_artifacts=list(settings.ci_evidence.sarif_artifacts),
        analyzers_mode=analyzers_mode,
        trust_tier=ctx.trust_tier,
        authority_trust=ctx.authority_trust,
        analyzers_settings_enabled=settings.analyzers.enabled,
        sarif_upload_enabled=sarif_upload_enabled,
        run_id=int(os.environ["GITHUB_RUN_ID"]) if os.environ.get("GITHUB_RUN_ID") else None,
        job_id=os.environ.get("GITHUB_JOB"),
        oss=run_context.oss,
        plan="unknown",
        resolved_model=ctx.resolved_model,
        suggest_eval_add=bool(payload.get("suggestEvalAdd")),
        budget_tracker=ctx.budget_tracker,
    )
    from mergecraft.config.settings_snapshot import capture_run_scope_snapshot

    snapshot = capture_run_scope_snapshot(
        ctx.tool_context,
        root=Path(primary_repo_state(tool_state).dir),
        settings=settings,
        load_learnings_files=False,
        operator_owned=ctx.settings_snapshot_operator_owned,
    )
    from mergecraft.review.roster_auth import (
        RosterAuthError,
        RosterSecretEmptyError,
        validate_roster_at_run_start,
    )

    try:
        validate_roster_at_run_start(snapshot=snapshot)
    except (RosterAuthError, RosterSecretEmptyError) as exc:
        raise _ConfigurationError(str(exc)) from exc


async def _apply_overrides_and_setup_git(ctx: RunContext) -> None:
    """Apply setup-input overrides, re-raise a captured bad ``timeout``, run ``setup_git``.

    Both run AFTER ``tool_context`` exists (S1 review / NEW1) so the outer
    handler can still call ``report_status_checks`` for the
    ``configuration_error`` outcome, but BEFORE
    ``asyncio.create_subprocess_shell`` so a bad value never triggers the
    setup script to run.
    """
    assert ctx.settings is not None
    assert ctx.run_context is not None
    assert ctx.tool_state is not None
    assert ctx.token_ref is not None
    assert ctx.tmpdir is not None
    assert ctx.scm is not None

    try:
        settings = apply_setup_overrides(ctx.settings)
    except ValueError as exc:
        raise _ConfigurationError(str(exc)) from None
    ctx.settings = settings

    # S1 review / NEW1 — re-raise the captured bad-``timeout`` sentinel now
    # that ``tool_context`` exists. The input parsing already classified
    # the input as bad earlier (``_setup_run``); this only fires the guard
    # so a ``--notimeout`` / unset input still resolves to ``None`` /
    # ``3_600_000`` without firing.
    if ctx.timeout_error is not None:
        raise _ConfigurationError(ctx.timeout_error) from None

    await asyncio.to_thread(
        setup_git,
        git_token=ctx.token_ref.git_token,
        owner=ctx.run_context.repo.owner,
        name=ctx.run_context.repo.name,
        tool_state=ctx.tool_state,
        shell=ctx.payload.get("shell") or "restricted",
        tmpdir=ctx.tmpdir,
        octokit=github_client_from_scm(ctx.scm),
    )


async def _run_setup_script_phase(ctx: RunContext) -> None:
    """Run (or skip) the trusted-tier ``setup_script`` inside its wall-clock budget (S1/F6).

    The action-input resolver already bounds the upper end
    (``DEFAULT_SETUP_TIMEOUT_S`` = 10 m); the *only* cross-budget constraint
    is that ``setup_timeout_s`` be strictly less than the run timeout, so a
    failed setup script cannot be masked by an agent timeout (S1 review /
    F3 follow-up — equal-or-larger setup budgets let the setup script
    consume the entire run deadline, after which the agent budget is
    clamped to ~1 ms and the failure surfaces as ``_AgentTimeoutError``
    (``timed_out``) instead of the ``configuration_error`` /
    ``inconclusive`` the setup policy was supposed to produce). Only
    checked when a setup script is actually configured and a run timeout
    is in scope.
    """
    assert ctx.settings is not None
    assert ctx.tool_state is not None
    settings = ctx.settings
    tool_state = ctx.tool_state

    configured_setup_timeout_s = settings.setup_timeout_s
    timeout_ms = ctx.timeout_ms
    if (
        settings.setup_script
        and timeout_ms is not None
        and configured_setup_timeout_s * 1000 >= timeout_ms
    ):
        raise _ConfigurationError(
            f"setup_timeout ({configured_setup_timeout_s}s) must be less than the run "
            f"timeout ({timeout_ms // 1000}s) so a failed setup script is not "
            f"masked as an agent timeout"
        )
    setup_timeout_s = configured_setup_timeout_s
    ctx.setup_timeout_s = setup_timeout_s

    setup_script_skip_reason = ""
    setup_hook_failure = ""
    setup_started_at = time.monotonic()
    if settings.setup_script:
        if ctx.trust_tier == "trusted":
            logger.info("» running setup script")
            proc = await asyncio.create_subprocess_shell(
                settings.setup_script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,  # F6 — session leader so killpg reaches grandchildren
            )
            register_process_group(proc.pid)
            try:
                _out, err = await asyncio.wait_for(proc.communicate(), timeout=setup_timeout_s)
            except TimeoutError:
                # F6 — TERM → grace → KILL the whole tree (convention 9).
                kill_process_group(proc.pid)
                setup_hook_failure = f"setup script timed out after {setup_timeout_s}s"
            else:
                if proc.returncode != 0:
                    # S1 review / NEW3 — redact the full stderr text
                    # BEFORE truncating to 500 chars. Truncating first
                    # can lop a ``ghp_…`` token below the redactor's
                    # pattern minimum length, leaving a partial prefix
                    # in the prompt — redaction must run on the whole
                    # input so the pattern matches and the slice is
                    # taken from the *redacted* output.
                    detail = redact_secrets((err or b"").decode(errors="replace"))[:500]
                    setup_hook_failure = f"setup script failed (exit {proc.returncode}): {detail}"
            finally:
                unregister_process_group(proc.pid)
            if setup_hook_failure:
                tool_state.setup_hook_failure = setup_hook_failure
                logger.warning("» {}", setup_hook_failure)
        else:
            event_name = os.environ.get("GITHUB_EVENT_NAME", "unknown")
            setup_script_skip_reason = (
                f"skipped setup_script on untrusted tier ({event_name} event)"
            )
            tool_state.setup_script_skip_reason = setup_script_skip_reason
            logger.warning("» {}", setup_script_skip_reason)
    setup_elapsed_s = time.monotonic() - setup_started_at
    ctx.setup_hook_failure = setup_hook_failure
    if setup_script_skip_reason:
        ctx.setup_script_skip_reason = setup_script_skip_reason
    ctx.setup_elapsed_s = setup_elapsed_s


async def _prepare_agent_dispatch(ctx: RunContext) -> None:
    """Start the MCP server, seed learnings/skills, resolve instructions, build ``run_ctx``.

    ``tool_context``, ``modes``, ``output_schema``, ``ctx_payload``,
    ``analyzers_mode`` and ``sarif_upload_enabled`` were all built earlier
    in ``_build_run_tool_context`` — before the equal-deadline guard and
    the fail-policy short-circuit in ``_execute_agent`` — so the outer
    handler can still call ``report_status_checks`` when those guards
    raise ``_ConfigurationError``. The MCP server URL is filled in here.
    """
    assert ctx.tool_context is not None
    assert ctx.settings is not None
    assert ctx.run_context is not None
    assert ctx.tool_state is not None
    assert ctx.tmpdir is not None

    tool_context = ctx.tool_context
    settings = ctx.settings
    run_context = ctx.run_context
    tool_state = ctx.tool_state
    payload = ctx.payload
    tmpdir = ctx.tmpdir

    mcp_url, stop_mcp = start_mcp_http_server(tool_context, output_schema=ctx.output_schema)
    tool_context.mcp_server_url = mcp_url
    ctx.mcp_url = mcp_url
    ctx.stop_mcp = stop_mcp
    _reviewer_mcp_url = mcp_role_url(mcp_url, None)
    logger.info("» MCP server started at {}", mcp_url)

    subagent_denied = subagent_denied_tool_names(tool_context, ctx.output_schema)
    ctx.subagent_denied = subagent_denied
    verifier_denied = verifier_denied_tool_names(tool_context, ctx.output_schema)
    ctx.verifier_denied = verifier_denied

    try:
        learnings_path = await seed_learnings_file(tmpdir=tmpdir, current=settings.learnings)
        tool_state.learnings_file_path = learnings_path
        tool_state.learnings_seed = (settings.learnings or "").strip()
        # D10 / W6.5 — wire the opt-in auto-promote flag from
        # ``RepoSettings`` into ``tool_state`` so ``persist_learnings``
        # honors it. Default is fail-closed (staging only); setting
        # ``autopromoteLearnings: true`` restores legacy behaviour for
        # trusted maintainer authors (see ``utils/learnings.py``).
        tool_state.autopromote_learnings = settings.autopromote_learnings
        logger.info(
            "» learnings seeded at {} (existing={})",
            learnings_path,
            "yes" if settings.learnings else "no",
        )
    except Exception as exc:
        logger.warning("» learnings seed failed: {} — continuing without learnings file", exc)

    if payload.get("xrepo"):
        try:
            xrepo_path = await seed_xrepo_learnings_file(
                tmpdir=tmpdir, current=settings.xrepo_learnings
            )
            tool_state.xrepo_learnings_file_path = xrepo_path
            tool_state.xrepo_learnings_seed = (settings.xrepo_learnings or "").strip()
        except Exception as exc:
            logger.warning("» xrepo learnings seed failed: {}", exc)

    start_installation(tool_context)

    # Install bundled skills into a fake HOME under tmpdir
    skills_home = os.path.join(tmpdir, "home")
    os.makedirs(skills_home, exist_ok=True)
    try:
        install_bundled_skills(home=skills_home)
    except Exception as exc:
        logger.warning("» bundled skills install failed: {}", exc)

    instructions = resolve_instructions(
        payload=payload,
        repo=run_context.repo,
        modes=ctx.modes,
        agent_id=ctx.agent_id,
        output_schema=ctx.output_schema,
        signed_commits=settings.signed_commits,
        learnings_file_path=tool_state.learnings_file_path,
        learnings_headings=settings.learnings_headings,
        setup_hook_failure=ctx.setup_hook_failure,
        setup_script_skip_reason=ctx.setup_script_skip_reason,
        xrepo_brief=settings.xrepo_brief,
        xrepo_learnings_file_path=tool_state.xrepo_learnings_file_path,
        xrepo_learnings_headings=settings.xrepo_learnings_headings,
    )
    ctx.instructions = instructions
    logger.info("Using agent={} model={}", ctx.agent_id, ctx.resolved_model or "(auto)")

    ctx.run_ctx = AgentRunContext(
        payload=payload,
        mcp_server_url=_reviewer_mcp_url,
        mcp_auth_token=tool_context.mcp_auth_token,
        tmpdir=tmpdir,
        subagent_denied_tools=subagent_denied,
        verifier_denied_tools=verifier_denied,
        instructions=instructions,
        tool_state=tool_state,
        api_token=run_context.api_token,
        resolved_model=ctx.resolved_model,
        stop_script=settings.stop_script,
    )


def _promote_and_finalize_agent_result(
    ctx: RunContext, winning_slug: str | None, result: AgentResult
) -> AgentResult:
    """Post-process the dispatched ``AgentResult``: model promotion, usage, schema check.

    Split out of ``_dispatch_agent_with_deadline`` (G4.2) purely to keep
    that function's complexity down — this is the tail of the same
    original contiguous block, called immediately after the agent task
    resolves (whether via the plain await or the deadline-wrapped one).
    """
    assert ctx.tool_state is not None
    assert ctx.tool_context is not None
    tool_state = ctx.tool_state
    tool_context = ctx.tool_context
    payload = ctx.payload
    chain_for_decision = ctx.chain_for_decision
    output_schema = ctx.output_schema

    if winning_slug:
        resolved_model = resolve_model(slug=winning_slug, respect_env_override=False)
        tool_context.resolved_model = resolved_model
        ctx.resolved_model = resolved_model
        # W10.2/W10.3 — single promotion path; chain stamps metadata in
        # ``_attach_model_evidence``, single-slug defaults to index 0.
        meta = result.metadata or {}
        requested_meta = meta.get("requested_model")
        requested = (
            requested_meta.strip()
            if isinstance(requested_meta, str) and requested_meta.strip()
            else (chain_for_decision[0] if chain_for_decision else tool_state.requested_model)
        )
        fallback_raw = meta.get("fallback_index")
        fallback_index = fallback_raw if isinstance(fallback_raw, int) else 0
        executed = payload.get("proxyModel") or resolved_model or winning_slug
        promote_model_evidence(
            tool_state,
            requested_model=requested,
            executed_model=executed if isinstance(executed, str) else winning_slug,
            fallback_index=fallback_index,
        )

    if result.usage:
        tool_state.usage_entries.append(result.usage)
        from mergecraft.utils.run_bounds import BudgetExhausted, record_agent_usage

        try:
            record_agent_usage(ctx.budget_tracker, result.usage, phase="reviewer_dispatch")
        except BudgetExhausted as exc:
            ctx.budget_exhaustion = exc

    if output_schema and not tool_state.output and result.success:
        msg = (
            "output_schema was provided but agent did not call set_output — "
            "structured output is required"
        )
        raise RuntimeError(msg)

    return result


async def _run_agent_task_with_deadline(ctx: RunContext) -> tuple[str | None, AgentResult]:
    """Dispatch the agent (or model chain) as a task and await it under the deadline.

    ``timeout_ms`` / ``timeout_raw`` were resolved up front in
    ``_setup_run`` (right after ``payload = resolve_payload(...)``) so the
    setup-script budget could be capped against the run deadline (S1 /
    F6). The ``--notimeout`` / ``none`` escape and the fail-closed
    validation both happened there; this just spends the resolved values.
    """
    assert ctx.settings is not None
    assert ctx.run_context is not None
    assert ctx.tool_state is not None
    assert ctx.tool_context is not None
    assert ctx.run_ctx is not None
    assert ctx.agent is not None

    settings = ctx.settings
    run_context = ctx.run_context
    tool_state = ctx.tool_state
    tool_context = ctx.tool_context
    run_ctx = ctx.run_ctx
    payload = ctx.payload
    agent = ctx.agent
    agent_id = ctx.agent_id
    model_head = ctx.model_head
    model_pin = ctx.model_pin
    use_model_chain = ctx.use_model_chain
    selected_slug = ctx.selected_slug
    output_schema = ctx.output_schema
    setup_hook_failure = ctx.setup_hook_failure
    setup_script_skip_reason = ctx.setup_script_skip_reason

    async def _run_agent_once(slug: str) -> AgentResult:
        attempt_model = resolve_model(slug=slug, respect_env_override=False)
        attempt_agent = resolve_runtime_agent(model=attempt_model, settings=settings)
        attempt_agent_id = attempt_agent.name

        if attempt_agent_id == agent_id:
            attempt_ctx = replace(run_ctx, resolved_model=attempt_model)
        else:
            attempt_modes = [
                *compute_modes(attempt_agent_id, settings.signed_commits),
                *_custom_modes(settings.modes),
            ]
            attempt_instructions = resolve_instructions(
                payload=payload,
                repo=run_context.repo,
                modes=attempt_modes,
                agent_id=attempt_agent_id,
                output_schema=output_schema,
                signed_commits=settings.signed_commits,
                learnings_file_path=tool_state.learnings_file_path,
                learnings_headings=settings.learnings_headings,
                setup_hook_failure=setup_hook_failure,
                setup_script_skip_reason=setup_script_skip_reason,
                xrepo_brief=settings.xrepo_brief,
                xrepo_learnings_file_path=tool_state.xrepo_learnings_file_path,
                xrepo_learnings_headings=settings.xrepo_learnings_headings,
            )
            attempt_denied = subagent_denied_tool_names(
                replace(tool_context, agent_id=attempt_agent_id),
                output_schema,
            )
            attempt_verifier_denied = verifier_denied_tool_names(
                replace(tool_context, agent_id=attempt_agent_id),
                output_schema,
            )
            attempt_ctx = replace(
                run_ctx,
                resolved_model=attempt_model,
                instructions=attempt_instructions,
                subagent_denied_tools=attempt_denied,
                verifier_denied_tools=attempt_verifier_denied,
            )
            tool_context.agent_id = attempt_agent_id
            tool_context.modes = attempt_modes
            tool_state.modes = attempt_modes
            tool_context.resolved_model = attempt_model
            logger.info(
                "» model chain advanced to agent={} model={}",
                attempt_agent_id,
                attempt_model or "(auto)",
            )
        # O8/D10 (OB4) — issue the per-agent identity at dispatch: the span
        # carries it and ``spawn_agent_cli`` exports it as
        # ``MERGECRAFT_AGENT_ID`` so the MCP server can attribute this
        # agent's tool calls.
        from mergecraft.review.lens_routing import lens_id_from_agent_id
        from mergecraft.tracing import get_tracer_from_settings
        from mergecraft.tracing.signals import agent_run_span

        with agent_run_span(
            get_tracer_from_settings(settings),
            agent_id=str(attempt_agent_id),
            role="reviewer",
            lens=lens_id_from_agent_id(str(attempt_agent_id)),
            executed_model=attempt_model,
        ):
            result = await attempt_agent.run(attempt_ctx)
        from mergecraft.mcp.tool_state import append_dispatched_lens

        append_dispatched_lens(tool_state, str(attempt_agent_id))
        return result

    async def _dispatch_selected_agent() -> tuple[str | None, AgentResult]:
        if use_model_chain:
            winning_slug, chain_result = await run_with_model_chain(
                settings=settings,
                run_once=_run_agent_once,
                head=model_head,
                pin=model_pin,
                tool_state=tool_state,
            )
            return winning_slug, chain_result
        from mergecraft.review.lens_routing import lens_id_from_agent_id
        from mergecraft.tracing import get_tracer_from_settings
        from mergecraft.tracing.signals import agent_run_span

        with agent_run_span(
            get_tracer_from_settings(settings),
            agent_id=str(agent.name),
            role="reviewer",
            lens=lens_id_from_agent_id(str(agent.name)),
            executed_model=ctx.resolved_model,
        ):
            result = await agent.run(run_ctx)
        from mergecraft.mcp.tool_state import append_dispatched_lens

        append_dispatched_lens(tool_state, str(agent.name))
        return selected_slug, result

    agent_task = asyncio.create_task(_dispatch_selected_agent())

    # S1 / F6 — deduct the setup-script elapsed time from the agent
    # deadline. A slow setup must NOT silently extend the total run
    # deadline. ``setup_elapsed_s`` is the wall-clock duration measured
    # by the bounded setup block above; ``timeout_ms`` is the
    # pre-deduction run budget.
    timeout_ms = ctx.timeout_ms
    setup_elapsed_s = ctx.setup_elapsed_s
    agent_timeout_ms: int | None
    if timeout_ms is None:
        agent_timeout_ms = None
    else:
        agent_timeout_ms = max(1, int(timeout_ms - setup_elapsed_s * 1000))
        if agent_timeout_ms != timeout_ms:
            logger.info(
                "» deducted setup elapsed {:.2f}s from agent deadline ({}s -> {}s)",
                setup_elapsed_s,
                timeout_ms / 1000,
                agent_timeout_ms / 1000,
            )

    if agent_timeout_ms is None:
        winning_slug, result = await agent_task
    else:
        try:
            winning_slug, result = await asyncio.wait_for(
                agent_task, timeout=agent_timeout_ms / 1000.0
            )
        except TimeoutError:
            agent_task.cancel()
            kill_all_active_process_groups()
            msg = f"agent run timed out after {ctx.timeout_raw or '1h'}"
            raise _AgentTimeoutError(msg) from None

    return winning_slug, result


async def _dispatch_agent_with_deadline(ctx: RunContext) -> AgentResult:
    """Run the agent (or model chain) under the deadline, then post-process the result.

    Orchestrates the two sub-steps of the original phase body: dispatch +
    deadline (``_run_agent_task_with_deadline``) and result post-processing
    (``_promote_and_finalize_agent_result``) — each a named local
    extraction (G4.2), no behaviour change.
    """
    winning_slug, result = await _run_agent_task_with_deadline(ctx)
    return _promote_and_finalize_agent_result(ctx, winning_slug, result)


async def _run_review_after_analyze(ctx: RunContext) -> AgentResult | SkipAgentReview:
    """Setup script, MCP start, and payload-timed agent dispatch (review stage)."""
    await _apply_overrides_and_setup_git(ctx)
    assert ctx.tool_context is not None
    await ingest_ci_sarif_from_action_env(
        ctx.tool_context,
        ctx.gh_event or {},
        event_name=os.environ.get("GITHUB_EVENT_NAME", ""),
    )
    await _run_setup_script_phase(ctx)

    # Plan 12 B5 — run-record setup reasons must also appear outside any open group.
    if ctx.setup_hook_failure:
        gha_log.warning(ctx.setup_hook_failure)

    assert ctx.settings is not None

    # S1 review / F4 + S1 review / N2 — the policy decides whether a
    # trusted-tier ``setup_script`` failure short-circuits *before* the
    # agent loop. ``fail`` aborts (existing F4 behaviour); ``inconclusive``
    # (N2 fix) skips the agent and runs the publish block with outcome
    # ``inconclusive`` so no review/mutation tool is invoked; ``warn``
    # falls through to the late outcome block in ``_finalize``. Pre-N2 the
    # ``inconclusive`` branch ran the agent first and only then rewrote the
    # outcome — letting the agent post reviews / push branches on an
    # under-provisioned tree.
    sc_action, sc_payload = _short_circuit_setup_failure(
        ctx.setup_hook_failure, ctx.settings.setup_failure_policy
    )
    if sc_action == "abort":
        assert isinstance(sc_payload, _ConfigurationError)
        logger.warning(
            "» setup script failure under fail policy — aborting before agent runs: {}",
            ctx.setup_hook_failure,
        )
        raise sc_payload
    if sc_action == "skip_agent":
        assert isinstance(sc_payload, str)
        skip_reason = sc_payload
        logger.warning(
            "» setup script failure under inconclusive policy — skipping agent "
            "loop to honour no-verdict: {}",
            skip_reason,
        )
        # Engine publish (``_finalize``) owns completion; do not publish here.
        return SkipAgentReview(reason=skip_reason)

    with gha_log.group("agent-dispatch"):
        await _prepare_agent_dispatch(ctx)
        return await _dispatch_agent_with_deadline(ctx)


async def _finalize(ctx: RunContext, result: AgentResult | SkipAgentReview) -> MainResult:
    """Phase 4 — post-run, publish, outcome mapping (G4.2)."""
    assert ctx.tool_context is not None
    assert ctx.tool_state is not None
    assert ctx.settings is not None

    tool_context = ctx.tool_context
    tool_state = ctx.tool_state
    settings = ctx.settings

    if isinstance(result, SkipAgentReview):
        agent_result = AgentResult(success=True)
    else:
        agent_result = result
        if ctx.run_ctx is not None:
            try:
                agent_result = await finalize_agent_result(ctx.run_ctx, agent_result)
            except Exception as exc:
                logger.debug("post-run finalize skipped: {}", exc)

    # D3/W5.2 + W6.1 + S1/D5/D10 — a completed run is ``passed`` / ``failed``,
    # ``inconclusive`` when review-relevant dependency prep failed OR a
    # trusted-tier ``setup_script`` failed under the default policy, or
    # ``configuration_error`` when the operator opted into ``fail``. Agent
    # failure wins over both prep and setup-script failure (the agent
    # genuinely couldn't do its job). S1 also adds D10's
    # ``setup_failure_policy`` to the resolution.
    prep_reason = await _prep_failure_reason(tool_context)
    setup_reason = tool_state.setup_hook_failure or ""
    if ctx.budget_tracker is not None:
        ctx.run_bounds = ctx.budget_tracker.bounds
    outcome: RunOutcome
    failure_reason: str | None
    if ctx.budget_exhaustion is not None:
        from mergecraft.utils.run_bounds import budget_exhaustion_outcome

        outcome = budget_exhaustion_outcome(ctx.budget_exhaustion)
        failure_reason = str(ctx.budget_exhaustion)
    elif (
        ctx.budget_tracker is not None
        and getattr(ctx.budget_tracker, "last_exhausted", None) is not None
    ):
        # D12 / PR #242 finding ``aeb5d964c1d35e5a41784ded`` — tool-call
        # budget exhaustion surfaces only from the MCP ``tools/call`` handler
        # (which catches ``BudgetExhausted`` to return a JSON-RPC error). The
        # tracker itself records the exception, so the orchestrator still
        # tags the run ``inconclusive`` at finalize time rather than
        # approving on a partial signal.
        from mergecraft.utils.run_bounds import budget_exhaustion_outcome

        outcome = budget_exhaustion_outcome(ctx.budget_tracker.last_exhausted)
        failure_reason = str(ctx.budget_tracker.last_exhausted)
    else:
        outcome, failure_reason = _classify_outcome(
            result=agent_result,
            setup_reason=setup_reason,
            setup_policy=settings.setup_failure_policy,
            prep_reason=prep_reason,
            mode=tool_state.selected_mode,
            verdict_protocol=settings.gates.terminal_verdict,
            final_summary_written=tool_state.final_summary_written,
            terminal_publication_failed=tool_state.terminal_publication_failed,
        )
    verdict_publish = _verdict_protocol_publish(
        result=agent_result,
        mode=tool_state.selected_mode,
        setup_reason=setup_reason,
        setup_policy=settings.setup_failure_policy,
        prep_reason=prep_reason,
        final_summary_written=tool_state.final_summary_written,
        terminal_verdict=settings.gates.terminal_verdict,
        terminal_publication_failed=tool_state.terminal_publication_failed,
    )
    diagnostic_attrs = verdict_publish.attrs
    verdict_prediction = verdict_publish.prediction
    verdict_diagnostic_code = verdict_publish.diagnostic

    selected_mode_obj = next(
        (m for m in tool_context.modes if m.name == tool_context.tool_state.selected_mode),
        None,
    )
    packet_path = await _publish(
        ctx,
        outcome=outcome,
        failure_reason=failure_reason,
        attrs_source=lambda: _publish_span_attrs(outcome, selected_mode_obj) | diagnostic_attrs,
        verdict_prediction=verdict_prediction,
        actual_outcome=str(outcome) if verdict_prediction is not None else None,
        verdict_diagnostic=verdict_diagnostic_code,
    )

    # O9 (OB4) — the verdict span at the publish convergence point. Emitted
    # only when the agent actually submitted a terminal verdict: a run that
    # never submitted has no verdict, and the missing span is the signal
    # (the same diagnostic philosophy as the phase spans). The disagreement
    # flag is derived by the emitter, never supplied here.
    submission = tool_state.terminal_submission
    if submission is not None:
        try:
            from mergecraft.tracing import get_tracer_from_settings
            from mergecraft.tracing.signals import emit_verdict

            fallback_reason = (agent_result.metadata or {}).get("fallback_reason")
            published_count = len(submission.findings)
            emit_verdict(
                get_tracer_from_settings(settings),
                agent_verdict=submission.verdict,
                structural_verdict="pass" if outcome is RunOutcome.passed else "fail",
                published_count=published_count,
                # Withdrawn ≈ proposed by the agent but not published.
                withdrawn_count=max(len(tool_state.agent_findings) - published_count, 0),
                fallback_reason=str(fallback_reason) if fallback_reason else None,
            )
        except Exception as exc:
            logger.debug("verdict span emission skipped: {}", exc)

    if outcome is not RunOutcome.passed:
        return MainResult(
            success=False,
            error=failure_reason or agent_result.error or "agent execution failed",
            evidence_packet_path=packet_path,
            outcome=outcome,
            verdict_diagnostic=verdict_diagnostic_code,
        )

    output = tool_state.output or agent_result.output
    return MainResult(
        success=True,
        output=output,
        result=output,
        evidence_packet_path=packet_path,
        outcome=outcome,
        verdict_diagnostic=verdict_diagnostic_code,
    )


def _action_review_context() -> ReviewContext:
    """Build the run's ``ReviewContext`` from the Actions environment (OB1/O1).

    Resolved from the same env correlation fields the tracer baseline uses,
    so both agree on repo/pr/revision. ``GITHUB_SHA`` is the best head-sha
    proxy available at bind time (before the event payload is parsed); the
    correlation key is empty when there is no full repo context (D3).
    """
    correlation = resolve_correlation_from_env()
    repo_raw = correlation.get("repo")
    repo = repo_raw if isinstance(repo_raw, str) else None
    pr_number_raw = correlation.get("pr_number")
    pr_number = pr_number_raw if isinstance(pr_number_raw, (int, str)) else None
    head_sha_raw = correlation.get("commit_sha")
    head_sha = head_sha_raw if isinstance(head_sha_raw, str) else None
    attempt_raw = os.environ.get("GITHUB_RUN_ATTEMPT")
    try:
        attempt = int(attempt_raw) if attempt_raw else None
    except ValueError:
        attempt = None
    # Derive the tier from the same event payload `_resolve_credentials` uses
    # (`derive_trust_tier`, fail-closed `untrusted`) — never the
    # `MERGECRAFT_TRUST_TIER` env var, which only the CLI path sets; reading it
    # here would omit the tier on Action runs.
    from mergecraft.utils.payload import read_github_event

    try:
        event = read_github_event()
    except Exception:
        event = None
    return ReviewContext(
        review_id=resolve_review_id(),
        correlation_key=correlation_key_for(repo=repo, pr_number=pr_number, head_sha=head_sha),
        attempt=attempt,
        source="action",
        repo=repo,
        pr_number=pr_number,
        base_ref=os.environ.get("GITHUB_BASE_REF") or None,
        head_ref=os.environ.get("GITHUB_HEAD_REF") or None,
        head_sha=head_sha,
        mode="review",
        trigger=os.environ.get("GITHUB_EVENT_NAME") or "",
        trust_tier=derive_trust_tier(event=event),
    )


async def main() -> MainResult:
    """Orchestrates the four engine stages — materialize (setup + credentials),
    analyze (model chain + tool context), review (setup script + payload-timed
    agent), publish (finalize) — over a single shared :class:`RunContext`.
    The ``try``/``except``/``finally`` below is the same completion
    contract ``main()`` always had: every exit path (success, agent failure,
    timeout, the ``inconclusive`` setup-script short-circuit, or an
    unclassified exception) reaches cleanup, and every path except the two
    that predate ``ToolContext`` construction reaches the publish block.
    """
    install_loguru_redaction_filter()
    normalize_env()
    snapshot: ReviewSnapshot = canonical_review_snapshot(
        entry="action",
        source=os.environ.get("GITHUB_REPOSITORY") or None,
        replay_key=os.environ.get("GITHUB_SHA") or None,
    )
    engine: ReviewEngine[MainResult] = ReviewEngine(snapshot=snapshot)
    ensure_github_workspace_registered()
    workspace = os.environ.get("GITHUB_WORKSPACE", "").strip()
    if workspace:
        # Guard the workspace prep at its call site so a missing/UID-0 agent
        # user surfaces as a structured ``RunOutcome.configuration_error``
        # rather than escaping as an uncaught traceback. The try/except/finally
        # below is reached only after this block returns, so we route through
        # the same classification the outer handler would have used.
        try:
            prepare_workspace_for_agent(workspace)
        except _ConfigurationError as exc:
            return MainResult(
                success=False,
                error=str(exc),
                outcome=_classify_error_outcome(exc),
            )

    ctx = RunContext()
    # OB1 / O1 — bind the review-wide identity for the whole run so every
    # span closed in this process (and, via the exported review env, every
    # spawned agent CLI) carries the same ``review.id``.
    with bind_review_context(_action_review_context()):
        try:
            staged = await engine.run(
                ctx,
                on_timeout=lambda _name: kill_all_active_process_groups(),
            )
            return staged.published_or(
                MainResult(
                    success=False,
                    error="review engine returned no result",
                    outcome=RunOutcome.infra_error,
                )
            )
        except Exception as error:
            error_message = str(error) if error else "unknown error occurred"
            logger.error("{}", error_message)
            error_outcome = _classify_error_outcome(error)
            if isinstance(error, (TimeoutError, asyncio.TimeoutError, _AgentTimeoutError)):
                kill_all_active_process_groups()
            if ctx.tool_context:
                try:
                    await _publish(
                        ctx,
                        outcome=error_outcome,
                        failure_reason=error_message,
                        emit=False,
                    )
                except Exception as cleanup_exc:
                    logger.warning("post-failure learnings/status cleanup failed: {}", cleanup_exc)
            return MainResult(success=False, error=error_message, outcome=error_outcome)
        finally:
            if ctx.stop_mcp is not None:
                with contextlib.suppress(Exception):
                    ctx.stop_mcp()
            with contextlib.suppress(Exception):
                cleanup_temp_directory()
            if ctx.token_ref is not None:
                with contextlib.suppress(Exception):
                    await ctx.token_ref.aclose()
            if ctx.scm is not None:
                with contextlib.suppress(Exception):
                    await ctx.scm.aclose()
            from mergecraft.config.settings_snapshot import reset_gateway_settings_cache

            reset_gateway_settings_cache()


__all__ = [
    "MainResult",
    "RunOutcome",
    "main",
    "publish_deterministic_record",
]
