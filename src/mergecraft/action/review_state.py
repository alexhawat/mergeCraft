"""Define the Action review state and phase results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Callable

    from mergecraft.agents.lite import LiteOutcome
    from mergecraft.agents.shared import Agent, AgentRunContext
    from mergecraft.analyzers.manifest import TrustTier
    from mergecraft.analyzers.trust import AnalyzersMode
    from mergecraft.classify.triage import TriageDecision
    from mergecraft.config.settings import RepoSettings, RunContextData
    from mergecraft.mcp.context import ResolvedPayload, ToolContext
    from mergecraft.mcp.tool_state import (
        ToolState,
    )
    from mergecraft.mcp.verdict import VerdictDiagnostic
    from mergecraft.memory.feedback import FeedbackReport
    from mergecraft.modes import Mode
    from mergecraft.run_outcome import (
        RunOutcome,
    )
    from mergecraft.scm.protocol import ScmProvider
    from mergecraft.utils.instructions import ResolvedInstructions
    from mergecraft.utils.payload import (
        JsonPayload,
    )
    from mergecraft.utils.run_bounds import BudgetExhausted, BudgetTracker, RunBounds
    from mergecraft.utils.token import TokenRef


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


@dataclass
class RunContext:
    """Resources and state needed during or after a partially completed Action run.

    Cleanup and failure publication can run before preparation or dispatch
    completes. The existing entry-point adapter exposes these defaulted fields
    while phase-specific results carry completed work between operations.
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

    # -- model resolution and dispatch --------------------------------------
    model_pin: bool = False
    model_head: str | None = None
    chain_for_decision: list[str] = field(default_factory=list)
    use_model_chain: bool = False
    selected_slug: str | None = None
    resolved_model: str | None = None
    agent: Agent | None = None
    agent_id: Any = ""
    modes: list[Mode] = field(default_factory=list)
    output_schema: dict[str, Any] | None = None
    ctx_payload: ResolvedPayload | None = None
    analyzers_mode: AnalyzersMode | None = None
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
    instructions: ResolvedInstructions | None = None
    feedback_report: FeedbackReport | None = None
    run_ctx: AgentRunContext | None = None
    run_bounds: RunBounds | None = None
    budget_tracker: BudgetTracker | None = None
    budget_exhaustion: BudgetExhausted | None = None
    # Why a required ``set_output`` payload is missing, if it is (resolver input).
    structured_output_error: str | None = None
    # Instructions rendered at run start, per harness, for every attempt and
    # server-side reviewer; never re-rendered from the post-checkout tree.
    run_start_instructions: dict[str, ResolvedInstructions] = field(default_factory=dict)
    # -- populated by ``_finalize`` -------------------------------------------
    # Why this run's formal review was not posted as an APPROVE, if it was not.
    approval_withheld_reason: str | None = None
    # The publish stage began: the review finished, so a failure from here on
    # (a publish-stage timeout) still owes the run its evidence packet.
    publish_started: bool = False
