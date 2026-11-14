"""Main orchestration — local-config BYOK runtime (no mergecraft.com)."""

from __future__ import annotations

import asyncio
import os
import time
from copy import deepcopy
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger

from mergecraft.action.inputs import (
    apply_setup_overrides,
    apply_tracing_overrides,
    collect_tracing_warnings_for_summary,
    export_tracing_env_from_action_inputs,
)
from mergecraft.agents.gates import subagent_denied_tool_names
from mergecraft.agents.lite import LiteOutcome, lite_model_slug, run_lite_review
from mergecraft.agents.post_run import finalize_agent_result
from mergecraft.agents.shared import FAILOVER_ELIGIBLE_KEY, Agent, AgentResult, AgentRunContext
from mergecraft.agents.verifier import verifier_denied_tool_names
from mergecraft.analyzers.redact import install_loguru_redaction_filter, redact_secrets
from mergecraft.analyzers.sarif_upload import resolve_sarif_upload_enabled
from mergecraft.analyzers.trust import (
    allow_repo_command_overrides,
    derive_trust_tier,
    resolve_analyzers_mode,
)
from mergecraft.ci.sarif_ingest import (
    ingest_ci_sarif_from_action_env,
    ingest_red_green_after_review,
    record_unverified_red_green,
)
from mergecraft.classify.triage import TriageDecision
from mergecraft.config.env import ActionInputEnv, EnvSettingsError, validate_env_settings
from mergecraft.config.settings import ReviewSettings
from mergecraft.evidence.run_packet import emit_run_packet, resolve_prepared_run_packet
from mergecraft.fast_path import load_triage_inputs, triage_pull_request
from mergecraft.main_outcome import (
    _is_review_mode,
    _publication_outcome_inputs,
    _publication_unproven,
    _publish_span_attrs,
    _verdict_protocol_publish,
)
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.dependencies import start_installation
from mergecraft.mcp.endpoints import mcp_role_url
from mergecraft.mcp.server import start_mcp_http_server
from mergecraft.mcp.tool_state import (
    ProgressComment,
    ToolState,
    init_tool_state,
    loaded_review_skills_for_ledger,
)
from mergecraft.modes import _custom_modes, compute_modes
from mergecraft.prep.types import is_prep_install_failure
from mergecraft.requirements.ingest import ScopeDeclaration, parse_scope_paths
from mergecraft.review.engine import ReviewEngine
from mergecraft.review.roster_execution import (
    RosterExecutionSummary,
    apply_roster_failure,
    primary_repo_state_dir,
    run_file_group_reviewers,
)
from mergecraft.review.snapshot import ReviewSnapshot, canonical_review_snapshot
from mergecraft.review_checks import StaticCheckConfig
from mergecraft.review_policy.fix_labels import resolve_fix_labels
from mergecraft.review_policy.ignore_paths import INPUT_ENV as IGNORE_PATHS_INPUT_ENV
from mergecraft.review_policy.ignore_paths import list_pull_request_paths, resolve_review_ignore
from mergecraft.review_policy.red_green import read_red_green_declaration
from mergecraft.run_outcome import (
    RUN_OUTCOME_CONCLUSION,
    CompletionConclusion,
    RunOutcome,
    outcome_with_disposition_ledger,
    run_succeeded_for_outcome,
)
from mergecraft.scm.github import (
    create_github_scm,
    github_client_from_scm,
)
from mergecraft.security.review_integrity import scan_local_sinks_for_secrets
from mergecraft.tracing.review_context import (
    ReviewContext,
    bind_review_context,
    correlation_key_for,
    resolve_review_id,
    stamp_review_context,
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
    from collections.abc import Awaitable, Callable, Sequence

    from mergecraft.analyzers.manifest import TrustTier
    from mergecraft.config.settings import RepoSettings, RunContextData
    from mergecraft.evidence.shadow import VerdictProtocolPrediction
    from mergecraft.mcp.verdict import VerdictDiagnostic
    from mergecraft.modes import Mode
    from mergecraft.scm.protocol import ScmProvider
    from mergecraft.types import AgentId


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
    # #1009 — the failed agent result declared ``failover_eligible``: no retry of
    # this rung's credential can succeed, but the next vendor's may. Surfaced as
    # the action's ``failover_eligible`` output so the workflow cascade can hand
    # the review on even though this rung's packet carries a ``neutral`` verdict.
    failover_eligible: bool = False


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
    # Author metadata is cached separately from the deliberately narrow trust event.
    pull_request_snapshots: dict[tuple[str, str, int, str, str], dict[str, Any]] = field(
        default_factory=dict
    )
    tool_state: ToolState | None = None
    tmpdir: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    timeout_ms: int | None = None
    timeout_raw: Any = None
    timeout_error: str | None = None
    setup_completed: bool = False
    automatic_review: Literal["skip", "lite"] | None = None
    automatic_review_reason: str = ""
    draft_lite_settings: RepoSettings | None = None

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
    agent_deadline_monotonic: float | None = None
    mcp_url: str = ""
    stop_mcp: Callable[[], None] | None = None
    subagent_denied: list[str] = field(default_factory=list)
    verifier_denied: list[str] = field(default_factory=list)
    instructions: Any = None
    run_ctx: AgentRunContext | None = None
    run_bounds: Any = None
    budget_tracker: Any = None
    budget_exhaustion: Any = None
    # Why a required ``set_output`` payload is missing, if it is (resolver input).
    structured_output_error: str | None = None
    # Instructions rendered at run start, per harness, for every attempt and
    # server-side reviewer; never re-rendered from the post-checkout tree.
    run_start_instructions: dict[str, Any] = field(default_factory=dict)
    # -- populated by ``_finalize`` -------------------------------------------
    # Why this run's formal review was not posted as an APPROVE, if it was not.
    approval_withheld_reason: str | None = None
    # The publish stage began: the review finished, so a failure from here on
    # (a publish-stage timeout) still owes the run its evidence packet.
    publish_started: bool = False

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


@dataclass(frozen=True, slots=True)
class SkipAgentReview:
    """Review-stage outcome when setup-script policy or the triage fast path skips the agent."""

    reason: str


@dataclass(frozen=True, slots=True)
class LiteAgentReview:
    """Review-stage outcome when the triage ``lite`` tier replaced the agent with one call.

    ``outcome`` is ``reviewed`` or ``failed``; a ``downgraded`` call never becomes a
    ``LiteAgentReview`` (the run takes the full review instead). The agent, its MCP
    server and the roster never start for it, and it never grants approval.
    """

    decision: TriageDecision
    outcome: LiteOutcome


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


def _publication_record_lines(tool_state: ToolState) -> list[str]:
    """Record lines naming what GitHub shows when it differs from the recorded verdict.

    A publication mismatch names both verdicts: the one GitHub shows (published
    earlier in this run) and the final recorded one, which was not published.
    A review on this head that proves no verdict (recovered after a lost create
    response, state neither approval nor change request) says the recorded
    verdict is not proven published. A same-verdict publication lists the
    recorded findings its inline comments lack, by fingerprint. Empty when the
    published review matches the record.
    """
    lines: list[str] = []
    review = tool_state.review
    submission = tool_state.terminal_submission
    if tool_state.terminal_publication_mismatch:
        published = review.verdict if review is not None and review.verdict else "unknown"
        recorded = str(submission.verdict) if submission is not None else "unknown"
        lines += [
            "",
            f"**Publication mismatch:** GitHub shows the `{published}` review this run "
            f"published earlier on this head; the final recorded verdict `{recorded}` was "
            "not published, and no second review was posted.",
        ]
    elif (
        submission is not None
        and review is not None
        and review.verdict is None
        and review.reviewed_sha is not None
    ):
        lines += [
            "",
            f"**Publication unproven:** GitHub shows a review this run published on this "
            f"head, but it is neither an approval nor a change request; the final recorded "
            f"verdict `{submission.verdict}` is not proven published, and no second review "
            "was posted.",
        ]
    elif tool_state.publication_incomplete:
        missing = sorted(tool_state.publication_incomplete)
        lines += [
            "",
            f"**Publication incomplete:** the published review does not show {len(missing)} "
            "recorded finding(s) as inline comments: "
            + ", ".join(f"`{fingerprint}`" for fingerprint in missing),
        ]
    return lines


def _record_attempt_marker(ctx: ToolContext) -> str:
    """Hidden marker naming the Actions run attempt that wrote a deterministic record."""
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "").strip() or "1"
    return f"<!-- mergecraft-record-attempt: {ctx.run_id or 'local'}:{attempt} -->"


async def publish_deterministic_record(
    *,
    pull_number: int,
    packet: Any,
    rejection_reason: str | None = None,
    tmpdir: str | None = None,
    ctx: ToolContext | None = None,
    run_outcome: RunOutcome | None = None,
    verdict_diagnostic: Any | None = None,
    approval_withheld_reason: str | None = None,
) -> None:
    """Complete the formal review with the final deterministic run record.

    ``approval_withheld_reason`` names why an ``approve`` verdict was published
    as a comment rather than an approval; the record states it.

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
    import re

    from mergecraft.findings.ledger import (
        DETERMINISTIC_RECORD_MARKER,
        REVIEW_BODY_MARKER,
        _is_trusted_sticky_author,
        _run_bound_sticky_id,
        _run_sticky_scope,
        ensure_finding_ledger,
        fetch_sticky_progress_comment,
        hydrate_finding_ledger_from_progress_comment,
        merge_ledger_into_comment,
        render_deterministic_review_block,
    )
    from mergecraft.mcp.comment import add_footer
    from mergecraft.mcp.review import _truncate_review_body_for_github
    from mergecraft.review.authorship import expected_publisher_logins
    from mergecraft.scm.github import create_github_scm
    from mergecraft.utils.learnings import merge_learnings_delta_into_review_body
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
            # No run event to derive trust from, so the record claims no trust.
            trust_tier="untrusted",
        )

    tool_state = resolved_ctx.tool_state
    await hydrate_finding_ledger_from_progress_comment(resolved_ctx)
    analyzer_run = tool_state.analyzer_run
    block = render_deterministic_review_block(
        packet=packet,
        rejection_reason=rejection_reason,
        run_url=_run_url(resolved_ctx),
        run_outcome=run_outcome,
        verdict_diagnostic=verdict_diagnostic,
        analyzer_summary=analyzer_run.pre_merge_summary if analyzer_run is not None else None,
        # The accepted summary already lives in the formal review body; a lite run
        # has no formal review body, so its single call's summary is the record's.
        agent_summary=_lite_record_summary(tool_state.lite_review),
        trust_tier=resolved_ctx.trust_tier,
        attempt_count=len(tool_state.usage_entries) if tool_state.usage_entries else None,
        token_summary=_token_summary(
            tool_state.usage_entries,
            budget_tracker=resolved_ctx.budget_tracker,
        ),
        cost_summary=_cost_summary(
            tool_state.usage_entries,
            budget_tracker=resolved_ctx.budget_tracker,
        ),
        llm_review_timing=tool_state.llm_review_timing,
        credential_degradations=list(tool_state.credential_degradations),
        agent_sandbox_decision=tool_state.agent_sandbox_decision,
        action_pin_sha=_action_pin_sha(),
        image_source_sha=_image_source_sha(),
        review_skills=loaded_review_skills_for_ledger(tool_state),
        review_mcp_servers=_loaded_review_mcp(tool_state),
        publication_entrypoint=tool_state.review_publication_entrypoint,
        inline_comments_demoted=tool_state.review_inline_comments_demoted,
        comment_fallback_applied=tool_state.review_comment_fallback_applied,
        review_body_truncated=tool_state.review_body_truncated,
    )
    publication_lines = _publication_record_lines(tool_state)
    if approval_withheld_reason:
        publication_lines += [
            "",
            "**Approval withheld:** the recorded verdict is `approve`, but this run did "
            f"not pass ({approval_withheld_reason}), so it was published as a comment.",
        ]
    if publication_lines:
        block = "\n".join([block.rstrip(), *publication_lines]) + "\n"
    from mergecraft.mcp.review import should_publish_sticky_only

    if tool_state.review_publication_sticky_only or should_publish_sticky_only(packet):
        # #1078 — this rung is non-terminal (a fallback rung will replace a
        # neutral decision), so its record belongs in the sticky progress
        # comment. It must not create the formal review the publish seam
        # deliberately skipped, and must not retire the sticky as a legacy
        # record: the sticky is the record.
        from mergecraft.findings.ledger import upsert_sticky_progress_comment

        await upsert_sticky_progress_comment(resolved_ctx, block)
        return
    owner, repo = resolved_ctx.repo.owner, resolved_ctx.repo.name
    review = tool_state.review
    existing_body = ""
    run_url = _run_url(resolved_ctx)
    attempt_marker = _record_attempt_marker(resolved_ctx)
    if review is None and run_url:
        # A publish response can be lost after GitHub accepted the review.
        # Reuse the record this attempt created on this head on retry. The run
        # URL is the same on every attempt of a run, so the match also needs
        # this attempt's marker: a re-run never rewrites an earlier attempt's
        # review (which may be an approval).
        from mergecraft.mcp.tool_state import ReviewRecord, primary_repo_state

        bound_sha = primary_repo_state(tool_state).checkout_sha

        def _is_this_attempts_record(item: dict[str, Any]) -> bool:
            item_body = str(item.get("body") or "")
            item_sha = str(item.get("commit_id") or "")
            return (
                _is_trusted_sticky_author(item)
                and item_body.lstrip().startswith(DETERMINISTIC_RECORD_MARKER)
                and f"- **Run:** {run_url}" in item_body
                and attempt_marker in item_body
                and (not bound_sha or not item_sha or item_sha == bound_sha)
            )

        for page in range(1, 11):
            reviews = await resolved_ctx.scm.list_reviews(
                owner, repo, pull_number, params={"per_page": 100, "page": page}
            )
            matched = next((item for item in reviews if _is_this_attempts_record(item)), None)
            if matched is not None:
                review = ReviewRecord(
                    id=int(matched["id"]),
                    node_id=str(matched.get("node_id") or ""),
                    reviewed_sha=str(matched.get("commit_id") or "") or None,
                )
                tool_state.review = review
                break
            if len(reviews) < 100:
                break
    if review is not None:
        existing = await resolved_ctx.scm.get_review(owner, repo, pull_number, review.id)
        existing_body = str(existing.get("body") or "")

    # The old progress comment is read through the same rule as every other "did
    # mergeCraft post this?" decision: the run-bound comment id, then the run's
    # expected-publisher set, never a bare bot-type match. With neither, the read is
    # skipped and the record says so.
    legacy: dict[str, Any] | None = None
    if not expected_publisher_logins(resolved_ctx) and _run_bound_sticky_id(resolved_ctx) is None:
        logger.info(
            "learnings migration: earlier progress comment read skipped for PR #{} — no "
            "publisher identity and no run-bound comment id prove who wrote it",
            pull_number,
        )
        block = (
            f"{block.rstrip()}\n\n**Earlier progress comment not read:** no publisher "
            "identity proves which comment is mergeCraft's, so its learnings were not "
            "carried into this record.\n"
        )
    else:
        with _run_sticky_scope(resolved_ctx):
            legacy = await fetch_sticky_progress_comment(resolved_ctx.scm, owner, repo, pull_number)
    legacy_body = str(legacy.get("body") or "") if legacy is not None else ""
    # Preserve the old comment's ephemeral learnings before retiring it. Its
    # run record and finding markers are rendered anew in this formal review.
    legacy_delta = re.search(
        r"### Learnings delta[\s\S]*?(?=\n<!-- mergecraft-ledger:|\n\*via mergecraft\*|\Z)",
        legacy_body,
    )
    tail = (
        existing_body.split(REVIEW_BODY_MARKER, 1)[1].strip()
        if REVIEW_BODY_MARKER in existing_body
        else ""
    )
    if legacy_delta is not None and "### Learnings delta" not in tail:
        tail = f"{tail}\n\n{legacy_delta.group(0).strip()}".strip()
    tail = merge_learnings_delta_into_review_body(tool_state, tail)
    body = f"{block.rstrip()}\n{attempt_marker}\n{REVIEW_BODY_MARKER}\n"
    if tail:
        body += f"\n{tail}\n"
    body = merge_ledger_into_comment(body, records=ensure_finding_ledger(tool_state).records())
    body = add_footer(resolved_ctx, body)
    body = str(
        _truncate_review_body_for_github(resolved_ctx, {"body": body}, pull_number=pull_number)[
            "body"
        ]
    )

    if review is not None:
        await resolved_ctx.scm.update_review(owner, repo, pull_number, review.id, body)
    else:
        # No model verdict was accepted or published. A diagnostic COMMENT
        # review records the failure without implying an approval or adding a
        # second summary-only review beside an accepted verdict.
        result = await resolved_ctx.scm.create_review(
            owner, repo, pull_number, event="COMMENT", body=body
        )
        from mergecraft.mcp.tool_state import ReviewRecord

        tool_state.review = ReviewRecord(
            id=int(result["id"]),
            node_id=str(result.get("node_id") or ""),
            reviewed_sha=None,
        )

    # Only a bot-authored legacy record may be removed, and only after the
    # formal review has accepted all of its persisted state. A contributor can
    # quote the heading and a ledger marker; body shape alone must not delete
    # that comment or copy it into the review.
    if (
        legacy is not None
        and _is_trusted_sticky_author(legacy)
        and legacy_body.startswith("## mergeCraft progress")
        and (DETERMINISTIC_RECORD_MARKER in legacy_body or "<!-- mergecraft-ledger:" in legacy_body)
    ):
        try:
            await resolved_ctx.scm.delete_issue_comment(owner, repo, int(legacy["id"]))
        except Exception as err:
            logger.warning("legacy review record could not be retired: {}", err)
        else:
            tool_state.progress_comment = False


def _action_pin_sha() -> str | None:
    from mergecraft.build_metadata import resolve_action_pin_sha

    return resolve_action_pin_sha()


def _image_source_sha() -> str | None:
    from mergecraft.build_metadata import resolve_build_commit

    return resolve_build_commit()


def _loaded_review_mcp(tool_state: ToolState) -> list[str]:
    return list(tool_state.review_mcp_names)


def _token_summary(
    usage_entries: list[Any],
    *,
    budget_tracker: Any | None = None,
) -> str | None:
    from mergecraft.utils.run_bounds import BudgetTracker, token_summary_from_usage

    tracker = budget_tracker if isinstance(budget_tracker, BudgetTracker) else None
    return token_summary_from_usage(usage_entries, budget_tracker=tracker)


def _cost_summary(
    usage_entries: list[Any],
    *,
    budget_tracker: Any | None = None,
) -> str | None:
    from mergecraft.agents.curated_model_catalog import cost_summary_from_usage_entries

    return cost_summary_from_usage_entries(usage_entries, budget_tracker=budget_tracker)


async def _report_record_publication_failure(
    tool_context: ToolContext, prepared: Any, sink_error: str | None
) -> None:
    """Post the checks for a run whose formal review record failed to publish."""
    await report_status_checks(
        tool_context,
        run_succeeded=False,
        failure_reason="formal review record publication failed",
        conclusion="neutral",
        packet=prepared,
        approval_failure_reason=sink_error,
    )


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
    sink_scan_error: str | None = None,
    sink_scan: Callable[[Path | None], str | None] | None = None,
) -> str | None:
    """Prepare packet + emit + persist learnings + status checks.

    Shared by the normal post-agent path in ``_finalize`` and the exception
    cleanup path (``emit=False`` — failure still reports status but skips
    SARIF/packet emit). Tracer span wraps the emit path only.

    ``sink_scan_error`` (SX-D10) is the pre-publication sink-hit reason. It does
    not change the completion check — the caller has already mapped the failed
    outcome — but it forces the ``mergecraft-approval`` conclusion to
    ``failure`` regardless of the packet verdict, so a credential that reached a
    local sink cannot leave the merge gate open.

    ``sink_scan`` (SX-D10) is the post-emission scan callback. In the emit path
    the packet is written **before** the status/approval report, then
    ``sink_scan(written)`` re-scans it (the artifact the workflow uploads). A
    non-``None`` result forces the completion and approval checks to ``failure``
    for this report, so a credential that only ever reached the generated
    packet still closes the merge gate before artifact upload.
    """
    tool_context = ctx.tool_context
    if tool_context is None:
        return None
    prepared = resolve_prepared_run_packet(
        tool_context, run_succeeded=run_succeeded_for_outcome(outcome)
    )

    # Effective values the status report uses. The pre-emission scan may already
    # have failed the run; the post-emission scan (emit path) can update these
    # before the report is posted. An open analyzer disposition ledger makes a
    # passed run inconclusive so the completion check agrees with the packet's
    # ``neutral`` approval conclusion (#1014); ``_finalize`` applies the same
    # rule to the run's own result.
    effective_outcome, ledger_reason = outcome_with_disposition_ledger(outcome, prepared)
    effective_failure_reason = ledger_reason or failure_reason
    effective_sink_error = sink_scan_error

    async def _learnings_and_status() -> None:
        await persist_learnings(tool_context)
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
        if rejection_reason is None and tool_context.tool_state.finalize_failure:
            rejection_reason = tool_context.tool_state.finalize_failure
        review_run = tool_context.tool_state.selected_mode in {"Review", "IncrementalReview"}
        if rejection_reason is None and tool_context.tool_state.terminal_publication_failed:
            rejection_reason = "terminal_publication_failed"
        lite_run = tool_context.tool_state.lite_review is not None
        if (
            rejection_reason is None
            and review_run
            and tool_context.tool_state.terminal_submission is None
        ):
            # A lite run records no terminal verdict by design (one capped call, no
            # agent); only a real failure reason belongs in its record.
            rejection_reason = effective_failure_reason or (
                None if lite_run else "no_accepted_model_verdict"
            )
        # A refused terminal attempt owes the PR a record even when the agent never
        # selected a mode: without it a rejected approval left only a failing
        # approval check and no review naming the rejection (#1211).
        terminal_rejected = tool_context.tool_state.last_terminal_rejection is not None
        if (
            pull_number is not None
            and prepared is not None
            and (
                review_run
                or lite_run
                or terminal_rejected
                or tool_context.tool_state.review is not None
            )
        ):
            try:
                await publish_deterministic_record(
                    pull_number=int(pull_number),
                    packet=prepared,
                    rejection_reason=rejection_reason,
                    tmpdir=tool_context.tmpdir,
                    ctx=tool_context,
                    run_outcome=effective_outcome,
                    verdict_diagnostic=verdict_diagnostic,
                    approval_withheld_reason=ctx.approval_withheld_reason,
                )
            except Exception as err:
                if lite_run:
                    # The lite comment is the record a human reads, but the checks carry
                    # the same findings and the never-approve rule; a failed post is
                    # reported, and the checks below still post.
                    logger.warning(
                        "» the lite review comment could not be published ({}); the checks "
                        "still carry its findings",
                        type(err).__name__,
                    )
                    gha_log.warning("mergeCraft: the lite review comment could not be published")
                else:
                    await _report_record_publication_failure(
                        tool_context, prepared, effective_sink_error
                    )
                    raise
        run_ok = run_succeeded_for_outcome(effective_outcome)
        completion: CompletionConclusion = RUN_OUTCOME_CONCLUSION[effective_outcome]
        completion_reason = effective_failure_reason
        lite_completion = _lite_completion_conclusion(
            tool_context.tool_state, prepared, outcome_conclusion=completion
        )
        if lite_completion is not None:
            completion, lite_reason = lite_completion
            completion_reason = completion_reason or lite_reason
        await report_status_checks(
            tool_context,
            run_succeeded=run_ok,
            failure_reason=completion_reason,
            conclusion=completion,
            packet=prepared,
            approval_failure_reason=effective_sink_error,
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
                run_outcome=effective_outcome,
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
                cost_summary=_cost_summary(
                    tool_context.tool_state.usage_entries,
                    budget_tracker=tool_context.budget_tracker,
                ),
                llm_review_timing=tool_context.tool_state.llm_review_timing,
                credential_degradations=list(tool_context.tool_state.credential_degradations),
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
        # SX-D10 — emit *before* the status/approval report so the post-emission
        # scan can see the packet this run generates; the packet is an upload
        # source, and a credential that only ever reached it would otherwise
        # ship untouched. A hit is folded into the report below (completion and
        # approval both ``failure``) and the sink is already deleted.
        written = await asyncio.to_thread(
            emit_run_packet,
            tool_context,
            packet=prepared,
            verdict_prediction=verdict_prediction,
            actual_outcome=actual_outcome,
        )
        if sink_scan is not None:
            post_error = sink_scan(Path(written) if written else None)
            if post_error is not None:
                effective_sink_error = post_error
                effective_outcome = RunOutcome.failed
                effective_failure_reason = post_error
        await _learnings_and_status()
        # #39 — opt-in, off by default, and never a gate: with `sarif_upload`
        # unset this returns before making any request.
        await report_sarif_upload(tool_context)
        return str(written) if written else None


_PREP_PUBLISH_WAIT_S: float = 30.0
"""How long publication waits for a still-running dependency install.

A fraction of the publish stage's budget: an install that has not finished by
the time the review did is stopped rather than allowed to hold publication
(and the evidence packet) until the stage times out.
"""


async def _await_prep(promise: Any) -> object:
    return await promise


async def _prep_failure_reason(
    tool_context: ToolContext, *, wait_s: float | None = None
) -> str | None:
    """Return a reason string when review-relevant dependency prep failed (W6.1).

    Awaits an in-progress install before inspecting status, for at most
    ``wait_s`` seconds (``None`` waits until the install's own deadline). An
    install still running then is stopped (its process groups are killed) and
    reported as a reason, so the run is ``inconclusive``: the review ran
    without its dependencies.

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
            await asyncio.wait_for(_await_prep(state.promise), timeout=wait_s)
        except TimeoutError:
            cancel = getattr(state.promise, "cancel", None)
            if callable(cancel):
                cancel()
            return (
                f"dependency installation was still running {wait_s:g}s after the review "
                "finished and was stopped"
            )
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
    ctx.job_token = get_job_token()
    github_client = GitHubClient(ctx.job_token)
    ctx.scm = create_github_scm(ctx.job_token, client=github_client)
    run_context = await resolve_run_context_data(github_client)
    ctx.run_context = run_context
    try:
        # Prompt resolution builds ``ActionInputEnv`` (the prompt fields share the
        # model with the fail-closed tracing inputs), so it belongs inside this
        # guard too: a malformed ``INPUT_TRACING`` must map to
        # ``_ConfigurationError`` (→ ``configuration_error``), never fall through
        # to the generic ``infra_error`` bucket. Plain prompt-validation errors
        # are not ``EnvSettingsError`` and propagate exactly as before.
        resolved_prompt = resolve_prompt_input()
        ctx.resolved_prompt = resolved_prompt
        export_tracing_env_from_action_inputs()
        validate_env_settings()
    except EnvSettingsError as exc:
        # A malformed control-carrying setting fails configuration before any
        # subprocess or agent exists. ``_ConfigurationError`` maps to
        # ``RunOutcome.configuration_error``; the message names the variable
        # and never the value.
        raise _ConfigurationError(str(exc)) from exc
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
    # HS2 — read the capture flag once, at run start, so a mid-run env change
    # cannot turn verdict capture on or off partway through a review.
    from mergecraft.evidence.verdict_capture import capture_verdicts_enabled

    tool_state.capture_verdicts = capture_verdicts_enabled()
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

    ctx.setup_completed = True
    return ctx


def _composed_prompt_from_payload(ctx: RunContext) -> str | None:
    """Return the composed review prompt this run actually uses, if any (F1).

    The Action writes the workflow's composed ``steps.prompt.outputs.text`` to the
    ``prompt`` input; ``resolve_payload`` stores it at ``payload["prompt"]`` (a JSON
    dispatch payload keeps the same key). Returns ``None`` when no usable prompt is
    present, so the caller leaves the event untouched.
    """
    prompt = (ctx.payload or {}).get("prompt")
    return prompt if isinstance(prompt, str) and prompt.strip() else None


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
    assert ctx.run_context is not None

    from mergecraft.action.inputs import (
        ForkCredentialInvariantError,
        validate_fork_credential_invariant,
    )
    from mergecraft.agents.codex import CODEX_SANDBOX_UNSANDBOXED
    from mergecraft.config.settings_snapshot import capture_repo_settings_snapshot
    from mergecraft.config.trust_policy import (
        agent_sandbox_manifest_fields,
        bind_dispatch_review_prompt,
        bind_target_pull_request,
        bound_head_sha,
        default_branch_from_event,
        log_trust_policy_at_run_start,
        resolve_agent_sandbox_decision,
        resolve_trust_policy,
        trust_policy_manifest_fields,
        unbound_target_pull_number,
    )

    repo_root = Path.cwd()
    gh_event = ctx.gh_event or {}
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")

    # F1 (TB-D1) — the live dispatch review path composes "Review pull request
    # #<n>. …" into the Action's ``prompt`` input, so ``github.event.inputs.prompt``
    # holds only the operator's raw input (usually empty). Merge the composed prompt
    # into the event before the first trust read so a dispatch that names a PR is
    # floored as a fork until ``get_pull`` binds it — exactly as a comment-on-PR run
    # is. A dispatch that names no PR (and every non-dispatch event) is unchanged.
    gh_event = bind_dispatch_review_prompt(
        gh_event,
        event_name=event_name,
        prompt=_composed_prompt_from_payload(ctx),
    )
    ctx.gh_event = gh_event

    # TB-D2 — bind the target PR by fetching, once, before the first trust read.
    # A comment on a PR (`issue.pull_request`, no head) and a `workflow_dispatch`
    # that names a PR carry no head, so their fork status is unknown until the
    # SCM API answers. Fetch here and replace ``ctx.gh_event`` with the bound
    # event so the credential invariant, the trust policy and the sandbox
    # decision all read one bound event. A fetch failure leaves the event
    # unbound — floored as a fork — and is warned, never raised; the invariant
    # below turns that into a refusal when credentials are present (P-8).
    unbound_pull = unbound_target_pull_number(gh_event)
    if unbound_pull is not None:
        try:
            pull = await ctx.scm.get_pull(
                ctx.run_context.repo.owner, ctx.run_context.repo.name, unbound_pull
            )
        except Exception as exc:
            logger.warning(
                "could not bind pull request #{} for this run; leaving it unbound "
                "so the fork floor applies: {}",
                unbound_pull,
                exc,
            )
        else:
            _remember_pull_request(
                ctx, ctx.run_context.repo.owner, ctx.run_context.repo.name, unbound_pull, pull
            )
            gh_event = bind_target_pull_request(gh_event, pull)
            ctx.gh_event = gh_event
            # Dispatch events carry no PR number during setup. Keep the run and
            # tool state in sync with the fetched PR before reading its issues.
            bound_pull_number = pull.get("number")
            if isinstance(bound_pull_number, int):
                ctx.pr_number = bound_pull_number
                ctx.tool_state.pr_number = bound_pull_number

    try:
        validate_fork_credential_invariant(event=gh_event, env=os.environ, settings=ctx.settings)
    except ForkCredentialInvariantError as exc:
        raise _ConfigurationError(str(exc)) from exc

    # D7 — the same ``event_name`` read above for ``resolve_trust_policy``
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

    from mergecraft.config.env import RuntimeOverridesEnv

    operator_override_requested = RuntimeOverridesEnv().codex_sandbox == CODEX_SANDBOX_UNSANDBOXED
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

    # Resolve capability-dependent API permissions only after repository
    # settings have passed the trust-tier filter. The same resolved SARIF flag
    # is carried into ToolContext later; it must not be reinterpreted after the
    # App tokens have already been minted.
    sarif_upload_enabled = resolve_sarif_upload_enabled(
        action_input=ActionInputEnv().sarif_upload,
        repo_setting=settings.analyzers.sarif_upload,
    )
    ctx.sarif_upload_enabled = sarif_upload_enabled
    token_ref = await resolve_tokens(
        push=ctx.payload.get("push") or "restricted",
        xrepo=ctx.payload.get("xrepo"),
        primary_repo=f"{ctx.run_context.repo.owner}/{ctx.run_context.repo.name}",
        status_checks=bool(ctx.payload.get("statusChecks")),
        sarif_upload=sarif_upload_enabled,
    )
    ctx.token_ref = token_ref
    # Prefer MCP token for API calls. Closing the superseded job-token client is
    # best-effort: a failure must not sink the run (CR-D8), so it is logged once
    # and the MCP-token client is installed regardless.
    await _close_superseded_scm(ctx.scm)
    ctx.scm = create_github_scm(token_ref.mcp_token, client=GitHubClient(token_ref.mcp_token))
    await _read_linked_issues(ctx)

    return ctx


async def _read_linked_issues(ctx: RunContext) -> None:
    """Record the issues this pull request closes, with their authors, once, at run start.

    The ``requirements`` policy evidence producer maps their acceptance criteria
    against the diff and names their authors. A run without a pull request reads
    nothing and leaves ``ToolState.linked_issues`` at ``None``. A read that fails,
    is malformed or spans more than one page *writes* ``None`` ("not read"), so the
    evidence stays absent rather than treating the pull request as closing nothing.
    """
    tool_state = ctx.tool_state
    run_context = ctx.run_context
    if tool_state is None or run_context is None or ctx.pr_number is None or ctx.scm is None:
        return
    client = github_client_from_scm(ctx.scm)
    if client is None:
        tool_state.linked_issues = None
        return
    try:
        issues = await client.closing_issues(
            run_context.repo.owner, run_context.repo.name, int(ctx.pr_number)
        )
    except Exception as exc:  # an advisory read: a failure must never fail the run
        logger.warning(
            "linked issues of PR #{} could not be read; requirements evidence stays absent: {}",
            ctx.pr_number,
            exc,
        )
        tool_state.linked_issues = None
        return
    if issues is None:
        logger.warning(
            "linked issues of PR #{} were not fully read; requirements evidence stays absent",
            ctx.pr_number,
        )
    tool_state.linked_issues = issues


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
    tool_state.model = resolved_model or payload.get("model")

    from mergecraft.utils.agent_resolve import collect_roster_credential_degradations

    degradations = collect_roster_credential_degradations(
        settings=settings,
        cwd=Path.cwd(),
        model_head=ctx.model_head,
        model_pin=ctx.model_pin,
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


def _agent_timeout_ms(ctx: RunContext) -> int | None:
    """Return the agent deadline: the run timeout minus setup elapsed (S1 / F6).

    A slow setup must NOT silently extend the total run deadline, so its
    wall-clock duration comes out of the agent's share. ``None`` means the
    run has no timeout.
    """
    if ctx.timeout_ms is None:
        return None
    return max(1, int(ctx.timeout_ms - ctx.setup_elapsed_s * 1000))


def _render_run_modes(ctx: RunContext, agent_id: AgentId) -> list[Mode]:
    """Render built-in plus custom modes for ``agent_id`` with this run's budgets."""
    assert ctx.settings is not None
    settings = ctx.settings
    agent_timeout_ms = _agent_timeout_ms(ctx)
    return [
        *compute_modes(
            agent_id,
            inline_budget=settings.analyzers.inline_budget,
            time_budget_minutes=None if agent_timeout_ms is None else agent_timeout_ms // 60_000,
        ),
        *_custom_modes(settings.modes),
    ]


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

    modes = _render_run_modes(ctx, ctx.agent_id)
    tool_state.modes = modes
    ctx.modes = modes
    output_schema = resolve_output_schema()
    ctx.output_schema = output_schema

    ctx_payload = _payload_to_ctx(payload)
    ctx.ctx_payload = ctx_payload
    analyzers_mode = resolve_analyzers_mode(ActionInputEnv().analyzers)
    ctx.analyzers_mode = analyzers_mode
    sarif_upload_enabled = ctx.sarif_upload_enabled
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
        ci_coverage_artifacts=list(settings.ci_evidence.coverage_artifacts),
        ci_mutation_artifacts=list(settings.ci_evidence.mutation_artifacts),
        analyzers_mode=analyzers_mode,
        trust_tier=ctx.trust_tier,
        authority_trust=ctx.authority_trust,
        analyzers_settings_enabled=settings.analyzers.enabled,
        sarif_upload_enabled=sarif_upload_enabled,
        run_id=int(os.environ["GITHUB_RUN_ID"]) if os.environ.get("GITHUB_RUN_ID") else None,
        job_id=os.environ.get("GITHUB_JOB"),
        oss=run_context.oss,
        resolved_model=ctx.resolved_model,
        suggest_eval_add=bool(payload.get("suggestEvalAdd")),
        budget_tracker=ctx.budget_tracker,
        gh_event=ctx.gh_event,
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
    tool_state.phase_elapsed_s["setup"] = round(setup_elapsed_s, 3)


async def _run_start_instruction_scope(
    ctx: RunContext,
) -> tuple[list[str], ReviewSettings | None]:
    """Resolve ranking paths and config for the bound PR before any harness runs."""
    from mergecraft.config.trust_policy import bound_head_sha
    from mergecraft.review_policy.ignore_paths import _base_review_settings, _event_base_sha

    event = ctx.gh_event or {}
    pull = event.get("pull_request")
    if not isinstance(pull, dict):
        return [], None
    assert ctx.tool_context is not None
    scm, repo = ctx.tool_context.scm, ctx.tool_context.repo
    base_sha = _event_base_sha(event)
    review = None
    if base_sha:
        review, _source, _detail = await _base_review_settings(scm, repo.owner, repo.name, base_sha)
    review = review if review is not None else ReviewSettings()

    head_sha = bound_head_sha(event, event_name=os.environ.get("GITHUB_EVENT_NAME", ""))
    number = pull.get("number")
    if not base_sha or not head_sha or not isinstance(number, int):
        return [], review
    paths = await list_pull_request_paths(
        scm, repo.owner, repo.name, number, head_sha=head_sha, base_sha=base_sha
    )
    return paths or [], review


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

    # The setup script ran after ``_build_run_tool_context`` rendered the modes;
    # re-render so ``${TIME_BUDGET}`` states the deadline net of its elapsed time.
    if ctx.setup_elapsed_s:
        modes = _render_run_modes(ctx, ctx.agent_id)
        ctx.modes = modes
        tool_state.modes = modes
        tool_context.modes = modes

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

    from mergecraft.review.consumer_mcp import load_consumer_mcp_servers

    repo_root = Path.cwd()
    trust_tier = str(tool_state.trust_tier or "untrusted")
    consumer_mcp = load_consumer_mcp_servers(
        repo_root,
        configured=list(settings.review.mcp_servers),
        trust_tier=trust_tier,
    )
    tool_state.review_mcp_names = tuple(server.name for server in consumer_mcp)
    tool_state.review_mcp_servers = tuple(consumer_mcp)
    changed_paths, review_instruction_settings = await _run_start_instruction_scope(ctx)
    instructions = resolve_instructions(
        payload=payload,
        repo=run_context.repo,
        modes=ctx.modes,
        agent_id=ctx.agent_id,
        output_schema=ctx.output_schema,
        learnings_file_path=tool_state.learnings_file_path,
        learnings_headings=settings.learnings_headings,
        setup_hook_failure=ctx.setup_hook_failure,
        setup_script_skip_reason=ctx.setup_script_skip_reason,
        xrepo_brief=settings.xrepo_brief,
        xrepo_learnings_file_path=tool_state.xrepo_learnings_file_path,
        xrepo_learnings_headings=settings.xrepo_learnings_headings,
        repo_root=repo_root,
        trust_tier=trust_tier,
        review_mcp_names=list(tool_state.review_mcp_names),
        changed_paths=changed_paths,
        review_instruction_settings=review_instruction_settings,
    )
    ctx.run_start_instructions = {str(ctx.agent_id): instructions}
    for other_agent_id in _run_start_harnesses(ctx):
        if other_agent_id in ctx.run_start_instructions:
            continue
        ctx.run_start_instructions[other_agent_id] = _render_agent_instructions(
            ctx,
            agent_id=other_agent_id,
            modes=_render_run_modes(ctx, other_agent_id),  # type: ignore[arg-type]  # — str from Agent.name is an AgentId at runtime
            repo_root=repo_root,
            changed_paths=changed_paths,
            review_instruction_settings=review_instruction_settings,
        )
    tool_state.review_skill_paths = tuple(
        str(item) for item in instructions.extra.get("review_skills") or []
    )
    tool_state.review_skills_ledger = tuple(
        str(item) for item in instructions.extra.get("review_skills_ledger") or []
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
        idle_timeout_s=float(settings.agent_idle_timeout_s),
    )


def _render_agent_instructions(
    ctx: RunContext,
    *,
    agent_id: str,
    modes: list[Mode],
    repo_root: Path,
    changed_paths: Sequence[str],
    review_instruction_settings: ReviewSettings | None,
) -> Any:
    """Render one harness's instructions with this run's run-start inputs."""
    assert ctx.settings is not None
    assert ctx.run_context is not None
    assert ctx.tool_state is not None
    settings = ctx.settings
    tool_state = ctx.tool_state
    return resolve_instructions(
        payload=ctx.payload,
        repo=ctx.run_context.repo,
        modes=modes,
        agent_id=agent_id,
        output_schema=ctx.output_schema,
        learnings_file_path=tool_state.learnings_file_path,
        learnings_headings=settings.learnings_headings,
        setup_hook_failure=ctx.setup_hook_failure,
        setup_script_skip_reason=ctx.setup_script_skip_reason,
        xrepo_brief=settings.xrepo_brief,
        xrepo_learnings_file_path=tool_state.xrepo_learnings_file_path,
        xrepo_learnings_headings=settings.xrepo_learnings_headings,
        repo_root=repo_root,
        trust_tier=str(tool_state.trust_tier or "untrusted"),
        review_mcp_names=list(tool_state.review_mcp_names),
        changed_paths=changed_paths,
        review_instruction_settings=review_instruction_settings,
    )


def _run_start_harnesses(ctx: RunContext) -> list[str]:
    """Harness names any attempt or server-side reviewer of this run may run under.

    Resolved at run start, before the first attempt can check the reviewed
    head out into the workspace, so each harness's instructions are rendered
    from the tree the run started on. A slug or binding that cannot be resolved
    here is skipped: an attempt on it would fail to resolve its agent anyway,
    and a reviewer on it is refused for want of run-start instructions.
    """
    assert ctx.settings is not None
    settings = ctx.settings
    harnesses: list[str] = []

    def _add(model: str | None) -> None:
        try:
            agent = resolve_runtime_agent(
                model=resolve_model(slug=model, respect_env_override=False) if model else None,
                settings=settings,
            )
        except Exception as exc:  # an unresolvable rung renders nothing; it cannot run
            logger.debug("run-start instructions: no harness for {!r}: {}", model, exc)
            return
        if agent.name not in harnesses:
            harnesses.append(str(agent.name))

    if ctx.use_model_chain:
        for slug in ctx.chain_for_decision:
            _add(slug)
    if ctx.tool_context is not None and ctx.tool_state is not None:
        try:
            from mergecraft.agents.registry import AgentRole, load_registry, resolve_agent_model
            from mergecraft.config.settings_snapshot import repo_settings_from_context

            roster_settings = repo_settings_from_context(ctx.tool_context)
            registry = load_registry(settings=roster_settings, repo_root=Path.cwd())
            reviewers = registry.resolve_roles(AgentRole.reviewer)
        except Exception as exc:  # no roster to render for
            logger.debug("run-start instructions: roster unavailable: {}", exc)
            reviewers = ()
        for binding in reviewers:
            try:
                slug = resolve_agent_model(binding, settings=roster_settings).dispatched_model
            except Exception as exc:  # an unresolvable binding is refused at dispatch
                logger.debug("run-start instructions: binding {}: {}", binding.agent_id, exc)
                continue
            _add(slug)
    return harnesses


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
    chain_for_decision = ctx.chain_for_decision
    output_schema = ctx.output_schema
    # Slice 6 — keep the watchdog diagnostic so the packet and the check
    # summary can name *what* stalled, not only that the clock expired.
    if (result.metadata or {}).get("idle_timeout"):
        tool_state.agent_diagnostic = dict(result.metadata)

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
        executed = resolved_model or winning_slug
        promote_model_evidence(
            tool_state,
            requested_model=requested,
            executed_model=executed if isinstance(executed, str) else winning_slug,
            fallback_index=fallback_index,
        )

    if result.usage:
        from mergecraft.agents.curated_model_catalog import apply_catalog_cost_to_usage

        usage = apply_catalog_cost_to_usage(result.usage, model=tool_state.model)
        if usage is not None:
            result = replace(result, usage=usage)
        tool_state.usage_entries.append(result.usage)
        from mergecraft.utils.run_bounds import BudgetExhausted, record_agent_usage

        try:
            record_agent_usage(ctx.budget_tracker, result.usage, phase="reviewer_dispatch")
        except BudgetExhausted as exc:
            ctx.budget_exhaustion = exc

    from mergecraft.utils.llm_review_timing import snapshot_llm_review_timing

    timing_snapshot = snapshot_llm_review_timing()
    if timing_snapshot is not None and tool_state.selected_mode in {"Review", "IncrementalReview"}:
        tool_state.llm_review_timing = timing_snapshot

    if output_schema and result.success:
        # Classified by the shared resolver (inconclusive), the same way the
        # offline review reads a missing ``set_output`` — not as a crash.
        from mergecraft.review.outcome_resolution import structured_output_error

        ctx.structured_output_error = structured_output_error(tool_state.output)

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
    tool_state = ctx.tool_state
    tool_context = ctx.tool_context
    run_ctx = ctx.run_ctx
    agent = ctx.agent
    agent_id = ctx.agent_id
    model_head = ctx.model_head
    model_pin = ctx.model_pin
    use_model_chain = ctx.use_model_chain
    selected_slug = ctx.selected_slug
    output_schema = ctx.output_schema

    from mergecraft.utils.llm_review_timing import bind_llm_review_timing_tracker

    # The reviewer normally selects its mode during dispatch. Bind before the
    # task is created so its first generation and every secondary share a tracker.
    bind_llm_review_timing_tracker()

    async def _run_agent_once(slug: str) -> AgentResult:
        attempt_model = resolve_model(slug=slug, respect_env_override=False)
        attempt_agent = resolve_runtime_agent(model=attempt_model, settings=settings)
        attempt_agent_id = attempt_agent.name

        if attempt_agent_id == agent_id:
            attempt_ctx = replace(run_ctx, resolved_model=attempt_model)
        else:
            attempt_modes = _render_run_modes(ctx, attempt_agent_id)
            # Every attempt reuses the instructions resolved at run start; an
            # earlier attempt may have checked the reviewed head out into the
            # workspace, so nothing is re-rendered from the tree now.
            attempt_instructions = ctx.run_start_instructions.get(str(attempt_agent_id))
            if attempt_instructions is None:
                return AgentResult(
                    success=False,
                    error=(
                        f"no instructions were resolved at run start for harness "
                        f"{attempt_agent_id!r}; the attempt does not run"
                    ),
                    metadata={"retryable": True},
                )
            # ``ToolContext`` has a custom ``__init__``, so ``dataclasses.replace``
            # cannot copy it; evaluate the denied sets under the attempt's id.
            previous_agent_id = tool_context.agent_id
            tool_context.agent_id = attempt_agent_id
            try:
                attempt_denied = subagent_denied_tool_names(tool_context, output_schema)
                attempt_verifier_denied = verifier_denied_tool_names(tool_context, output_schema)
            finally:
                tool_context.agent_id = previous_agent_id
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

    from mergecraft.agents.token_budget import (
        bind_run_budget,
        current_run_budget,
        token_budget_for,
    )
    from mergecraft.jev.types import PINNED_MODEL

    provider_budget = current_run_budget() or token_budget_for(
        model=ctx.resolved_model or PINNED_MODEL,
        max_tokens=ctx.run_bounds.token_budget if ctx.run_bounds is not None else 250_000,
    )
    with bind_run_budget(provider_budget):
        agent_task = asyncio.create_task(_dispatch_selected_agent())

        # S1 / F6 — deduct the setup-script elapsed time from the agent
        # deadline. A slow setup must NOT silently extend the total run
        # deadline. ``setup_elapsed_s`` is the wall-clock duration measured
        # by the bounded setup block above; ``timeout_ms`` is the
        # pre-deduction run budget.
        timeout_ms = ctx.timeout_ms
        agent_timeout_ms = _agent_timeout_ms(ctx)
        if agent_timeout_ms is not None and agent_timeout_ms != timeout_ms:
            logger.info(
                "» deducted setup elapsed {:.2f}s from agent deadline ({}s -> {}s)",
                ctx.setup_elapsed_s,
                (timeout_ms or 0) / 1000,
                agent_timeout_ms / 1000,
            )

        # Stamped unconditionally (deadline or not) so a record rendered
        # mid-dispatch — inside the terminal publish call — can report the
        # agent phase as elapsed-so-far instead of 0s (#1075).
        tool_state.agent_started_monotonic = time.monotonic()
        if agent_timeout_ms is None:
            winning_slug, result = await agent_task
        else:
            agent_started = tool_state.agent_started_monotonic
            ctx.agent_deadline_monotonic = agent_started + agent_timeout_ms / 1000.0
            # The MCP server reads these to tell the agent how much time it has used.
            tool_state.agent_deadline_s = agent_timeout_ms / 1000.0
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


def _is_completed_review(review: dict[str, Any]) -> bool:
    """Recognize already-authenticated history for frequency, never approval."""
    import re

    from mergecraft.findings.ledger import DETERMINISTIC_RECORD_MARKER, REVIEW_BODY_MARKER

    commit = review.get("commit_id")
    if not isinstance(commit, str) or re.fullmatch(r"[0-9a-fA-F]{40}", commit) is None:
        return False
    state = str(review.get("state")).upper()
    if state in {"APPROVED", "CHANGES_REQUESTED"}:
        return True
    if state != "COMMENTED":
        return False
    body = str(review.get("body") or "").lstrip()
    if not body.startswith(f"{DETERMINISTIC_RECORD_MARKER}\n### mergeCraft run record\n"):
        return False
    record, separator, _prose = body.partition(REVIEW_BODY_MARKER)
    if not separator:
        return False
    header, boundary, _pre_merge = record.partition("\n### Pre-merge checks\n")
    lines = header.splitlines()
    if not boundary or len(lines) < 6:
        return False
    if "- **Publication path:** `publish_pull_request_review`" not in lines or any(
        line.startswith(("- **Tier:** skip", "- **Tier:** lite")) for line in lines
    ):
        return False
    # The renderer writes these fields before any variable record content.
    outcome, diagnostic, decision = lines[3:6]
    return (
        outcome == "- **Outcome:** `passed`"
        and diagnostic == "- **Verdict diagnostic:** `approved`"
        and decision.startswith("- **Decision:** `success` — ")
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


async def _publish_policy_skip(ctx: RunContext, reason: str) -> MainResult:
    """Publish a head-bound record of a deliberate no-op and neutral checks."""
    tool_context = ctx.tool_context
    assert tool_context is not None
    from mergecraft.config.trust_policy import bound_head_sha
    from mergecraft.mcp.tool_state import primary_repo_state

    head_sha = bound_head_sha(
        ctx.gh_event or {}, event_name=os.environ.get("GITHUB_EVENT_NAME", "")
    )
    if not head_sha:
        return MainResult(
            success=False,
            error="Cannot record a review policy skip without a bound PR head.",
            outcome=RunOutcome.inconclusive,
        )
    primary_repo_state(tool_context.tool_state).checkout_sha = head_sha
    # Unavailable draft-lite work stays inconclusive and cannot use the
    # workflow exception for an explicit policy decision to run no review.
    triage = (
        TriageDecision(tier="skip", recognizer="reviewPolicy", reason=reason)
        if ctx.automatic_review == "skip"
        else TriageDecision(tier="lite", recognizer=None, reason=reason)
    )
    tool_context.tool_state.triage = triage

    sink_error = _scan_sinks_after_run(ctx)
    packet_path = None
    packet = None
    if sink_error is None:
        packet = resolve_prepared_run_packet(tool_context, run_succeeded=False)
        if (
            packet is not None
            and packet.decision is not None
            and packet.decision.verdict == "neutral"
            and packet.reviewed_head_sha == head_sha
        ):
            packet_path = await asyncio.to_thread(emit_run_packet, tool_context, packet=packet)
            if packet_path is not None:
                sink_error = _scan_sinks_after_run(ctx, extra_paths=[packet_path])

    if sink_error is not None or packet_path is None:
        error = sink_error or "Could not record the review policy skip in the evidence packet."
        await report_status_checks(
            tool_context,
            run_succeeded=False,
            conclusion="failure",
            failure_reason=error,
            approval_failure_reason=sink_error,
        )
        return MainResult(success=False, error=error, outcome=RunOutcome.failed)

    await report_status_checks(
        tool_context,
        run_succeeded=False,
        conclusion="neutral",
        failure_reason=reason,
        packet=packet,
    )
    logger.info("» {}", reason)
    return MainResult(
        success=True,
        output=reason,
        result=reason,
        outcome=RunOutcome.inconclusive,
        evidence_packet_path=str(packet_path),
    )


async def _run_draft_lite(ctx: RunContext) -> SkipAgentReview | LiteAgentReview:
    """Run the capped draft review or stop without escalating to a full review."""
    assert ctx.draft_lite_settings is not None
    assert ctx.tool_context is not None
    assert ctx.tool_state is not None
    settings = ctx.draft_lite_settings
    lite = settings.review.fast_path.lite
    unavailable = SkipAgentReview(
        reason="Draft lite review skipped: a capped call was unavailable."
    )
    if not lite.enabled or lite_model_slug(settings) is None:
        return unavailable

    from mergecraft.config.trust_policy import bound_head_sha
    from mergecraft.fast_path import _read_diff
    from mergecraft.mcp.tool_state import primary_repo_state
    from mergecraft.review_policy.ignore_paths import _event_base_sha

    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    head_sha = bound_head_sha(ctx.gh_event or {}, event_name=event_name)
    pull_number = ctx.tool_context.payload.event.issue_number
    base_sha = _event_base_sha(ctx.gh_event)
    if not head_sha or not base_sha or not isinstance(pull_number, int):
        return SkipAgentReview(reason="Draft lite review skipped: no bound pull request revision.")
    scm, repo = ctx.tool_context.scm, ctx.tool_context.repo
    number = pull_number

    async def revision_matches() -> bool:
        pull = await scm.get_pull(repo.owner, repo.name, number)
        event = {"pull_request": pull}
        return (
            bound_head_sha(event, event_name=event_name).casefold() == head_sha.casefold()
            and _event_base_sha(event).casefold() == base_sha.casefold()
        )

    changed = SkipAgentReview(
        reason="Draft lite review skipped: the pull request revision changed."
    )
    try:
        if not await revision_matches():
            return changed
        diff, _paths = await _read_diff(scm, repo.owner, repo.name, number)
        if not await revision_matches():
            return changed
    except Exception as exc:
        logger.info("Draft lite diff unavailable ({})", type(exc).__name__)
        return SkipAgentReview(
            reason="Draft lite review skipped: the pull request diff is unavailable."
        )
    decision = TriageDecision(
        tier="lite",
        recognizer=None,
        reason=ctx.automatic_review_reason,
        token_cap=lite.token_cap,
    )
    primary_repo_state(ctx.tool_state).checkout_sha = head_sha
    ctx.tool_state.triage = decision
    result = await _run_lite_tier(ctx, decision, diff_text=diff, draft_settings=settings)
    return result or unavailable


async def _triage_gate(ctx: RunContext) -> SkipAgentReview | LiteAgentReview | None:
    """Deterministic pre-dispatch triage (``review.fastPath``): skip the agent when certain.

    Returns ``SkipAgentReview`` for a ``skip`` tier and ``LiteAgentReview`` for a
    ``lite`` tier whose single capped call ran (``reviewed`` or ``failed``). A ``lite``
    call the driver ``downgraded`` (over the cap, no credential) returns ``None`` and
    records a ``full`` decision carrying the downgrade reason, so the run gets the
    normal review. Off by default; the config is honoured only when it is the
    operator's base-side config. The pull request is read once, and the ``lite``
    driver gets exactly the diff the decision was made from. The decision is
    recorded on the run (packet, check summaries, shadow log) whenever the gate was
    evaluated, and any doubt is ``full``. The PR's title, body, labels and head-side
    config are never read. With ``review.fastPath.reapproval`` enabled, the
    re-approval proof (:func:`_reapproval_gate`) runs first and may return a
    ``SkipAgentReview`` that carries a trusted prior pass over to this head.
    """
    assert ctx.settings is not None
    assert ctx.tool_state is not None
    config = ctx.settings.review.fast_path
    if not config.enabled:
        return None
    event = ctx.gh_event if isinstance(ctx.gh_event, dict) else {}
    pull = event.get("pull_request")
    if not isinstance(pull, dict) or not isinstance(pull.get("number"), int):
        return None
    head = pull.get("head")
    head_sha = str(head.get("sha") or "") if isinstance(head, dict) else ""
    assert ctx.tool_context is not None
    repo = ctx.tool_context.repo
    if config.reapproval.enabled and ctx.settings_snapshot_operator_owned:
        reapproved = await _reapproval_gate(ctx, int(pull["number"]), head_sha)
        if reapproved is not None:
            return reapproved
    decision, inputs = await triage_pull_request(
        ctx.tool_context.scm,
        repo.owner,
        repo.name,
        int(pull["number"]),
        head_sha,
        config=config,
        operator_owned=ctx.settings_snapshot_operator_owned,
        loader=load_triage_inputs,
        instruction_extra_filenames=ctx.settings.review.instruction_extra_filenames,
    )
    ctx.tool_state.triage = decision
    if decision.tier == "lite" and inputs is not None:
        return await _run_lite_tier(ctx, decision, diff_text=inputs.diff_text)
    if decision.tier != "skip":
        return None
    logger.warning("» {} — {}", decision.record_line(), decision.reason)
    gha_log.warning(decision.record_line())
    return SkipAgentReview(reason=decision.reason)


async def _reapproval_gate(
    ctx: RunContext, pull_number: int, head_sha: str
) -> SkipAgentReview | None:
    """Carry a trusted prior pass over to this head when only changelog prose moved (#1284).

    Returns ``SkipAgentReview`` when :func:`mergecraft.reapproval.evaluate_reapproval`
    proves the prior pass applies, and records the ``skip`` / ``reapproval`` tier and
    its record so the checks publish the reused verdict on this exact head. ``None``
    otherwise: the normal triage and review run. Either way the run's review stamp
    (pull request, target branch, review-policy digest) is recorded, so this run's own
    approval check can seed a later re-approval.
    """
    assert ctx.settings is not None
    assert ctx.tool_state is not None
    assert ctx.tool_context is not None
    from mergecraft import __version__
    from mergecraft.classify.reapproval import APPROVAL_CHECK_NAME, REAPPROVAL_RECOGNIZER
    from mergecraft.mcp.checkout import list_mergecraft_reviews
    from mergecraft.reapproval import evaluate_reapproval, workflow_path_from_ref

    tool_context = ctx.tool_context
    repo = tool_context.repo

    async def _reviews() -> list[dict[str, Any]]:
        return await list_mergecraft_reviews(tool_context, pull_number=pull_number)

    outcome = await evaluate_reapproval(
        tool_context.scm,
        repo.owner,
        repo.name,
        pull_number,
        head_sha,
        config=ctx.settings.review.fast_path.reapproval,
        list_reviews=_reviews,
        workflow_path=workflow_path_from_ref(os.environ.get("GITHUB_WORKFLOW_REF")),
        version=__version__,
    )
    ctx.tool_state.review_stamp = outcome.stamp
    record = outcome.verdict.record
    if record is None:
        logger.info("» re-approval: normal review — {}", outcome.verdict.reason)
        return None
    ctx.tool_state.reapproval = record
    decision = TriageDecision(
        tier="skip",
        recognizer=REAPPROVAL_RECOGNIZER,
        reason=record.reason(),
        relied_on_checks=(f"{APPROVAL_CHECK_NAME}@{record.prior_head_sha}",),
    )
    ctx.tool_state.triage = decision
    logger.warning("» {} — {}", decision.record_line(), decision.reason)
    gha_log.notice(f"mergeCraft: {decision.reason} (prior review: {record.prior_url})")
    return SkipAgentReview(reason=decision.reason)


async def _run_lite_tier(
    ctx: RunContext,
    decision: TriageDecision,
    *,
    diff_text: str,
    draft_settings: RepoSettings | None = None,
) -> LiteAgentReview | None:
    """Run the ``lite`` tier's single call; ``None`` (a full review) when it downgraded.

    Findings are recorded twice. The checks fail through the packet findings: compact
    ``tool="lite"`` rows on ``agent_findings``, which
    :func:`mergecraft.evidence.merge.lite_row_finding` expands, so a Critical or Major
    one fails the checks like any review finding. The roster record
    (``record_reviewer_dispatch_run(agent_id="lite")``) is kept separately as the
    provenance of who raised them. The driver is reached through this module's
    ``run_lite_review`` binding.
    """
    assert ctx.settings is not None
    assert ctx.tool_state is not None
    tool_state = ctx.tool_state
    settings = draft_settings if draft_settings is not None else ctx.settings
    try:
        outcome = await run_lite_review(decision=decision, diff_text=diff_text, settings=settings)
    except Exception as err:  # the driver is total; a bug in it must not crash the run
        logger.warning("» lite review raised {}: the run is inconclusive", type(err).__name__)
        outcome = LiteOutcome(
            status="failed", reason=f"the lite review raised {type(err).__name__}"
        )
    if draft_settings is not None and outcome.status == "failed":
        return None
    if outcome.status == "downgraded":
        if draft_settings is None:
            tool_state.triage = TriageDecision(tier="full", recognizer=None, reason=outcome.reason)
            logger.warning("» Tier: full — lite downgraded: {}", outcome.reason)
        return None
    model_slug = outcome.model_slug or lite_model_slug(settings)
    if outcome.model_slug is None and model_slug is not None:
        outcome = replace(outcome, model_slug=model_slug)
    tool_state.lite_review = outcome
    if outcome.findings:
        from mergecraft.mcp.tool_state import record_reviewer_dispatch_run

        rows = [dict(finding) for finding in outcome.findings]
        record_reviewer_dispatch_run(
            tool_state, agent_id="lite", findings=rows, model_slug=model_slug
        )
        tool_state.agent_findings.extend(_lite_finding_rows(outcome))
    logger.warning("» {} — {} ({})", decision.record_line(), outcome.reason, outcome.status)
    gha_log.warning(decision.record_line())
    return LiteAgentReview(decision=decision, outcome=outcome)


def _lite_finding_rows(outcome: LiteOutcome) -> list[dict[str, Any]]:
    """Compact ``lite`` rows for the packet, so a lite blocker reaches the gate.

    :func:`mergecraft.evidence.merge.lite_row_finding` expands them into findings.
    """
    from mergecraft.evidence.merge import LITE_FINDING_TOOL

    return [
        {
            "tool": LITE_FINDING_TOOL,
            "rule_id": "lite-review",
            "severity": item["severity"],
            "path": item["path"],
            "line": item["line"],
            "message": item["message"],
        }
        for item in outcome.findings
    ]


def _lite_record_summary(outcome: LiteOutcome | None) -> str | None:
    """The lite model's summary for the deterministic record, with record markers stripped.

    The full-review path strips forged or stale deterministic-record markers from
    agent prose before it is rendered; a lite summary is model output too.
    """
    from mergecraft.findings.ledger import _strip_deterministic_record_markers

    summary = getattr(outcome, "summary", None)
    if not summary:
        return None
    return _strip_deterministic_record_markers(str(summary)) or None


def _lite_completion_conclusion(
    tool_state: ToolState, prepared: Any, *, outcome_conclusion: CompletionConclusion
) -> tuple[CompletionConclusion, str | None] | None:
    """The ``mergecraft`` check for a ``lite`` run, and the lead its summary states.

    ``None`` when the run was not a ``lite`` run. A Critical or Major finding fails the
    check whatever else happened (a cap overrun never softens a blocker); otherwise a
    clean completion is ``neutral``, never ``success``, because a lite call is triage,
    not a review. Any other outcome conclusion (``neutral`` for ``inconclusive``,
    ``failure``) is kept.
    """
    triage = tool_state.triage
    if tool_state.lite_review is None or getattr(triage, "tier", None) != "lite":
        return None
    from mergecraft.agents.gates import blocking_findings

    blockers = blocking_findings(list(getattr(prepared, "findings", None) or []))
    if blockers and outcome_conclusion in {"success", "neutral"}:
        noun = "finding" if len(blockers) == 1 else "findings"
        return "failure", f"The lite review raised {len(blockers)} blocking {noun}."
    if outcome_conclusion == "success":
        return "neutral", "The lite review finished; approval is left to a human."
    return outcome_conclusion, None


def _lite_inconclusive_reason(outcome: LiteOutcome) -> str | None:
    """Why a ``lite`` run is ``inconclusive``: a failed call, or usage over the cap."""
    if outcome.status == "failed":
        return f"the lite review failed: {outcome.reason}"
    if outcome.cap_hit:
        return (
            f"the lite review used {outcome.tokens_used} tokens, over its cap; "
            "its result is not trusted"
        )
    return None


_IGNORE_SKIP_EVENTS: frozenset[str] = frozenset({"pull_request", "pull_request_target"})


def _pull_snapshot_key(
    owner: str, repo: str, number: int, pull: dict[str, Any]
) -> tuple[str, str, int, str, str] | None:
    head, base = pull.get("head"), pull.get("base")
    head_sha = head.get("sha") if isinstance(head, dict) else None
    base_sha = base.get("sha") if isinstance(base, dict) else None
    if (
        not isinstance(head_sha, str)
        or not head_sha
        or not isinstance(base_sha, str)
        or not base_sha
    ):
        return None
    return owner, repo, number, head_sha.lower(), base_sha.lower()


def _remember_pull_request(
    ctx: RunContext, owner: str, repo: str, number: int, pull: dict[str, Any]
) -> None:
    """Keep the initial API payload as author data, outside the trust-binding event."""
    snapshots = getattr(ctx, "pull_request_snapshots", None)
    key = _pull_snapshot_key(owner, repo, number, pull)
    if snapshots is not None and key is not None and pull.get("number") == number:
        snapshots[key] = deepcopy(pull)


async def _fetch_pull_request(
    ctx: RunContext, pull: dict[str, Any], *, what: str
) -> dict[str, Any]:
    """Reuse the run's bound PR snapshot or read it once through the SCM.

    *what* names the field the caller is after, for the error. Raises when the
    read fails or there is no SCM to read with, so the caller records what it
    could not see rather than silently reading an empty value.
    """
    scm = getattr(ctx, "scm", None)
    tool_context = getattr(ctx, "tool_context", None)
    if scm is None and tool_context is not None:
        scm = getattr(tool_context, "scm", None)
    repo = getattr(getattr(ctx, "run_context", None), "repo", None)
    if repo is None and tool_context is not None:
        repo = getattr(tool_context, "repo", None)
    raw_number = pull.get("number")
    number = raw_number if isinstance(raw_number, int) else ctx.pr_number
    if scm is None or repo is None or number is None:
        msg = f"the pull request {what} is not in the event and cannot be read"
        raise RuntimeError(msg)
    key = _pull_snapshot_key(repo.owner, repo.name, int(number), pull)
    snapshots = getattr(ctx, "pull_request_snapshots", {})
    if key is not None and key in snapshots:
        return deepcopy(snapshots[key])
    fetched = await scm.get_pull(repo.owner, repo.name, int(number))
    if not isinstance(fetched, dict):
        return {}
    _remember_pull_request(ctx, repo.owner, repo.name, int(number), fetched)
    return fetched


async def _fetch_pull_request_body(ctx: RunContext, pull: dict[str, Any]) -> str | None:
    """Read the pull request's description through the SCM (one ``get_pull``).

    Raises when the read fails or there is no SCM to read with, so the caller
    records the scope as unknown rather than skipping a body it could not see.
    """
    body = (await _fetch_pull_request(ctx, pull, what="body")).get("body")
    return body if isinstance(body, str) else None


async def _resolve_run_pull_request_metadata(ctx: RunContext) -> None:
    """Record the pull request's title and label names on the run state (#1056 part 5).

    A ``pull_request`` the run bound itself (the comment trigger, a PR-naming
    ``workflow_dispatch``) carries only ``number``/``head``/``base``, and a dispatch
    payload has no title either, so fix detection would see neither a ``fix:`` title
    nor a ``bug`` label and an unproven fix would pass as ``fix.not-required``. The
    title and labels are taken from the raw event when it has them
    (``pull_request.*``, or ``issue.*`` on a comment on a pull request) and read
    through the SCM once otherwise, onto ``ToolState.pull_request_title`` and
    ``ToolState.pull_request_labels``. Never fails the run: a read that fails leaves
    both ``None`` and is logged, so detection falls back to whatever the payload
    carries. Author inputs only ever add the requirement.
    """
    if ctx.tool_state is None:
        return
    from mergecraft.evidence.run_packet import (
        event_pull_request_labels,
        event_pull_request_title,
    )

    event = ctx.gh_event if isinstance(ctx.gh_event, dict) else {}
    title = event_pull_request_title(event)
    labels = event_pull_request_labels(event)
    if title is None or labels is None:
        pull = event.get("pull_request")
        if not isinstance(pull, dict):
            return
        try:
            fetched = await _fetch_pull_request(ctx, pull, what="title and labels")
        except Exception as err:  # fix detection keeps the payload's inputs, never crashes the run
            logger.warning(
                "fix_labels: the pull request's title and labels could not be read; "
                "fix detection uses the event's inputs only: {}",
                err,
            )
            return
        read = {"pull_request": fetched}
        if title is None:
            title = event_pull_request_title(read)
        if labels is None:
            labels = event_pull_request_labels(read)
        if title is None and labels is None:
            logger.warning(
                "fix_labels: the pull request read carries neither title nor labels; "
                "fix detection uses the event's inputs only"
            )
            return
    if title is not None:
        ctx.tool_state.pull_request_title = title
    if labels is not None:
        ctx.tool_state.pull_request_labels = tuple(labels)


async def _pull_request_body(ctx: RunContext) -> str | None:
    """The pull request's own description, never a comment body.

    Read from the raw event: ``pull_request.body`` on pull-request and review
    comment events, ``issue.body`` on a comment on a pull request. A
    ``pull_request`` the run bound itself (the comment trigger, a PR-naming
    ``workflow_dispatch``) carries no ``body`` key, so the pull request is read
    through the SCM once; a failed read raises. The resolved payload's
    ``event.body`` is the comment for comment triggers, so it is used only for a
    pull-request trigger.
    """
    event = ctx.gh_event if isinstance(ctx.gh_event, dict) else {}
    pull = event.get("pull_request")
    if isinstance(pull, dict):
        if "body" not in pull:
            return await _fetch_pull_request_body(ctx, pull)
        body = pull.get("body")
        return body if isinstance(body, str) else None
    issue = event.get("issue")
    if isinstance(issue, dict) and issue.get("pull_request") is not None:
        body = issue.get("body")
        return body if isinstance(body, str) else None
    resolved = ctx.ctx_payload
    if resolved is not None and resolved.event.is_pr:
        trigger = resolved.event.trigger
        if trigger.startswith("pull_request") and "comment" not in trigger:
            return resolved.event.body
    return None


async def _record_scope_declaration(ctx: RunContext) -> None:
    """Record the run's ``Scope paths:`` declaration on ``ToolState.scope_declaration``.

    Sources in order, first declaration wins: the pull request body
    (``source_ref="pr_description"``), then the body of each issue the pull
    request closes (``ToolState.linked_issues``, ``source_ref="linked_issue#<n>"``).
    A body without a block is skipped; a block that is empty or broke a bound
    still wins, so a later source never widens it. No block anywhere records an
    undeclared scope. The bodies are untrusted data and never open a file. Any
    failure, including a pull request body that had to be fetched and could not
    be, leaves ``None`` (unknown) and never raises into the run: a closing
    issue's block never stands in for a body that might declare a narrower scope.
    """
    tool_state = ctx.tool_state
    if tool_state is None:
        return
    try:
        sources: list[tuple[str, str | None]] = [("pr_description", await _pull_request_body(ctx))]
        sources.extend(
            (f"linked_issue#{issue.number}", issue.body) for issue in tool_state.linked_issues or ()
        )
        declaration = ScopeDeclaration(declared=False, globs=(), source_ref="", rejected=())
        for source_ref, body in sources:
            if not body:
                continue
            parsed = parse_scope_paths(body)
            if parsed.declared:
                declaration = replace(parsed, source_ref=source_ref)
                break
    except Exception as exc:  # unknown, never an error: the scope gate stays null
        logger.warning("scope declaration could not be read; the scope stays unknown: {}", exc)
        tool_state.scope_declaration = None
        return
    tool_state.scope_declaration = declaration
    if declaration.declared:
        logger.info(
            "» scope declared in {}: {} glob(s), {} rejected",
            declaration.source_ref,
            len(declaration.globs),
            len(declaration.rejected),
        )


async def _resolve_run_fix_labels(ctx: RunContext) -> None:
    """Record ``review.fixLabels`` from the operator's side of the pull request (#1056).

    Stored on ``ToolState.fix_labels`` before any tier can skip the agent, so the
    packet and the verification tool decide "is this a fix?" from base-side labels
    only. Never fails the run: any doubt leaves the defaults (``bug``, ``fix``).
    """
    if ctx.settings is None or ctx.tool_state is None or ctx.tool_context is None:
        return
    event = ctx.gh_event if isinstance(ctx.gh_event, dict) else {}
    repo = ctx.tool_context.repo
    try:
        labels = await resolve_fix_labels(
            ctx.tool_context.scm,
            repo.owner,
            repo.name,
            event=event,
            run_start_review=ctx.settings.review,
            operator_owned=ctx.settings_snapshot_operator_owned,
        )
    except Exception as err:  # fix detection falls back to the defaults, never off
        logger.warning("fix_labels: could not resolve review.fixLabels, using defaults: {}", err)
        from mergecraft.ci.red_green import DEFAULT_FIX_LABELS

        labels = DEFAULT_FIX_LABELS
    ctx.tool_state.fix_labels = labels


async def _resolve_run_red_green_declaration(ctx: RunContext) -> None:
    """Record the base-side ``ciEvidence.redGreen`` before any CI ingest (#1056).

    Stored on ``ToolState.red_green_declaration``; with none declared,
    ``ToolState.red_green`` records ``not-declared`` so a fix pull request is told
    which setting is missing. A pull request's own config never declares its
    receipt. Never fails the run: any doubt declares nothing.
    """
    if ctx.settings is None or ctx.tool_state is None or ctx.tool_context is None:
        return
    event = ctx.gh_event if isinstance(ctx.gh_event, dict) else {}
    repo = ctx.tool_context.repo
    unreadable: str | None
    try:
        declaration, unreadable = await read_red_green_declaration(
            ctx.tool_context.scm,
            repo.owner,
            repo.name,
            event=event,
            run_start_ci_evidence=ctx.settings.ci_evidence,
            operator_owned=ctx.settings_snapshot_operator_owned,
        )
    except Exception as err:  # an unresolvable declaration declares nothing, never fails
        logger.warning("red_green: could not resolve ciEvidence.redGreen: {}", err)
        declaration = None
        unreadable = f"the PR base config could not be read ({type(err).__name__})"
    ctx.tool_state.red_green_declaration = declaration
    if declaration is None:
        from mergecraft.ci.red_green import undeclared_red_green_evidence

        ctx.tool_state.red_green = undeclared_red_green_evidence(unreadable)


def _skip_without_review_diff(
    ctx: RunContext, skip: SkipAgentReview | LiteAgentReview
) -> SkipAgentReview | LiteAgentReview:
    """A run without the agent has no review diff, so a declared receipt is unverified.

    Both a ``skip`` tier and a ``lite`` tier leave the pull request unchecked out:
    neither writes the review diff the untouched-workflow check needs, so the
    fail-then-pass receipt cannot be verified on either path.
    """
    if ctx.tool_context is not None:
        reason = (
            skip.reason
            if isinstance(skip, SkipAgentReview)
            else f"lite tier: {skip.decision.reason}"
        )
        record_unverified_red_green(ctx.tool_context, reason=f"the agent did not run ({reason})")
    return skip


async def _ignore_paths_gate(ctx: RunContext) -> SkipAgentReview | None:
    """Resolve review path ignoring (#1109); skip the agent when every changed file is ignored.

    The matcher is built from the ``ignore_paths`` Action input, the built-in defaults
    and ``review.ignorePaths`` read from the operator's side of the pull request only,
    and is recorded on the tool state so ``checkout_pr`` trims the reviewer's diff.
    Only a ``pull_request`` / ``pull_request_target`` run whose complete file listing is
    ignored skips the agent; it then records a ``skip`` triage tier, so the run passes
    with "nothing to review" and approval is left to a human. Any doubt reviews.
    """
    assert ctx.settings is not None
    assert ctx.tool_state is not None
    assert ctx.tool_context is not None
    event = ctx.gh_event if isinstance(ctx.gh_event, dict) else {}
    repo = ctx.tool_context.repo
    try:
        ignore = await resolve_review_ignore(
            ctx.tool_context.scm,
            repo.owner,
            repo.name,
            event=event,
            run_start_review=ctx.settings.review,
            operator_owned=ctx.settings_snapshot_operator_owned,
            input_value=os.environ.get(IGNORE_PATHS_INPUT_ENV),
        )
    except Exception as err:  # path ignoring is an optimisation; failing it reviews everything
        logger.warning("ignore_paths: could not resolve the matcher, reviewing every file: {}", err)
        return None
    ctx.tool_state.review_ignore = ignore
    logger.info(
        "ignore_paths: {} glob(s), generated defaults {}, config from {}",
        len(ignore.patterns),
        "on" if ignore.generated_defaults else "off",
        ignore.source,
    )
    pull = event.get("pull_request")
    if not ignore.active or not isinstance(pull, dict) or not isinstance(pull.get("number"), int):
        return None
    if os.environ.get("GITHUB_EVENT_NAME", "") not in _IGNORE_SKIP_EVENTS:
        return None
    paths = await list_pull_request_paths(
        ctx.tool_context.scm, repo.owner, repo.name, int(pull["number"])
    )
    if not paths:
        return None
    kept, ignored = ignore.partition(paths)
    if kept:
        return None
    reason = f"nothing to review: all {len(ignored)} changed file(s) are ignored by config"
    ctx.tool_state.ignored_review_paths = ignored
    ctx.tool_state.triage = TriageDecision(tier="skip", recognizer="ignorePaths", reason=reason)
    logger.warning("» {} — {}", ctx.tool_state.triage.record_line(), reason)
    gha_log.notice(f"mergeCraft: {reason}")
    return SkipAgentReview(reason=reason)


async def _run_server_roster_reviewers_if_needed(ctx: RunContext) -> RosterExecutionSummary | None:
    """Dispatch file groups and secondary reviewers server-side; return the roster summary.

    The opt-in file-group fan-out (``review.fileGroupFanout``) runs first, after
    the primary reviewer. Its failures are run-health notes recorded on the tool
    state, so its summary is never folded into the roster result.
    """
    assert ctx.tool_context is not None
    assert ctx.tool_state is not None
    assert ctx.settings is not None
    assert ctx.run_ctx is not None
    if ctx.tool_state.selected_mode not in {"Review", "IncrementalReview"}:
        return None
    from mergecraft.review.roster_execution import run_pending_roster_reviewers

    def _remaining_roster_timeout_s() -> float | None:
        if ctx.agent_deadline_monotonic is None:
            return None
        return max(1.0, ctx.agent_deadline_monotonic - time.monotonic())

    if ctx.settings.review.file_group_fanout.enabled:
        fanout = await run_file_group_reviewers(
            tool_context=ctx.tool_context,
            base_run_ctx=ctx.run_ctx,
            settings=ctx.settings,
            payload=ctx.payload,
            repo_root=Path(primary_repo_state_dir(ctx.tool_state)),
            remaining_timeout_s=_remaining_roster_timeout_s,
            instructions_for=ctx.run_start_instructions.get,
        )
        if fanout.degraded:
            logger.warning(
                "» file-group fan-out degraded: {} group(s) recorded as run health",
                len(fanout.failures),
            )

    # Each secondary reviewer runs under its own deadline budget, never the
    # remainder of the primary's (``secondary_reviewer_timeout_s``).
    return await run_pending_roster_reviewers(
        tool_context=ctx.tool_context,
        base_run_ctx=ctx.run_ctx,
        settings=ctx.settings,
        payload=ctx.payload,
        instructions_for=ctx.run_start_instructions.get,
    )


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


_SINK_SCAN_ARTIFACT_SOURCES: tuple[str, ...] = (
    "packet-opencode-go.json",
    "packet-nous.json",
    "packet-codex.json",
    "packet-claude.json",
    "mergecraft/run-packet.json",
    "shadow-compare.jsonl",
)
"""Artifact sources the evidence/trace uploads are assembled from (SX-D10).

Every one lives under ``RUNNER_TEMP`` — the GitHub-provided per-job scratch
directory the workflow's ``actions/upload-artifact`` steps read. ``.json`` is
deliberately *not* a sink suffix, so the packet files are named explicitly and
scanned by path; the globs pick up the packet's real slug-prefixed spelling
and the shadow-compare JSONL wherever it lands beneath the runner temp dir.
"""


def _runner_temp_artifact_sources() -> list[Path]:
    """Resolve the in-scope artifact sources under ``RUNNER_TEMP``."""
    runner_temp = os.environ.get("RUNNER_TEMP", "").strip()
    if not runner_temp:
        return []
    base = Path(runner_temp)
    sources = [base / rel for rel in _SINK_SCAN_ARTIFACT_SOURCES]
    sources.extend(sorted(base.glob("packet-*.json")))
    # The emitted packet is ``<change-slug>-merge-evidence-packet.json`` in the
    # run-packet dir; the literal/glob spellings above predate it, so match the
    # real basename too — a packet that exists before the scan must not be
    # missed (a publication-time packet is caught by the post-emission scan).
    sources.extend(sorted((base / "mergecraft").glob("*-merge-evidence-packet.json")))
    sources.extend(sorted((base / "mergecraft").glob("*run-packet.json")))
    sources.extend(sorted((base / "mergecraft").glob("*.jsonl")))
    return list(dict.fromkeys(sources))


def _run_sink_scan_secret_values(ctx: RunContext) -> list[str]:
    """Return the credential *values* the run holds, for the post-run sink scan.

    Covers every provider credential env name the registry can consume (D2's
    single authority, so a new provider cannot be missed) plus the SCM tokens
    and API/DB secrets carried on the run context. Values only — the scan
    compares them and never records them.
    """
    from mergecraft.config.runtime_provider_registry import provider_credential_env_names

    values: list[str] = []

    def _add(value: str | None) -> None:
        if isinstance(value, str) and value.strip():
            values.append(value.strip())

    for name in provider_credential_env_names(ctx.settings):
        _add(os.environ.get(name))
    token_ref = ctx.token_ref
    if token_ref is not None:
        _add(token_ref.git_token)
        _add(token_ref.mcp_token)
        _add(token_ref.read_token)
    _add(ctx.job_token)
    run_context = ctx.run_context
    if run_context is not None:
        _add(run_context.api_token)
        for secret in (run_context.db_secrets or {}).values():
            _add(secret)
    return list(dict.fromkeys(values))


def _scan_sinks_after_run(ctx: RunContext, *, extra_paths: Sequence[Path] = ()) -> str | None:
    """Scan the run tmpdir and the artifact sources, delete hits, return the reason.

    SX-D10: a credential that reached a local sink has already left the agent's
    process, so the honest response is to stop the run, name the sink path —
    **never** its contents — and delete the sink before the workflow's
    artifact-upload step reads it. ``extra_paths`` carries artifacts the run
    generates *after* the pre-publication scan (the emitted packet/run packet),
    so the same guarantee covers everything the run emits, not only what
    existed beforehand.

    Returns the failure reason (naming the paths and the rotate instruction) or
    ``None`` when nothing matched. The matched contents are never returned or
    logged.
    """
    secrets = _run_sink_scan_secret_values(ctx)
    if not secrets:
        return None
    hits = scan_local_sinks_for_secrets(
        Path(ctx.tmpdir) if ctx.tmpdir else None,
        secrets=secrets,
        explicit_paths=[*_runner_temp_artifact_sources(), *extra_paths],
    )
    if not hits:
        return None
    for path in hits:
        try:
            path.unlink()
        except OSError as exc:
            logger.warning("» could not remove exposed local sink {}: {}", path, exc)
        else:
            logger.warning("» removed local sink holding credential material: {}", path)
    return (
        "credential material found in local sink(s) after the run: "
        + ", ".join(str(path) for path in hits)
        + " — rotate the exposed credential(s)"
    )


_ORCHESTRATOR_PUBLISH_STEP = "orchestrator.publish_review"


def owes_a_terminal_review(tool_state: ToolState) -> bool:
    """Whether this run recorded a verdict that GitHub is owed.

    A run that recorded no submission owes nothing: it records no publish step
    and says nothing. Everything past this point is about a verdict that exists.
    """
    return tool_state.terminal_submission is not None


def publication_skip_reason(
    tool_state: ToolState,
    agent_result: AgentResult,
    *,
    verdict_protocol: str | None,
) -> str | None:
    """Why this run will not publish its recorded verdict, or ``None`` when it will.

    Call only when :func:`owes_a_terminal_review` is true; a run that recorded
    nothing returns before this and records nothing. A recorded verdict that
    stops short of a review must name itself: #1017's Codex rung recorded
    ``request_changes``, published no review, and recorded nothing about why, so
    the only visible trace was the failing ``mergecraft-approval`` check. The
    three ways it happens are the shadow protocol, a run that is not a review
    run, and a submission that the post-run re-validation rejected — the last one
    is what to look for first when a review is expected and absent.
    """
    if getattr(tool_state, "review_publication_sticky_only", False):
        return (
            "this non-terminal rung deferred its neutral verdict to the fallback "
            "rung; the run record is in the sticky progress comment (#1078)"
        )
    if verdict_protocol == "shadow":
        return "the verdict protocol is shadow, so the verdict is recorded but not published"
    if not _is_review_mode(tool_state.selected_mode):
        return (
            "the run is not a review run "
            f"(selected_mode={tool_state.selected_mode!r}), so it publishes no review"
        )
    if not agent_result.terminal_submission_received:
        rejection = str((agent_result.diagnostics or {}).get("rejection_reason") or "unknown")
        return f"the recorded submission was rejected at post-run validation ({rejection})"
    return None


def _approve_event_eligible(tool_context: ToolContext) -> bool:
    """Whether an ``approve`` verdict on this run is posted as a GitHub APPROVE.

    Mirrors the publisher's event rule: approvals enabled, trusted authority,
    and a run that had something in review scope (a triage skip never approves).
    """
    triage_skipped = getattr(tool_context.tool_state.triage, "tier", None) == "skip"
    return (
        bool(tool_context.pr_approve_enabled)
        and tool_context.authority_trust == "trusted"
        and not triage_skipped
    )


async def _publish_recorded_verdict(
    tool_context: ToolContext,
    agent_result: AgentResult,
    *,
    verdict_protocol: str | None,
    approval_withheld: str | None = None,
) -> None:
    """Phase 4 — publish the accepted terminal submission once (the run owns publication).

    A compliant Review run records one ``submit_review_verdict`` and publishes
    nothing itself; the run publishes the final attempt's accepted verdict
    here, before the outcome is classified. The publisher is idempotent on its
    receipt: an agent-published review with the same verdict is not posted
    again, and a receipt for a different verdict posts nothing and sets the
    mismatch flag. A failure never escapes Phase 4; the classifier reads the
    missing receipt (or ``terminal_publication_failed``) instead. The step is
    recorded in the trajectory as ``orchestrator.publish_review``, ``ok`` only
    when a receipt for the recorded verdict exists, including when the agent
    already published it. The row carries the receipt's ``payload_hash`` and
    the recorded findings GitHub's inline view lacks.

    A run that recorded no verdict records no step. A recorded verdict the run
    does not publish (:func:`publication_skip_reason`) is recorded as a not-ok
    step stamped ``failure_class="declined"`` with the reason in ``error``, so
    the trajectory auditor reads it as a decision, not a failed call.

    ``approval_withheld`` is the reason the run's outcome would not be
    ``passed`` (resolved before publication). When it is set, an ``approve``
    verdict is published as a ``COMMENT`` review rather than an ``APPROVE``:
    a run that does not pass never leaves an approval on the pull request.
    """
    tool_state = tool_context.tool_state
    if not owes_a_terminal_review(tool_state):
        # Nothing was recorded, so the run owes GitHub nothing and says nothing.
        return
    skip_reason = publication_skip_reason(
        tool_state,
        agent_result,
        verdict_protocol=verdict_protocol,
    )
    if skip_reason is not None:
        # A recorded verdict that reaches no review is evidence about the run, not
        # a silent return: the packet's trajectory is where a missing review is
        # explained, and #1017's Codex rung is what its absence looks like.
        logger.warning("» the run did not publish the recorded review verdict: {}", skip_reason)
        from mergecraft.evidence.trajectory import record_tool_call

        record_tool_call(
            tool_state,
            tool=_ORCHESTRATOR_PUBLISH_STEP,
            arguments=None,
            ok=False,
            error=skip_reason,
            failure_class="declined",
        )
        return
    from mergecraft.evidence.trajectory import record_tool_call
    from mergecraft.mcp.review import publish_pull_request_review

    submission = tool_state.terminal_submission
    withhold = (
        approval_withheld is not None
        and submission is not None
        and submission.verdict == "approve"
        and _approve_event_eligible(tool_context)
    )
    approve_enabled = tool_context.pr_approve_enabled
    if withhold:
        logger.warning(
            "» the approve verdict is published as a comment, not an approval: {}",
            approval_withheld,
        )
        tool_context.pr_approve_enabled = False
    try:
        publish_started = time.perf_counter()
        response = await publish_pull_request_review(
            tool_context, run_not_passing_reason=approval_withheld
        )
        tool_state.phase_elapsed_s["publish"] = round(time.perf_counter() - publish_started, 3)
    except Exception as exc:
        logger.warning("» the run could not publish the recorded review verdict: {}", exc)
        record_tool_call(
            tool_state,
            tool=_ORCHESTRATOR_PUBLISH_STEP,
            arguments=None,
            ok=False,
            error=f"{type(exc).__name__}: {exc}",
        )
        return
    finally:
        tool_context.pr_approve_enabled = approve_enabled
    # A same-verdict skip (the agent already published this verdict) is
    # recorded too: the receipt is present, and this row is where its hash and
    # any inline gap are read. A skipped *mismatch* (``success: false``) is
    # recorded as not ok.
    receipt = tool_state.review
    published = response.get("success") is True and receipt is not None
    record_tool_call(
        tool_state,
        tool=_ORCHESTRATOR_PUBLISH_STEP,
        arguments=None,
        ok=published,
        error=None if published else str(response.get("reason") or "no receipt"),
        payload_hash=receipt.payload_hash if receipt is not None else None,
        publication_incomplete=list(tool_state.publication_incomplete) if published else None,
    )


async def _dismiss_unpassed_approval(
    ctx: RunContext,
    *,
    reason: str,
    review_before_publication: Any,
) -> bool:
    """Dismiss this run's APPROVE review when the run did not pass; return whether it did.

    The formal review is published with an APPROVE only when every gate known
    before publication passed, but some inputs resolve only afterwards (the
    disposition ledger, the post-emission sink scan, a publication mismatch),
    and an agent can publish mid-run. When the final outcome is not ``passed``
    and the review this run holds was posted as an APPROVE, it is dismissed
    with the reason, so the pull request never keeps an approval from a run
    that did not pass. Total: a failed dismissal is logged and recorded in the
    trajectory, never raised.
    """
    tool_context = ctx.tool_context
    if tool_context is None:
        return False
    tool_state = tool_context.tool_state
    review = tool_state.review
    if review is None or review.verdict != "approve" or review.reviewed_sha is None:
        return False
    if not _approve_event_eligible(tool_context):
        return False
    if review is not review_before_publication and ctx.approval_withheld_reason is not None:
        # Published at finalize as a comment: there is no approval to dismiss.
        return False
    pull_number = tool_state.pr_number
    if pull_number is None and tool_context.payload.event.issue_number is not None:
        pull_number = int(tool_context.payload.event.issue_number)
    if pull_number is None:
        return False
    from mergecraft.evidence.trajectory import record_tool_call

    owner, repo = tool_context.repo.owner, tool_context.repo.name
    message = f"mergeCraft: this run did not pass, so its approval is withdrawn — {reason}"
    try:
        await tool_context.scm.put(
            f"/repos/{owner}/{repo}/pulls/{int(pull_number)}/reviews/{review.id}/dismissals",
            json={"message": message[:1000], "event": "DISMISS"},
        )
    except Exception as exc:  # dismissal is best effort; the checks already fail closed
        logger.warning("» could not dismiss this run's approval review {}: {}", review.id, exc)
        record_tool_call(
            tool_state,
            tool="orchestrator.dismiss_approval",
            arguments=None,
            ok=False,
            error=f"{type(exc).__name__}: {exc}",
        )
        return False
    logger.warning("» dismissed this run's approval review {}: {}", review.id, reason)
    record_tool_call(tool_state, tool="orchestrator.dismiss_approval", arguments=None, ok=True)
    return True


def _coverage_gate_reason(tool_context: ToolContext, settings: RepoSettings) -> str | None:
    """Return the outcome reason when changed-line coverage is incomplete and gated.

    Total: a failure to account for coverage must not fail the run it describes, so it
    logs and reports no gate (the packet then simply carries no coverage section).
    """
    from mergecraft.evidence.coverage import (
        coverage_gate_reason,
        coverage_policy,
        coverage_section_for_state,
    )

    # A hard diff budget cannot be relaxed by the advisory coverage policy.
    if tool_context.tool_state.diff_budget_reason:
        return tool_context.tool_state.diff_budget_reason
    try:
        return coverage_gate_reason(
            coverage_section_for_state(tool_context.tool_state),
            on_incomplete=coverage_policy(tool_context, fallback=settings),
        )
    except Exception as exc:  # accounting is evidence, never a new way to crash a run
        logger.warning("changed-line coverage could not be accounted for: {}", exc)
        return None


async def _finalize(
    ctx: RunContext, result: AgentResult | SkipAgentReview | LiteAgentReview
) -> MainResult:
    """Phase 4 — post-run, publish, outcome mapping (G4.2)."""
    assert ctx.tool_context is not None
    assert ctx.tool_state is not None
    assert ctx.settings is not None

    tool_context = ctx.tool_context
    tool_state = ctx.tool_state
    settings = ctx.settings
    ctx.publish_started = True

    finalize_failure: str | None = None
    lite = result if isinstance(result, LiteAgentReview) else None
    if isinstance(result, (SkipAgentReview, LiteAgentReview)):
        agent_result = AgentResult(success=True)
    else:
        agent_result = result
        from mergecraft.mcp.verdict import fold_reviewer_dispatch_findings_into_submission

        # Secondary reviewers and file groups ran after the primary recorded its
        # verdict; their findings join it before it is re-validated and published.
        fold_reviewer_dispatch_findings_into_submission(tool_context)
        # A primary that published mid-run assembled (and cached) the evidence
        # packet before the fan-out and the roster recorded their findings.
        # Drop that snapshot so publication, the approval decision, the checks
        # and the emitted packet are all built from the complete run.
        tool_state.prepared_run_packet = None
        if ctx.run_ctx is not None:
            try:
                agent_result = await finalize_agent_result(ctx.run_ctx, agent_result)
            except Exception as exc:  # finalize validates arbitrary recorded state
                # ``finalize_agent_result`` re-validates the recorded submission, which
                # can raise whatever that state makes it raise, so the catch stays broad
                # but is never silent: the run cannot confirm its terminal verdict, so the
                # verdict is not published as one and the run is ``inconclusive``.
                finalize_failure = f"finalize_failed: {type(exc).__name__}"
                tool_state.finalize_failure = finalize_failure
                logger.warning(
                    "» post-run finalize failed ({}): {}; the run cannot confirm its "
                    "terminal verdict and fails closed",
                    type(exc).__name__,
                    exc,
                )
                # A driver result is already finalized (``received=True``), so the
                # unconfirmed verdict is withdrawn from publication explicitly.
                agent_result = replace(
                    agent_result,
                    terminal_submission_received=False,
                    diagnostics={
                        **(agent_result.diagnostics or {}),
                        "rejection_reason": finalize_failure,
                    },
                )

    # SX-D10 / F2=A — post-run sink scan of the run temp dir *and* every
    # artifact source the evidence uploads read. It runs after the agent
    # finished (``finalize_agent_result`` above), before the formal review is
    # published and the outcome is classified, and before the ``finally``
    # block's ``cleanup_temp_directory()`` would remove the sinks. A hit means
    # the credential already left the agent's process, so the response is to
    # stop the run, name the sink path — never its contents — force the
    # approval conclusion to ``failure`` and delete the sink before artifact
    # upload.
    #
    # This scan sees only what exists *before* publication; ``_publish`` emits
    # the packet afterwards, so it is re-scanned post-emission (below) before
    # the approval/status report and the workflow's upload.
    sink_scan_error: str | None = _scan_sinks_after_run(ctx)

    # Every run-level gate is resolved before the formal review is published:
    # one shared resolver (``review.outcome_resolution``) maps them, and an
    # ``approve`` verdict is posted as an APPROVE only when the run passes.
    prep_reason = await _prep_failure_reason(tool_context, wait_s=_PREP_PUBLISH_WAIT_S)
    setup_reason = tool_state.setup_hook_failure or ""
    if ctx.budget_tracker is not None:
        ctx.run_bounds = ctx.budget_tracker.bounds
    from mergecraft.review.outcome_resolution import (
        OutcomeInputs,
        approval_withheld_reason,
        resolve_run_outcome,
        roster_failure_from_result,
    )

    # D12 / PR #242 finding ``aeb5d964c1d35e5a41784ded`` — tool-call budget
    # exhaustion surfaces only from the MCP ``tools/call`` handler (which
    # catches ``BudgetExhausted`` to return a JSON-RPC error). The tracker
    # itself records the exception, so the run is still tagged at finalize.
    budget_exhaustion = ctx.budget_exhaustion
    if budget_exhaustion is None and ctx.budget_tracker is not None:
        budget_exhaustion = getattr(ctx.budget_tracker, "last_exhausted", None)
    roster_failure, roster_infra_reason = roster_failure_from_result(agent_result)
    outcome_inputs = OutcomeInputs(
        result=agent_result,
        # A lite run owes no terminal verdict and delivers no checkout coverage:
        # it is classified on its own reason below, not as a review-mode run.
        mode=None if lite is not None else tool_state.selected_mode,
        verdict_protocol=settings.gates.terminal_verdict,
        setup_reason=setup_reason,
        setup_policy=settings.setup_failure_policy,
        prep_reason=prep_reason,
        final_summary_written=tool_state.final_summary_written,
        coverage_incomplete_reason=_coverage_gate_reason(tool_context, settings),
        diff_budget_reason=tool_state.diff_budget_reason,
        terminal_rejection=tool_state.last_terminal_rejection,
        budget_exhaustion=budget_exhaustion,
        finalize_failure=finalize_failure,
        roster_failure=roster_failure,
        roster_infra_reason=roster_infra_reason,
        lite_reason=_lite_inconclusive_reason(lite.outcome) if lite is not None else None,
        sink_scan_error=sink_scan_error,
        structured_output_error=ctx.structured_output_error,
    )
    review_before_publication = tool_state.review
    if not isinstance(result, (SkipAgentReview, LiteAgentReview)):
        withheld = approval_withheld_reason(outcome_inputs)
        if (
            withheld is not None
            and tool_state.terminal_submission is not None
            and tool_state.terminal_submission.verdict == "approve"
            and _approve_event_eligible(tool_context)
        ):
            ctx.approval_withheld_reason = withheld
        await _publish_recorded_verdict(
            tool_context,
            agent_result,
            verdict_protocol=settings.gates.terminal_verdict,
            approval_withheld=withheld,
        )
    publication_receipt, publication_mismatch = _publication_outcome_inputs(
        tool_state,
        result=agent_result,
        verdict_protocol=settings.gates.terminal_verdict,
    )
    outcome: RunOutcome
    failure_reason: str | None
    outcome, failure_reason = resolve_run_outcome(
        replace(
            outcome_inputs,
            terminal_publication_failed=tool_state.terminal_publication_failed,
            terminal_publication_receipt=publication_receipt,
            terminal_publication_mismatch=publication_mismatch,
            terminal_publication_unproven=_publication_unproven(tool_state),
        )
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
        terminal_publication_receipt=publication_receipt,
        terminal_publication_mismatch=publication_mismatch,
        terminal_rejection=tool_state.last_terminal_rejection,
    )
    diagnostic_attrs = verdict_publish.attrs
    verdict_prediction = verdict_publish.prediction
    verdict_diagnostic_code = verdict_publish.diagnostic

    selected_mode_obj = next(
        (m for m in tool_context.modes if m.name == tool_context.tool_state.selected_mode),
        None,
    )

    # SX-D10 — the pre-publication scan above cannot see the packet ``_publish``
    # emits, and the workflow uploads that artifact. ``_publish`` re-scans it
    # after emission and before the status/approval report; the callback records
    # a post-emission hit here so this run's own result agrees with the checks
    # ``_publish`` posted.
    post_emission_sink: list[str] = []

    def _scan_emitted_sink(written: Path | None) -> str | None:
        extra = [written] if written is not None else []
        post_error = _scan_sinks_after_run(ctx, extra_paths=extra)
        if post_error is not None:
            post_emission_sink.append(post_error)
        return post_error

    packet_path = await _publish(
        ctx,
        outcome=outcome,
        failure_reason=failure_reason,
        attrs_source=lambda: _publish_span_attrs(outcome, selected_mode_obj) | diagnostic_attrs,
        verdict_prediction=verdict_prediction,
        actual_outcome=str(outcome) if verdict_prediction is not None else None,
        verdict_diagnostic=verdict_diagnostic_code,
        sink_scan_error=sink_scan_error,
        sink_scan=_scan_emitted_sink,
    )
    if post_emission_sink:
        # The emitted packet held credential material and has been deleted; the
        # completion and approval checks were already forced to ``failure``.
        outcome = RunOutcome.failed
        failure_reason = post_emission_sink[0]
    # #1014 — the same open-ledger rule ``_publish`` applied to the checks, so
    # this run's own result agrees with the completion check it posted.
    from mergecraft.review.outcome_resolution import finalize_run_outcome

    outcome, ledger_reason = finalize_run_outcome(outcome, tool_state.prepared_run_packet)
    failure_reason = ledger_reason or failure_reason
    if outcome is not RunOutcome.passed:
        await _dismiss_unpassed_approval(
            ctx,
            reason=failure_reason or f"the run outcome is {outcome.value}",
            review_before_publication=review_before_publication,
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
            failover_eligible=(
                not agent_result.success
                and (agent_result.metadata or {}).get(FAILOVER_ELIGIBLE_KEY) is True
            ),
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


async def _close_superseded_scm(scm: ScmProvider) -> None:
    """Best-effort close of the job-token SCM before the MCP-token SCM replaces it.

    A failure here is logged once, naming the superseded handle and never a
    secret, and never changes the run outcome (CR-D8). The replacement client
    is still closed by the best-effort ``finally`` teardown.
    """
    try:
        await scm.aclose()
    except Exception as exc:
        logger.warning(
            "» could not close superseded scm handle: {}: {}",
            type(exc).__name__,
            exc,
        )


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
    sink_error = _scan_sinks_after_run(ctx, extra_paths=[Path(written)] if written else [])
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
