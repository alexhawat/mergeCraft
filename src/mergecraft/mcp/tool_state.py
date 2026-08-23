"""Mutable per-run tool state (ported from toolState.ts)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from mergecraft.findings.ledger import FindingLedger
    from mergecraft.modes import Mode
    from mergecraft.prep.types import PrepResult
    from mergecraft.review.lens_routing import LensRoutingDecision

RepoAccess = Literal["primary", "write", "read"]


@dataclass(slots=True)
class BackgroundProcess:
    pid: int
    output_path: str
    pid_path: str


@dataclass(slots=True)
class StoredPushDest:
    remote_name: str
    remote_branch: str
    local_branch: str


@dataclass(slots=True)
class CommentableLines:
    RIGHT: set[int] = field(default_factory=set)
    LEFT: set[int] = field(default_factory=set)


@dataclass(slots=True)
class InitialHeadBranch:
    kind: Literal["branch"]
    name: str


@dataclass(slots=True)
class InitialHeadDetached:
    kind: Literal["detached"]
    sha: str


InitialHead = InitialHeadBranch | InitialHeadDetached


@dataclass(slots=True)
class RepoToolState:
    owner: str
    name: str
    dir: str
    access: RepoAccess
    default_branch: str | None = None
    push_url: str | None = None
    push_dest: StoredPushDest | None = None
    initial_head: InitialHead | None = None
    issue_number: int | None = None
    checkout_sha: str | None = None
    commentable_lines_by_file: dict[str, CommentableLines] | None = None
    commentable_lines_pull_number: int | None = None
    commentable_lines_checkout_sha: str | None = None
    before_sha: str | None = None
    diff_coverage: Any = None
    # Full-PR unified diff written by ``checkout_pr``. Retained on the state
    # (not just returned to the agent as ``diffPath``) so end-of-run consumers
    # — the merge evidence packet's blast-radius classification, #96 — can
    # read the same authoritative patch the reviewer read.
    diff_path: str | None = None
    # Incremental review scope (C4): the commit mergeCraft last reviewed, the
    # patch covering everything since it, and that patch's changed paths. All
    # three stay ``None`` when no prior review is recoverable.
    last_reviewed_sha: str | None = None
    incremental_diff_path: str | None = None
    incremental_changed_paths: list[str] | None = None


@dataclass(slots=True)
class ProgressComment:
    id: str
    type: Literal["issue", "review"]


@dataclass(slots=True)
class TerminalSubmission:
    """Recorded terminal review verdict for a run (VP1).

    Findings are ``AgentFinding`` instances at runtime; typed as ``Any`` here
    to keep this module free of the verifier import cycle.
    """

    id: str
    verdict: Literal["approve", "request_changes"]
    summary: str
    findings: list[Any]
    payload_hash: str
    submitted_at: str
    attempt_id: int


@dataclass(slots=True)
class ReviewRecord:
    id: int
    node_id: str
    reviewed_sha: str | None


@dataclass(slots=True)
class ApprovalRecord:
    """Advisory record of what the agent asked ``create_pull_request_review``
    to do.

    ``would_approve`` is the agent's *self-assessment*, captured as a side
    effect of the ``create_pull_request_review`` tool call. It is **never the
    sole positive input** to the approval gate — that gate is computed
    structurally by ``mergecraft.agents.gates.decide_approval`` from the typed
    ``Finding`` list, the run's completion state, and the trust tier (D12).

    W2 of the merge-evidence plan (#41) split this signal from the evidence
    verdict: ``build_packet()`` translates the legacy ``ApprovalRecord`` into
    the packet's ``self_assessment`` row, and the structural ``Decision``
    lives in its own sibling field. The legacy ``tool_state.approval``
    surface stays for backward compatibility with consumers that still
    read ``would_approve`` directly; new code should consume the packet's
    ``self_assessment`` row instead.

    The field exists for the trajectory / merge-evidence plan (#41) so the
    recorded "self-assessment" can be compared against the structural
    conclusion after the fact. It is not consulted by ``report_status_checks``
    or ``create_pull_request_review``'s wire-call layer — both are pinned to
    structural inputs by W7.3 / W7.4 / W7.5 of the security-trust-boundary
    plan (#75).
    """

    would_approve: bool
    sha: str | None


@dataclass(slots=True)
class ReviewReplyRecord:
    comment_id: int
    url: str | None
    body_with_footer: str


@dataclass(slots=True)
class DependencyInstallationState:
    status: Literal["not_started", "in_progress", "completed", "failed"]
    promise: Any = None
    results: list[PrepResult] | None = None


@dataclass(slots=True)
class AnalyzerStatusRow:
    id: str
    status: str
    reason: str | None = None
    finding_count: int = 0


@dataclass(frozen=True, slots=True)
class AnalyzerRunKey:
    """Identity of the inputs one analyzer-pipeline run was computed from.

    An offline ``mergecraft review`` runs the catalog pipeline twice over the
    same inputs: once as a pre-pass (``review/offline_stages.py``, whose result
    feeds the structured findings and the exit code) and once when the
    reviewing agent calls the ``run_analyzers`` MCP tool. Recording the pre-pass
    inputs lets the tool reuse that result instead of provisioning and
    executing every analyzer a second time.

    Every field is an input that can change what the pipeline returns:
    ``repo_root`` and ``changed_files`` decide which manifests are selected,
    ``tier`` / ``shell`` / ``mode`` decide which of those may execute,
    ``inline_budget`` decides the inline/mechanical split, ``offline`` gates
    base-comparison work, ``base_ref`` picks the base for the differential
    analyzers, and ``diff_digest`` covers the diff the findings are scoped to.
    Anything not listed here must not differ between the two call sites.
    """

    repo_root: str
    changed_files: tuple[str, ...]
    tier: str
    shell: str
    mode: str
    inline_budget: int
    offline: bool
    base_ref: str | None
    diff_digest: str

    def matches(self, request: AnalyzerRunKey) -> bool:
        """Return True when ``request`` may reuse the run recorded under self.

        ``request`` is the incoming ``run_analyzers`` call. Every field must be
        equal, with one asymmetry: a ``request`` that omits ``base_ref``
        (``None``) is compatible with a recorded run that named one. ``None`` is
        the tool's "resolve a base yourself" sentinel, not a value — and because
        ``diff_digest`` already had to match, the recorded ``base_ref`` is the
        base of the very diff being scoped. A ``request`` that names a
        *different* base is not compatible.
        """
        if request.base_ref is not None and request.base_ref != self.base_ref:
            return False
        return (
            self.repo_root == request.repo_root
            and self.changed_files == request.changed_files
            and self.tier == request.tier
            and self.shell == request.shell
            and self.mode == request.mode
            and self.inline_budget == request.inline_budget
            and self.offline == request.offline
            and self.diff_digest == request.diff_digest
        )


def analyzer_run_key(
    *,
    repo_root: Path | str,
    changed_files: list[str],
    tier: str,
    shell: str,
    mode: str,
    inline_budget: int,
    offline: bool,
    base_ref: str | None,
    diff_text: str,
) -> AnalyzerRunKey:
    """Build an :class:`AnalyzerRunKey` from one pipeline call's inputs.

    Both call sites go through this helper so the normalisation stays identical:
    ``repo_root`` is resolved, ``changed_files`` is de-duplicated and sorted
    (order never changes the selected manifests), and the diff is reduced to a
    SHA-256 digest rather than carried whole.
    """
    return AnalyzerRunKey(
        repo_root=str(Path(repo_root).resolve()),
        changed_files=tuple(sorted({str(path) for path in changed_files})),
        tier=tier,
        shell=shell,
        mode=mode,
        inline_budget=inline_budget,
        offline=offline,
        base_ref=base_ref,
        diff_digest=hashlib.sha256(diff_text.encode("utf-8")).hexdigest(),
    )


@dataclass(slots=True)
class AnalyzerRunState:
    ran: bool = False
    reason: str | None = None
    analyzers: list[AnalyzerStatusRow] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    inline: list[dict[str, Any]] = field(default_factory=list)
    mechanical_section: str | None = None
    deferred_section: str | None = None
    deferred_findings: list[dict[str, Any]] = field(default_factory=list)
    pre_merge_summary: str | None = None
    lockfile_digest: str | None = None
    verified_ids: set[str] = field(default_factory=set)
    # Inputs this run was computed from, when they were recorded. Set only by
    # the offline pre-pass (``review/offline_stages.py``); ``None`` everywhere
    # else — including on the GitHub Action path, which has no pre-pass — so an
    # unkeyed run is never reused by ``run_analyzers``.
    key: AnalyzerRunKey | None = None

    def all_rows(self) -> list[dict[str, Any]]:
        """Return every dict-shaped finding row held on this analyzer run."""
        rows: list[dict[str, Any]] = []
        for collection in (self.findings, self.deferred_findings, self.inline):
            rows.extend(row for row in collection if isinstance(row, dict))
        return rows


@dataclass(slots=True)
class CiEvidenceState:
    """Evidence normalised from the consumer's *already-finished* CI (#36).

    Kept separate from ``AnalyzerRunState`` on purpose: ``run_analyzers``
    replaces its run state wholesale on every call, so anything merged into it
    would silently vanish if the reviewing agent re-ran the analyzers after
    reading CI. CI evidence outlives that.

    ``findings`` holds ``Finding.model_dump()`` rows — the same dict shape
    ``AnalyzerRunState.findings`` uses, so the packet's loader reads one shape.
    ``substitutions`` records every gate outcome a declared CI check run
    changed, so a reader can audit *why* a gate stopped saying ``unavailable``.
    """

    findings: list[dict[str, Any]] = field(default_factory=list)
    substitutions: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class ToolState:
    repos: dict[str, RepoToolState]
    primary_repo_key: str
    prepush_failure_count: int = 0
    background_processes: dict[str, BackgroundProcess] = field(default_factory=dict)
    selected_mode: str | None = None
    # Built-in + custom ``Mode`` objects resolved at ``main()`` time
    # (#145). ``main()`` stamps the resolved list here so the publish-span
    # ``attrs_source`` can spread ``trace_attrs_for_mode(m)`` per mode
    # without re-computing the renderer at span-close time. ``None`` is
    # intentional only for tests that build ``ToolState`` directly; the
    # live path always sets this.
    modes: list[Mode] = field(default_factory=list)
    review: ReviewRecord | None = None
    # D10 / VP4 — closed ``ReviewPhase`` vocabulary; advanced by checkout and
    # verdict tools (``mcp/verdict.py``).
    review_phase: str = "INIT"
    # Stashed ``create_pull_request_review`` params for ``publish_pull_request_review``.
    pending_review_publication: dict[str, Any] | None = None
    terminal_submission: TerminalSubmission | None = None
    terminal_submission_conflict: bool = False
    approval: ApprovalRecord | None = None
    review_replies: dict[int, ReviewReplyRecord] = field(default_factory=dict)
    dependency_installation: DependencyInstallationState | None = None
    progress_comment: ProgressComment | Literal[False] | None = None
    # None = unset, ProgressComment = active, False = deliberately deleted (TS uses null)
    had_progress_comment: bool = False
    last_progress_body: str | None = None
    was_updated: bool = False
    final_summary_written: bool = False
    existing_plan_comment_id: int | None = None
    previous_plan_body: str | None = None
    summary_file_path: str | None = None
    summary_seed: str | None = None
    summary_persist_attempted: bool = False
    learnings_file_path: str | None = None
    learnings_seed: str | None = None
    learnings_persist_attempted: bool = False
    learnings_review_delta: str | None = None
    # D10 / W6.2 — provenance + quarantine gate for new learning entries.
    # New entries land in a ``## Staging`` section by default; only entries
    # whose provenance chain contains an ``OWNER``/``MEMBER``/``COLLABORATOR``
    # author may be promoted, and promotion is opt-in via
    # ``autopromote_learnings`` (D10, #74).
    autopromote_learnings: bool = False
    # Run identity (GitHub Actions run id) for provenance records.
    run_id: str | None = None
    # PR number the run is acting on (None for non-PR runs).
    pr_number: int | None = None
    # Author login of the triggerer / comment author (provenance source).
    author: str | None = None
    # GitHub ``author_association`` of the triggering comment / event.
    author_association: str | None = None
    # ``derive_trust_tier()``'s return value for this run (trusted|untrusted).
    trust_tier: str | None = None
    # When ``setup_script`` is skipped on an untrusted tier (W1.2), the reason
    # string is recorded here for harness/tests and later RunOutcome mapping.
    setup_script_skip_reason: str | None = None
    # S1 / D5 / D6 / F6 — when a trusted-tier ``setup_script`` exits non-zero
    # or hits the configured timeout, the redacted reason is recorded here so
    # ``main.py`` can wire it into the agent prompt at both call sites and
    # into the outcome resolution path. Empty string = no failure.
    setup_hook_failure: str = ""
    # Former askpass path retained for bookkeeping only — ``setup_git`` shreds
    # the on-disk helper immediately (auth is MCP ``http.extraHeader``; W2.2).
    git_askpass_path: str | None = None
    xrepo_learnings_file_path: str | None = None
    xrepo_learnings_seed: str | None = None
    xrepo_learnings_persist_attempted: bool = False
    output: str | None = None
    # First-finding stream for ``mergecraft review --agent`` (#378).
    on_finding: Callable[[dict[str, Any]], None] | None = None
    # Per-attempt ``AgentUsage`` token counts, appended once per run by
    # ``main.py``. Despite what the merge-evidence plan assumed, this is *not*
    # a tool-call log — the trajectory record (#43) keeps its own field below.
    usage_entries: list[Any] = field(default_factory=list)
    # Every MCP tool call this run made, in order (#43, D8). Appended by
    # ``mcp/server.py``'s ``tools/call`` handler — the single door every agent
    # tool call goes through — and read at end of run by
    # ``evidence/trajectory.py::build_trajectory_record``. Typed ``list[Any]``
    # rather than ``list[ToolCallRecord]`` only to keep this module free of an
    # import cycle back into ``evidence``.
    tool_calls: list[Any] = field(default_factory=list)
    model: str | None = None
    # W10.2 / #20 — requested vs executed model evidence (always populated on
    # the live path so the packet can prove which model actually ran).
    requested_model: str | None = None
    fallback_index: int = 0
    attempt_id: int = 0
    fallback_occurred: bool = False
    unselected_proxy_default: bool | None = None
    model_clamped: dict[str, str] | None = None
    sha_pinned: bool | None = None
    oss: bool | None = None
    todo_tracker: Any = None
    agent_diagnostic: Any = None
    browser_daemon: Any = None
    analyzer_run: AnalyzerRunState | None = None
    # Session-scoped verifier confirms. ``run_analyzers`` replaces
    # ``analyzer_run`` wholesale, so confirmations must not live only there.
    verified_ids: set[str] = field(default_factory=set)
    # Fingerprints a verifier ``drop`` retired during this run. This set is
    # authoritative within the run — only canonical fingerprints survive the
    # learnings round trip, so the live set is what makes the drop valve
    # reliable here. The learnings file the refutation is also written to is the
    # cross-run memory of the same decision; the approve gate unions both
    # (``verdict.withdrawn_fingerprints_for_state``).
    withdrawn_fingerprints: set[str] = field(default_factory=set)
    # Lens routing snapshot (RC7, W5) — recommended vs actually-dispatched lenses.
    lens_routing_decision: LensRoutingDecision | None = None
    dispatched_lens_ids: tuple[str, ...] = ()
    # Open-PR finding ledger (RC4, D4) — hydrated from the sticky progress comment.
    finding_ledger: FindingLedger | None = None
    finding_ledger_loaded: bool = False
    # RC12 — 1-based review round, set by ``checkout_pr`` from prior PR reviews.
    review_round_index: int = 1
    confirmed_findings: list[dict[str, Any]] = field(default_factory=list)
    agent_findings: list[dict[str, Any]] = field(default_factory=list)
    # Evidence normalised from the consumer's finished CI (#36). ``None`` until
    # a CI source is actually read, so a run that consulted no CI records
    # nothing rather than an empty section.
    ci_evidence: CiEvidenceState | None = None
    # True once ``run_static_checks`` has been called this session. Read by the
    # verification tools (D14): an LLM judge may not evaluate a finding before
    # the deterministic checks it is meant to supplement have had their turn.
    static_checks_ran: bool = False
    # Last ``run_static_checks`` report — ``{name, status}`` rows, replaced (not
    # appended) on each call. Read by ``validation_state_from_tool_context`` so
    # ``approve`` is rejected when a required gate recorded ``status: failed``.
    static_checks: list[dict[str, Any]] = field(default_factory=list)

    def iter_finding_rows(self) -> list[dict[str, Any]]:
        """Return every dict-shaped finding row across analyzer and agent lanes."""
        rows: list[dict[str, Any]] = []
        if self.analyzer_run is not None:
            rows.extend(self.analyzer_run.all_rows())
        rows.extend(row for row in self.agent_findings if isinstance(row, dict))
        rows.extend(row for row in self.confirmed_findings if isinstance(row, dict))
        return rows


def record_lens_routing_decision(
    tool_state: ToolState,
    routing_decision: LensRoutingDecision,
) -> None:
    """Persist a lens routing decision before any lens subagent runs (RC7)."""
    tool_state.lens_routing_decision = routing_decision


def record_lens_execution(
    tool_state: ToolState,
    *,
    routing_decision: LensRoutingDecision,
    dispatched_lens_ids: Sequence[str],
) -> None:
    """Persist the routing decision and the lenses that actually ran (RC7)."""
    record_lens_routing_decision(tool_state, routing_decision)
    tool_state.dispatched_lens_ids = tuple(dispatched_lens_ids)


def append_dispatched_lens(tool_state: ToolState, agent_id: str) -> None:
    """Append one lens id when a lens subagent completes (RC7)."""
    from mergecraft.review.lens_routing import lens_id_from_agent_id

    lens_id = lens_id_from_agent_id(agent_id)
    if not lens_id:
        return
    current = tuple(tool_state.dispatched_lens_ids)
    if lens_id in current:
        return
    decision = tool_state.lens_routing_decision
    if decision is None:
        tool_state.dispatched_lens_ids = (*current, lens_id)
        return
    record_lens_execution(
        tool_state,
        routing_decision=decision,
        dispatched_lens_ids=(*current, lens_id),
    )


def repo_key(owner: str, name: str) -> str:
    return f"{owner}/{name}".lower()


def init_tool_state(
    *,
    owner: str,
    name: str,
    dir: str,
    progress_comment: ProgressComment | None = None,
) -> ToolState:
    if progress_comment:
        logger.info(
            "using pre-created progress comment: {} ({})",
            progress_comment.id,
            progress_comment.type,
        )
    primary = repo_key(owner, name)
    repos = {
        primary: RepoToolState(owner=owner, name=name, dir=dir, access="primary"),
    }
    return ToolState(
        repos=repos,
        primary_repo_key=primary,
        progress_comment=progress_comment,
        had_progress_comment=progress_comment is not None,
    )


def primary_repo_state(tool_state: ToolState) -> RepoToolState:
    state = tool_state.repos.get(tool_state.primary_repo_key)
    if state is None:
        msg = "primary repo state not initialized"
        raise RuntimeError(msg)
    return state


def require_repo_state(tool_state: ToolState, owner: str, name: str) -> RepoToolState:
    key = repo_key(owner, name)
    state = tool_state.repos.get(key)
    if state is None:
        msg = f"repo {key} is not a registered checkout — use checkout_repo first"
        raise RuntimeError(msg)
    return state


def ensure_repo_state(
    tool_state: ToolState,
    *,
    owner: str,
    name: str,
    dir: str,
    access: RepoAccess,
) -> RepoToolState:
    key = repo_key(owner, name)
    existing = tool_state.repos.get(key)
    if existing is not None:
        return existing
    created = RepoToolState(owner=owner, name=name, dir=dir, access=access)
    tool_state.repos[key] = created
    return created
