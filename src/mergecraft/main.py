"""Main orchestration — local-config BYOK runtime (no mergecraft.com)."""

from __future__ import annotations

import asyncio
import os
import time
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger

from mergecraft.analyzers.redact import install_loguru_redaction_filter
from mergecraft.analyzers.trust import (
    derive_trust_tier,
)
from mergecraft.ci.sarif_ingest import (
    ingest_ci_sarif_from_action_env,
    ingest_red_green_after_review,
)
from mergecraft.config.env import ActionInputEnv
from mergecraft.errors import AgentTimeoutError, ConfigurationError, ModelFallbackPolicyError
from mergecraft.evidence.run_packet import emit_run_packet, resolve_prepared_run_packet
from mergecraft.findings.fix_brief import fix_brief_path
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ToolContext
from mergecraft.review.engine import ReviewEngine
from mergecraft.review.roster_execution import (
    apply_roster_failure,
)
from mergecraft.review.snapshot import ReviewSnapshot, canonical_review_snapshot
from mergecraft.run_outcome import (
    RunOutcome,
    run_succeeded_for_outcome,
)
from mergecraft.scm.github import (
    create_github_scm,
)
from mergecraft.tracing.review_context import (
    ReviewContext,
    bind_review_context,
    correlation_key_for,
    resolve_review_id,
    stamp_review_context,
)
from mergecraft.tracing.tracer import resolve_correlation_from_env
from mergecraft.utils import gha_log
from mergecraft.utils.code_scanning import report_sarif_upload
from mergecraft.utils.git_setup import (
    cleanup_temp_directory,
)
from mergecraft.utils.github import GitHubClient
from mergecraft.utils.normalize_env import normalize_env
from mergecraft.utils.payload import (
    read_github_event,
)
from mergecraft.utils.privilege import prepare_workspace_for_agent
from mergecraft.utils.process_group import (
    kill_all_active_process_groups,
)
from mergecraft.utils.token import get_job_token
from mergecraft.utils.workspace import (
    WorkspacePathError,
    ensure_github_workspace_registered,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from mergecraft.agents.shared import Agent, AgentResult, AgentRunContext
    from mergecraft.config.settings import RepoSettings
    from mergecraft.evidence.shadow import VerdictProtocolPrediction
    from mergecraft.mcp.tool_state import (
        ToolState,
    )

from mergecraft.action import (
    review_dispatch,
    review_finalize,
    review_prep,
    review_publish,
)
from mergecraft.action.review_dispatch import (
    _agent_timeout_ms as _agent_timeout_ms,
)
from mergecraft.action.review_dispatch import (
    _apply_overrides_and_setup_git,
    _assemble_model_chain,
    _build_run_tool_context,
    _payload_to_ctx,
    _run_server_roster_reviewers_if_needed,
    _run_setup_script_phase,
)
from mergecraft.action.review_dispatch import (
    _first_runnable_in_chain as _first_runnable_in_chain,
)
from mergecraft.action.review_dispatch import (
    _prepare_agent_dispatch as _prepare_agent_dispatch,
)
from mergecraft.action.review_dispatch import (
    _promote_and_finalize_agent_result as _promote_and_finalize_agent_result,
)
from mergecraft.action.review_dispatch import (
    _render_run_modes as _render_run_modes,
)
from mergecraft.action.review_finalize import (
    _coverage_gate_reason as _coverage_gate_reason,
)
from mergecraft.action.review_finalize import (
    _prep_failure_reason as _prep_failure_reason,
)
from mergecraft.action.review_policy import (
    _ignore_paths_gate,
    _is_completed_review,
    _run_draft_lite,
    _skip_without_review_diff,
    _triage_gate,
)
from mergecraft.action.review_prep import (
    _read_linked_issues as _read_linked_issues,
)
from mergecraft.action.review_prep import _resolve_credentials
from mergecraft.action.review_publish import (
    _publish_policy_skip,
)
from mergecraft.action.review_pull import (
    _pull_request_body as _pull_request_body,
)
from mergecraft.action.review_pull import (
    _record_scope_declaration,
    _resolve_run_fix_labels,
    _resolve_run_red_green_declaration,
)
from mergecraft.action.review_pull import (
    _resolve_run_pull_request_metadata as _resolve_run_pull_request_metadata,
)
from mergecraft.action.review_record import (
    _publication_record_lines as _publication_record_lines,
)
from mergecraft.action.review_record import (
    _token_summary as _token_summary,
)
from mergecraft.action.review_record import (
    publish_deterministic_record as publish_deterministic_record,
)
from mergecraft.action.review_sinks import (
    _scan_sinks_after_run,
)
from mergecraft.action.review_state import (
    LiteAgentReview,
    MainResult,
    SkipAgentReview,
)
from mergecraft.action.review_state import RunContext as ActionRunState
from mergecraft.action.review_verdict import (
    _ORCHESTRATOR_PUBLISH_STEP as _ORCHESTRATOR_PUBLISH_STEP,
)
from mergecraft.action.review_verdict import (
    _publish_recorded_verdict as _publish_recorded_verdict,
)
from mergecraft.action.review_verdict import (
    owes_a_terminal_review as owes_a_terminal_review,
)
from mergecraft.action.review_verdict import (
    publication_skip_reason as publication_skip_reason,
)


class RunContext(ActionRunState):
    """Action adapter for the review engine's four stages."""

    async def materialize(self) -> None:
        with gha_log.group("setup"):
            if not self.setup_completed:
                await _setup_run(self)
            await _resolve_credentials(self)
        if self.setup_script_skip_reason:
            gha_log.warning(self.setup_script_skip_reason)

    async def analyze(self) -> None:
        self.automatic_review, self.automatic_review_reason = await _automatic_review_policy(self)
        if self.automatic_review is not None:
            self.tool_context = _policy_tool_context(self)
            if self.timeout_error is not None:
                raise _ConfigurationError(self.timeout_error) from None
            return
        with gha_log.group("model-chain"):
            await _assemble_model_chain(self)
            await _build_run_tool_context(self)

    async def review(self) -> AgentResult | SkipAgentReview | LiteAgentReview:
        if self.automatic_review == "skip":
            return SkipAgentReview(reason=self.automatic_review_reason)
        if self.automatic_review == "lite":
            return await _run_draft_lite(self)
        return await _run_review_after_analyze(self)

    async def publish(
        self, review_out: AgentResult | SkipAgentReview | LiteAgentReview
    ) -> MainResult:
        with gha_log.group("publish"):
            if self.automatic_review is not None and isinstance(review_out, SkipAgentReview):
                return await _publish_policy_skip(self, review_out.reason)
            return await _finalize(self, review_out)


async def _run_chained_attempt(
    attempt_agent: Agent,
    attempt_ctx: AgentRunContext,
    settings: RepoSettings,
    tool_state: ToolState,
    attempt_model: str | None,
) -> AgentResult:
    attempt_agent_id = attempt_agent.name
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


async def _run_single_attempt(
    agent: Agent,
    run_ctx: AgentRunContext,
    settings: RepoSettings,
    tool_state: ToolState,
    resolved_model: str | None,
) -> AgentResult:
    from mergecraft.review.lens_routing import lens_id_from_agent_id
    from mergecraft.tracing import get_tracer_from_settings
    from mergecraft.tracing.signals import agent_run_span

    with agent_run_span(
        get_tracer_from_settings(settings),
        agent_id=str(agent.name),
        role="reviewer",
        lens=lens_id_from_agent_id(str(agent.name)),
        executed_model=resolved_model,
    ):
        result = await agent.run(run_ctx)
    from mergecraft.mcp.tool_state import append_dispatched_lens

    append_dispatched_lens(tool_state, str(agent.name))
    return result


async def _run_agent_task_with_deadline(ctx: RunContext) -> tuple[str | None, AgentResult]:
    return await review_dispatch._run_agent_task_with_deadline(
        ctx, dispatch_chained=_run_chained_attempt, dispatch_single=_run_single_attempt
    )


async def _dispatch_agent_with_deadline(ctx: RunContext) -> AgentResult:
    winning_slug, result = await _run_agent_task_with_deadline(ctx)
    return _promote_and_finalize_agent_result(ctx, winning_slug, result)


async def _setup_run(ctx: RunContext) -> RunContext:
    await review_prep._setup_run(ctx, default_timeout_ms=3_600_000)
    return ctx


async def _publish(
    ctx: ActionRunState,
    *,
    outcome: RunOutcome,
    failure_reason: str | None,
    attrs_source: Callable[[], dict[str, Any]] | None = None,
    verdict_prediction: VerdictProtocolPrediction | None = None,
    actual_outcome: str | None = None,
    verdict_diagnostic: Any | None = None,
    emit: bool = True,
    sink_scan_error: str | None = None,
    sink_scan: Callable[[Path | None], str | None] | None = None,
) -> str | None:
    return await review_publish._publish(
        ctx,
        outcome=outcome,
        failure_reason=failure_reason,
        attrs_source=attrs_source,
        verdict_prediction=verdict_prediction,
        actual_outcome=actual_outcome,
        verdict_diagnostic=verdict_diagnostic,
        emit=emit,
        sink_scan_error=sink_scan_error,
        sink_scan=sink_scan,
        upload_sarif=_upload_action_sarif,
    )


async def _upload_action_sarif(tool_context: ToolContext) -> None:
    await report_sarif_upload(tool_context)


async def _finalize(
    ctx: RunContext, result: AgentResult | SkipAgentReview | LiteAgentReview
) -> MainResult:
    return await review_finalize._finalize(ctx, result, publish_result=_publish)


# Keep these names available for existing callers of the Action entry point.
_AgentTimeoutError = AgentTimeoutError
_ConfigurationError = ConfigurationError


def _classify_error_outcome(error: BaseException) -> RunOutcome:
    """Split the outer catch-all into timeout / config / infra buckets (D3, W5.2).

    Defaults to ``infra_error`` — that is the "infra never looks like
    success" invariant the taxonomy replaces the old plain boolean with.
    Only exceptions that already carry an unambiguous, distinct cause are
    reclassified; an unclassified agent crash stays ``infra_error``.
    """
    from pydantic import ValidationError

    from mergecraft.config.yaml_unique import ConfigParseError

    if isinstance(error, (_AgentTimeoutError, TimeoutError, asyncio.TimeoutError)):
        return RunOutcome.timed_out
    if isinstance(
        error,
        (
            _ConfigurationError,
            ConfigParseError,
            ModelFallbackPolicyError,
            WorkspacePathError,
            ValidationError,
        ),
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


def _policy_tool_context(ctx: RunContext) -> ToolContext:
    """Carry the bound PR identity for policy checks without building an agent."""
    assert ctx.run_context is not None
    assert ctx.scm is not None
    assert ctx.tool_state is not None
    assert ctx.tmpdir is not None
    assert ctx.token_ref is not None
    payload = _payload_to_ctx(ctx.payload)
    payload.event = PayloadEvent(
        trigger=payload.event.trigger,
        issue_number=int(ctx.pr_number) if ctx.pr_number is not None else None,
        is_pr=True,
    )
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner=ctx.run_context.repo.owner, name=ctx.run_context.repo.name),
        payload=payload,
        scm=ctx.scm,
        github_installation_token=ctx.token_ref.mcp_token,
        tool_state=ctx.tool_state,
        tmpdir=ctx.tmpdir,
        trust_tier=ctx.trust_tier,
        authority_trust=ctx.authority_trust,
        run_id=int(os.environ["GITHUB_RUN_ID"]) if os.environ.get("GITHUB_RUN_ID") else None,
        job_id=os.environ.get("GITHUB_JOB"),
        gh_event=ctx.gh_event,
    )


async def _automatic_review_policy(
    ctx: RunContext,
) -> tuple[Literal["skip", "lite"] | None, str]:
    """Apply defaults to native PR events and accept overrides from the base only."""
    if os.environ.get("GITHUB_EVENT_NAME") not in {"pull_request", "pull_request_target"}:
        return None, ""
    assert ctx.settings is not None
    event = ctx.gh_event or {}
    if isinstance(event.get("comment"), dict):
        return None, ""
    pull = event.get("pull_request")
    if not isinstance(pull, dict) or not isinstance(pull.get("number"), int):
        return None, ""
    settings: RepoSettings | None = ctx.settings
    if not ctx.settings_snapshot_operator_owned:
        from mergecraft.review_policy.ignore_paths import _base_repo_settings, _event_base_sha

        base_sha = _event_base_sha(event)
        settings_from_base = None
        if base_sha:
            assert ctx.scm is not None
            assert ctx.run_context is not None
            repo = ctx.run_context.repo
            settings_from_base, _source, _detail = await _base_repo_settings(
                ctx.scm, repo.owner, repo.name, base_sha
            )
        settings = settings_from_base
    review = settings.review if settings is not None else None
    frequency = review.triggers.frequency if review is not None else "everyPush"
    if frequency == "onRequest":
        return "skip", "Automatic review is disabled; request a review to run mergeCraft."

    drafts = review.drafts if review is not None else "skip"
    is_draft = pull.get("draft") is True
    if is_draft and drafts == "skip":
        return "skip", "Draft pull request; mergeCraft will review it when marked ready."

    if frequency == "oncePerPr" and event.get("action") == "synchronize":
        from mergecraft.mcp.checkout import list_mergecraft_reviews

        reviews = await list_mergecraft_reviews(
            _policy_tool_context(ctx), pull_number=pull["number"]
        )
        if any(_is_completed_review(item) for item in reviews):
            return "skip", "This pull request already received a mergeCraft review."
    if is_draft and drafts == "lite":
        ctx.draft_lite_settings = settings
        return "lite", "Draft pull request configured for a lite review."
    return None, ""


async def _run_review_after_analyze(
    ctx: RunContext,
) -> AgentResult | SkipAgentReview | LiteAgentReview:
    """Setup script, MCP start, and payload-timed agent dispatch (review stage)."""
    await _apply_overrides_and_setup_git(ctx)
    assert ctx.tool_context is not None
    await _resolve_run_red_green_declaration(ctx)
    # The fail-then-pass receipt is read after the agent phase, once the review diff
    # exists (``ingest_red_green_after_review`` below), not in this pre-agent lane.
    await ingest_ci_sarif_from_action_env(
        ctx.tool_context,
        ctx.gh_event or {},
        event_name=os.environ.get("GITHUB_EVENT_NAME", ""),
        red_green=False,
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
    # Base-side fix labels are recorded before any tier can skip the agent, the
    # setup-script ``inconclusive`` skip included, so the packet never falls back.
    await _resolve_run_fix_labels(ctx)
    await _resolve_run_pull_request_metadata(ctx)
    if sc_action == "skip_agent":
        assert isinstance(sc_payload, str)
        skip_reason = sc_payload
        logger.warning(
            "» setup script failure under inconclusive policy — skipping agent "
            "loop to honour no-verdict: {}",
            skip_reason,
        )
        # Engine publish (``_finalize``) owns completion; do not publish here.
        return _skip_without_review_diff(ctx, SkipAgentReview(reason=skip_reason))

    # #1056 part 3: read once, before the fast-path gate and before any dispatch.
    await _record_scope_declaration(ctx)
    triage_out = await _triage_gate(ctx)
    if triage_out is not None:
        return _skip_without_review_diff(ctx, triage_out)
    ignore_skip = await _ignore_paths_gate(ctx)
    if ignore_skip is not None:
        return _skip_without_review_diff(ctx, ignore_skip)

    with gha_log.group("agent-dispatch"):
        await _prepare_agent_dispatch(ctx)
        dispatch_started = time.perf_counter()
        result = await _dispatch_agent_with_deadline(ctx)
        roster = await _run_server_roster_reviewers_if_needed(ctx)
        from mergecraft.utils.llm_review_timing import snapshot_llm_review_timing

        if ctx.tool_state is not None and ctx.tool_state.selected_mode in {
            "Review",
            "IncrementalReview",
        }:
            ctx.tool_state.llm_review_timing = snapshot_llm_review_timing()
        # The review diff, ignored paths and unreviewable paths exist now, so the
        # declared workflow can be shown untouched before the packet is assembled.
        await ingest_red_green_after_review(
            ctx.tool_context,
            ctx.gh_event or {},
            event_name=os.environ.get("GITHUB_EVENT_NAME", ""),
        )
        if ctx.tool_state is not None:
            ctx.tool_state.phase_elapsed_s["agent"] = round(
                time.perf_counter() - dispatch_started, 3
            )
        return apply_roster_failure(result, roster)


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
    # TBO/TB6 — do NOT record the pre-binding tier as ``trust_tier``. This
    # entry point binds before ``_resolve_credentials`` fetches and binds the
    # target PR (main.py:812-814), so for a comment-on-PR or a PR-naming
    # dispatch the event carries no head and ``derive_trust_tier`` floors to
    # ``untrusted`` — while ``resolve_trust_policy`` on the *bound* event
    # returns ``trusted`` for a same-repo PR. Recording that floor as
    # ``trust_tier`` would read the opposite of ``tool_state.trust_tier``.
    # It is kept under ``raw_event_trust_floor`` instead, and ``main`` stamps
    # the real tier once materialize has resolved it (``stamp_review_context``).
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
        raw_event_trust_floor=derive_trust_tier(event=event),
    )


def _stamp_review_trust_tier(ctx: RunContext) -> None:
    """Stamp the run's resolved trust tier on the bound review context (TBO/TB6).

    Registered as an engine ``on_stage`` hook that fires in the entry-point
    context (before each stage's ``wait_for`` copies it), so a tier resolved
    during ``materialize`` reaches every span closed afterwards — including
    the run root — as ``review.trust_tier`` / ``mergecraft.trust_tier``. Before
    materialize the tier is unset and this is a no-op; the raw pre-binding
    floor stays available as ``review.raw_event_trust_floor``.
    """
    tool_state = ctx.tool_state
    tier = getattr(tool_state, "trust_tier", None) if tool_state is not None else None
    if isinstance(tier, str) and tier:
        stamp_review_context(trust_tier=tier)


_MERGE_GROUP_PROOF_TIMEOUT_S = 120


async def _run_merge_group() -> MainResult:
    """Handle the native queue event with GitHub evidence only."""
    from mergecraft.merge_queue import bind_merge_group, prove_merge_group
    from mergecraft.reapproval import ReapprovalUnavailableError
    from mergecraft.utils.status_checks import APPROVAL_CHECK, create_check_run

    try:
        group = bind_merge_group(read_github_event(), os.environ)
        if (ActionInputEnv().status_checks or "").lower() != "enabled":
            msg = "The merge group job requires status_checks: enabled"
            raise ReapprovalUnavailableError(msg)
        token = get_job_token()
    except (ValueError, ReapprovalUnavailableError) as error:
        return MainResult(success=False, error=str(error), outcome=RunOutcome.configuration_error)
    scm = create_github_scm(token, client=GitHubClient(token))
    failure: str | None = None
    summary = ""
    try:
        try:
            approvals = await asyncio.wait_for(
                prove_merge_group(scm, group, os.environ.get("GITHUB_WORKFLOW_REF")),
                timeout=_MERGE_GROUP_PROOF_TIMEOUT_S,
            )
            summary = "\n".join(
                ["All queue layers match trusted pull request approvals.", *approvals]
            )
        except TimeoutError:
            failure = "Merge group evidence verification timed out."
        except ReapprovalUnavailableError as error:
            failure = str(error)
        except Exception as error:
            failure = f"Merge group evidence could not be read ({type(error).__name__})."
        try:
            await create_check_run(
                scm,
                owner=group.owner,
                repo=group.repo,
                run_id=os.environ.get("GITHUB_RUN_ID"),
                name=APPROVAL_CHECK,
                head_sha=group.layer.head,
                conclusion="failure" if failure else "success",
                title="Merge group approval unavailable" if failure else "Merge group approved",
                summary=failure or summary,
            )
        except Exception as error:
            failure = f"Merge group approval could not be posted ({type(error).__name__})."
    finally:
        await _run_cleanup_step_async("scm.aclose", scm.aclose)
    return MainResult(
        success=failure is None,
        error=failure,
        outcome=RunOutcome.failed if failure else RunOutcome.passed,
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
    if os.environ.get("GITHUB_EVENT_NAME") == "merge_group":
        return await _run_merge_group()
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
    # TBO/TB6 — stamp the tier the run actually uses once materialize has
    # bound the target PR and resolved it. ``on_stage`` runs in this
    # (entry-point) context before each stage hook's ``wait_for`` task copies
    # the context, so the stamp reaches every span closed afterwards — the
    # bound ``ReviewContext`` above records only the raw pre-binding floor
    # (``raw_event_trust_floor``), never a ``trust_tier`` that could read the
    # opposite of ``tool_state.trust_tier``.
    engine.set_on_stage(lambda _name: _stamp_review_trust_tier(ctx))
    # OB1 / O1 — bind the review-wide identity for the whole run so every
    # span closed in this process (and, via the exported review env, every
    # spawned agent CLI) carries the same ``review.id``.
    with bind_review_context(_action_review_context()):
        try:
            # Tracing settings are resolved by setup. From this first usable
            # seam onward, the run root remains open through every engine
            # stage and failure-publication path.
            materialize_budget = engine.timeout_s("materialize")
            setup_started = time.monotonic()
            try:
                await asyncio.wait_for(_setup_run(ctx), timeout=materialize_budget)
            except TimeoutError:
                kill_all_active_process_groups()
                raise
            materialize_remaining = max(
                0.001,
                materialize_budget - (time.monotonic() - setup_started),
            )
            assert ctx.settings is not None
            from mergecraft.tracing.tracer import get_tracer_from_settings, run_root_span

            tracer = get_tracer_from_settings(ctx.settings, new_run=True)
            with run_root_span(
                tracer,
                attrs_source=lambda: dict(resolve_correlation_from_env()),
            ) as root_span:
                try:
                    staged = await engine.run(
                        ctx,
                        timeouts={"materialize": materialize_remaining},
                        on_timeout=lambda _name: kill_all_active_process_groups(),
                    )
                    result = staged.published_or(
                        MainResult(
                            success=False,
                            error="review engine returned no result",
                            outcome=RunOutcome.infra_error,
                        )
                    )
                except Exception as error:
                    result = await _action_failure_result(ctx, error)
                if not result.success:
                    root_span.set_status("error", result.error or "review failed")
                return result
        except Exception as error:
            # Setup failures happen before tracing settings exist, so no run
            # root can be created. Preserve the existing structured outcome.
            return await _action_failure_result(ctx, error)
        finally:
            if ctx.stop_mcp is not None:
                _run_cleanup_step("stop_mcp", ctx.stop_mcp)
            _run_cleanup_step("cleanup_temp_directory", cleanup_temp_directory)
            if ctx.token_ref is not None:
                await _run_cleanup_step_async("token_ref.aclose", ctx.token_ref.aclose)
            if ctx.scm is not None:
                await _run_cleanup_step_async("scm.aclose", ctx.scm.aclose)
            from mergecraft.config.settings_snapshot import reset_gateway_settings_cache

            reset_gateway_settings_cache()


def _log_cleanup_failure(step: str, exc: Exception) -> None:
    """One warning per failed best-effort cleanup step, never a secret (CR-D8)."""
    logger.warning("cleanup step {} failed: {}: {}", step, type(exc).__name__, exc)


def _run_cleanup_step(step: str, action: Callable[[], object]) -> None:
    """Run a synchronous cleanup step, logging one warning on failure."""
    try:
        action()
    except Exception as exc:
        _log_cleanup_failure(step, exc)


async def _run_cleanup_step_async(step: str, action: Callable[[], Awaitable[object]]) -> None:
    """Run an async cleanup step, logging one warning on failure."""
    try:
        await action()
    except Exception as exc:
        _log_cleanup_failure(step, exc)


_FAILURE_PUBLISH_TIMEOUT_S: float = 120.0
"""Bound on the failure path's record and status publication (the publish stage's budget)."""


async def _emit_packet_after_publish_failure(
    ctx: RunContext, outcome: RunOutcome
) -> tuple[str | None, str | None]:
    """Write the evidence packet for a run that failed during publication.

    Local work only, so it runs before any failure-path network call. The
    written packet is sink-scanned like the normal path's; on a hit the packet
    is removed and the scan's reason is returned. Returns ``(path, sink_error)``.
    """
    tool_context = ctx.tool_context
    if tool_context is None:
        return None, None
    prepared = resolve_prepared_run_packet(
        tool_context, run_succeeded=run_succeeded_for_outcome(outcome)
    )
    written = await asyncio.to_thread(emit_run_packet, tool_context, packet=prepared)
    sink_error = _scan_sinks_after_run(
        ctx, extra_paths=[written, fix_brief_path(written)] if written else []
    )
    if sink_error is not None or not written:
        return None, sink_error
    return str(written), None


async def _action_failure_result(ctx: RunContext, error: Exception) -> MainResult:
    """Map one Action failure and run best-effort failure publication.

    A failure after the publish stage began (a publish-stage timeout, after the
    verdict may already be on GitHub) still writes the evidence packet first,
    before the bounded record and status publication below.
    """
    error_message = str(error) if error else "unknown error occurred"
    logger.error("{}", error_message)
    error_outcome = _classify_error_outcome(error)
    if isinstance(error, (TimeoutError, asyncio.TimeoutError, _AgentTimeoutError)):
        kill_all_active_process_groups()
    packet_path: str | None = None
    sink_error: str | None = None
    if ctx.tool_context and ctx.publish_started:
        try:
            packet_path, sink_error = await _emit_packet_after_publish_failure(ctx, error_outcome)
        except Exception as emit_exc:
            logger.warning("post-failure evidence packet emission failed: {}", emit_exc)
        if sink_error is not None:
            error_outcome = RunOutcome.failed
            error_message = sink_error
    if ctx.tool_context:
        try:
            await asyncio.wait_for(
                _publish(
                    ctx,
                    outcome=error_outcome,
                    failure_reason=error_message,
                    emit=False,
                    sink_scan_error=sink_error,
                ),
                timeout=_FAILURE_PUBLISH_TIMEOUT_S,
            )
        except TimeoutError:
            logger.warning(
                "post-failure learnings/status publication timed out after {:g}s",
                _FAILURE_PUBLISH_TIMEOUT_S,
            )
        except Exception as cleanup_exc:
            logger.warning("post-failure learnings/status cleanup failed: {}", cleanup_exc)
    return MainResult(
        success=False,
        error=error_message,
        outcome=error_outcome,
        evidence_packet_path=packet_path,
    )


__all__ = [
    "MainResult",
    "RunOutcome",
    "main",
    "publish_deterministic_record",
]
