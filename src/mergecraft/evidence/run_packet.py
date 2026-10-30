"""Runtime seam that turns a finished run into an on-disk evidence packet (#96).

Batches A and B (#47, #41, #42, #48) shipped the packet model, the pure
builder, the I/O shell, and the blast-radius classifier — but no consumer.
Nothing under ``action/``, ``cli/`` or ``agents/`` called them, so no run
ever emitted a packet and ``blast_radius`` could only ever be ``None``.
This module is that missing consumer.

It is deliberately the *only* place that knows how to read a live run's
state. The builder stays pure, the classifier stays pure, and everything
environment-shaped (tool state, temp dirs, ``RUNNER_TEMP``) is confined
here. Schema versioning lives in ``mergecraft.evidence.packet``; this module
only assembles and emits packets for a completed run.

Exports:
    build_run_packet: Assemble the packet for a completed run (decision included).
    prepare_run_packet: Assemble once with enforce-mode fail-closed fallback.
    resolve_prepared_run_packet: Return the cached packet snapshot (D7).
    emit_run_packet: Write a pre-assembled packet; never rebuilds.
    resolve_evidence_dir: Resolve the run's evidence directory (shared policy).
    resolve_packet_path: Resolve the stable on-disk destination.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from loguru import logger
from pydantic import ValidationError

from mergecraft.analyzers.dispositions import DispositionCounts
from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.classify import ChangeSet, classify_blast_radius
from mergecraft.evidence.build import build_packet
from mergecraft.evidence.emit import write_packet
from mergecraft.evidence.packet import (
    AnalyzersEvidence,
    DeterministicCheck,
    DispositionSection,
    MergeEvidencePacket,
    ModePromptVersion,
    RunMetrics,
)
from mergecraft.utils.diff_paths import changed_paths_from_diff

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from mergecraft.classify import BlastRadiusClassification
    from mergecraft.evidence.gate_policy import GateActionPolicy
    from mergecraft.mcp.context import ToolContext
    from mergecraft.mcp.tool_state import RepoToolState, ToolState
    from mergecraft.modes import Mode

PACKET_FILENAME = "merge-evidence-packet.json"
"""Stable basename for the emitted packet, under whichever directory wins."""

_PACKET_DIR_ENV = "MERGECRAFT_EVIDENCE_DIR"
"""Operator override for the packet's parent directory."""


def resolve_evidence_dir(*, tmpdir: str) -> Path:
    """Return the directory this run's evidence artefacts live in.

    Resolution order, first hit wins:

    1. ``MERGECRAFT_EVIDENCE_DIR`` — explicit operator override.
    2. ``RUNNER_TEMP/mergecraft`` — the GitHub-provided per-job scratch
       directory. It survives the step, so a later
       ``actions/upload-artifact`` step can read it, and it is *outside* the
       checkout, so an artefact can never be swept into a commit by an agent
       running ``git add -A``.
    3. ``tmpdir/evidence`` — the run's own temp dir (local / offline runs).

    This is the single destination policy for the run's evidence. The packet
    (:func:`resolve_packet_path`) and the opt-in judge-verdict capture
    (:func:`mergecraft.evidence.verdict_capture.resolve_capture_dir`) both
    resolve through it, so a workflow that uploads one finds the other.
    """
    override = os.environ.get(_PACKET_DIR_ENV)
    runner_temp = os.environ.get("RUNNER_TEMP")
    if override:
        return Path(override)
    if runner_temp:
        return Path(runner_temp) / "mergecraft"
    return Path(tmpdir) / "evidence"


def resolve_packet_path(*, tmpdir: str, change_slug: str) -> Path:
    """Return the stable on-disk destination for this run's packet.

    The parent directory comes from :func:`resolve_evidence_dir` (the run's
    evidence policy); ``change_slug`` disambiguates concurrent runs sharing a
    directory in the basename.
    """
    return resolve_evidence_dir(tmpdir=tmpdir) / f"{change_slug}-{PACKET_FILENAME}"


def _slugify(change_id: str) -> str:
    """Reduce a ``owner/repo#123`` change id to a filesystem-safe slug."""
    return "".join(char if char.isalnum() or char in "-_" else "-" for char in change_id).strip("-")


def _read_diff_text(state: RepoToolState) -> str:
    """Return the run's unified diff text, preferring the full-PR diff.

    The incremental diff covers only commits since the last review, so it
    understates blast radius. The packet is evidence for the *merge*, which
    lands the whole PR — so the full diff is authoritative and the
    incremental one is only a fallback.
    """
    for raw in (state.diff_path, state.incremental_diff_path):
        if not raw:
            continue
        path = Path(raw)
        if path.is_file():
            try:
                return path.read_text(encoding="utf-8")
            except OSError as err:
                logger.debug("evidence packet: cannot read {} — {}", path, err)
    return ""


def _read_coverage_scope(state: RepoToolState) -> tuple[str, str | None]:
    """Return the diff that defines *review* scope and its path.

    Unlike :func:`_read_diff_text` (the whole PR, for blast radius), a
    re-review is scoped to the incremental range: that is what the reviewer
    was told to read, so that is what line coverage must measure. The full
    diff is the fallback when no incremental range exists.
    """
    for raw in (state.incremental_diff_path, state.diff_path):
        if not raw:
            continue
        path = Path(raw)
        if not path.is_file():
            continue
        try:
            return path.read_text(encoding="utf-8"), str(path)
        except OSError as err:
            logger.debug("evidence packet: cannot read coverage scope {} — {}", path, err)
    return "", None


def _diff_stats(diff_text: str) -> dict[str, object]:
    """Summarise a diff into the ``diff_stats`` shape the classifier reads.

    The classifier inspects ``diff`` for destructive tokens (``drop table``,
    ``rm -rf``, credential assignments) and ``lines_added`` / ``lines_deleted``
    for its small-isolated-change carve-out.
    """
    added = 0
    deleted = 0
    for line in diff_text.splitlines():
        if line.startswith("+") and not line.startswith("+++ "):
            added += 1
        elif line.startswith("-") and not line.startswith("--- "):
            deleted += 1
    return {"diff": diff_text, "lines_added": added, "lines_deleted": deleted}


def classify_run_blast_radius(diff_text: str) -> BlastRadiusClassification | None:
    """Classify the run's diff, or return ``None`` when there is no diff.

    Returning ``None`` for an empty diff keeps the packet honest: a run with
    nothing to classify records an absent section rather than a fabricated
    ``low`` lane.
    """
    paths = changed_paths_from_diff(diff_text)
    if not paths:
        return None
    change: ChangeSet = {"changed_paths": paths, "diff_stats": _diff_stats(diff_text)}
    return classify_blast_radius(change)


def _deterministic_checks(state: ToolState) -> list[DeterministicCheck]:
    """Project the analyzer run's per-analyzer status rows into packet rows.

    The command string comes from the analyzer catalog manifest, so the
    packet records what actually ran rather than a reconstructed guess. An
    analyzer missing from the catalog still yields a row — dropping it would
    understate the evidence.
    """
    run_state = state.analyzer_run
    rows = list(run_state.analyzers) if run_state is not None else []
    from mergecraft.analyzers.pipeline import CatalogScanStatus, catalog_scan_status
    from mergecraft.analyzers.registry import get_manifest

    checks: list[DeterministicCheck] = []
    if run_state is not None and catalog_scan_status(run_state) == CatalogScanStatus.UNAVAILABLE:
        checks.append(DeterministicCheck(name="analyzers", status="unavailable", command="catalog"))
    elif not rows:
        return []

    for row in rows:
        try:
            command = " ".join(get_manifest(row.id).command)
        except KeyError:
            command = row.id
        checks.append(DeterministicCheck(name=row.id, status=row.status, command=command))
    return checks


def _selected_modes(state: ToolState, ctx: ToolContext) -> Sequence[Mode]:
    """Return the mode that actually ran, as a one-element sequence.

    ``state.selected_mode`` (set by the ``select_mode`` MCP tool in
    ``src/mergecraft/mcp/select_mode.py``) names the mode the agent
    dispatched on; the matching :class:`Mode` object is resolved against
    ``ctx.modes`` (the configured catalog) so the packet records the prompt
    *version* the agent saw. When ``selected_mode`` is unset — an issue
    comment, a run that picked no mode, or an early exit — the returned
    sequence is empty and ``_mode_prompt_versions`` yields no rows. A
    ``selected_mode`` that names an unknown catalog entry degrades to the
    empty sequence rather than a fabricated row, so the packet can never
    lie about a mode it does not have a prompt for.
    """
    selected_name = state.selected_mode
    if not selected_name:
        return ()
    for mode in ctx.modes:
        if mode.name == selected_name:
            return (mode,)
    return ()


def _mode_prompt_versions(modes: Sequence[Mode]) -> list[ModePromptVersion]:
    """Project the modes that actually ran into ``ModePromptVersion`` rows (#145).

    The input is a one-element sequence containing the mode that ran (or
    an empty sequence when no mode was selected). The packet must
    attribute its verdict to the prompt that produced it — emitting a
    row for every mode in ``ctx.modes`` (the *catalog*) instead would
    falsely advertise every catalog mode as having produced this run's
    verdict. Modes without a version yield a row with an empty
    ``prompt_version`` rather than being dropped, so legacy ``Mode``
    objects built before the S5 split still register a row.
    """
    rows: list[ModePromptVersion] = []
    for m in modes:
        name = m.name
        version = m.version or ""
        if not name:
            continue
        rows.append(ModePromptVersion(mode_name=name, prompt_version=version))
    return rows


def _dropped_findings_health(dropped: int) -> Finding | None:
    """Run-health finding recording rows discarded before the approval gate (#623).

    :func:`mergecraft.evidence.findings.load_run_findings_with_drops` discards
    any stored finding row (agent-authored or analyzer) that fails ``Finding``
    validation — the #623 bug let an ``AgentFinding``-shaped row do exactly
    that, invisibly, because a dropped row and "nothing was found" looked
    identical from the packet's side. This makes the loss visible in the
    packet itself instead. ``scope="run"`` keeps it advisory-only:
    ``agents/gates._packet_has_blockers`` excludes run-scoped findings from
    the approval gate by design, so this can never fail a review on its own —
    it can only ever tell a human the evidence undercounted.

    Args:
        dropped (int): Count of rows discarded by ``typed_findings_from_rows_with_drops``.

    Returns:
        Finding | None: A single ``Major``, run-scoped finding naming the
        count, or ``None`` when nothing was dropped.

    Examples:
        >>> _dropped_findings_health(0) is None
        True
        >>> _dropped_findings_health(2).severity
        'Major'
    """
    if dropped <= 0:
        return None
    return make_finding(
        tool="findings-loader",
        rule_id="dropped-finding-rows",
        category="Data Integrity & Atomicity",
        severity="Major",
        confidence="certain",
        message=(
            f"{dropped} finding row(s) failed Finding validation and were discarded "
            "before reaching the approval gate — they never contributed to this "
            "packet's decision"
        ),
        path="",
        start_line=1,
        end_line=1,
        source="trajectory",
        scope="run",
        evidence=[f"dropped_rows={dropped}"],
        remediation=(
            "Check the run log for 'findings loader: dropping malformed finding row' "
            "warnings and fix whatever wrote the row in a shape Finding cannot validate."
        ),
        introduced_by_pr="false",
    )


def _disposition_section(source: Literal["catalog", "ci_sarif"], ledger: Any) -> DispositionSection:
    """Project one disposition ledger into its packet section."""
    summary = ledger.summary()
    return DispositionSection(
        source=source,
        counts=DispositionCounts(
            raw=summary.raw,
            kept=summary.kept,
            merged=summary.merged,
            downgraded=summary.downgraded,
            dropped_by_stage=summary.dropped_by_stage,
        ),
        entries=ledger.entries(),
        suppression_audit=ledger.suppression_audit,
        orphaned_hit_ids=summary.orphaned,
    )


def _open_ledger_health(orphans: list[str]) -> Finding:
    """Run-scoped finding naming the raw analyzer hits no stage accounted for (#941)."""
    shown = ", ".join(orphans[:20])
    more = f" (and {len(orphans) - 20} more)" if len(orphans) > 20 else ""
    return make_finding(
        tool="analyzers",
        rule_id="disposition-ledger-open",
        category="Data Integrity & Atomicity",
        severity="Major",
        confidence="certain",
        message=(
            f"{len(orphans)} raw analyzer hit(s) ended with no recorded disposition — a "
            "pipeline stage lost them without saying why, so this run's analyzer evidence "
            f"cannot be trusted as complete: {shown}{more}"
        ),
        path="",
        start_line=1,
        end_line=1,
        source="trajectory",
        scope="run",
        evidence=[f"orphaned_hit_ids={shown}{more}"],
        remediation=(
            "Find the stage that dropped or merged the hit(s) without recording a "
            "disposition (see the analyzer pipeline's stage functions) and make it record one."
        ),
        introduced_by_pr="false",
    )


def _analyzers_evidence(state: ToolState) -> tuple[AnalyzersEvidence | None, list[str]]:
    """Build the packet's ``analyzers`` section; also return the orphaned hit ids.

    Total by construction: the ledger is supplementary evidence about the evidence, so
    a malformed one degrades to a missing section and never fails packet assembly.
    """
    run_state = state.analyzer_run
    sarif_ledger = state.ci_evidence.sarif_dispositions if state.ci_evidence is not None else None
    sections: list[DispositionSection] = []
    orphans: list[str] = []
    try:
        if run_state is not None and run_state.dispositions is not None:
            section = _disposition_section("catalog", run_state.dispositions)
            sections.append(section)
            orphans.extend(section.orphaned_hit_ids)
        if sarif_ledger is not None:
            sarif_section = _disposition_section("ci_sarif", sarif_ledger)
            sections.append(sarif_section)
            orphans.extend(sarif_section.orphaned_hit_ids)
    except (ValidationError, ValueError, TypeError) as err:
        logger.warning("evidence packet: disposition ledger could not be projected — {}", err)
        sections = []
        orphans = []
    resolved_from = run_state.settings_resolved_from if run_state is not None else None
    detail = run_state.settings_detail if run_state is not None else None
    if not sections and resolved_from is None:
        return None, orphans
    return (
        AnalyzersEvidence(
            settings_resolved_from=resolved_from,
            settings_detail=detail,
            dispositions=sections,
        ),
        orphans,
    )


def _self_assessment(state: ToolState) -> dict[str, Any] | None:
    """Translate the legacy ``ApprovalRecord`` into the packet's input shape.

    ``build_packet`` already maps ``would_approve`` onto ``approved``; this
    only has to hand it the dict.
    """
    approval = state.approval
    if approval is None:
        return None
    return {"would_approve": approval.would_approve, "sha": approval.sha}


def _finalize_packet_with_gate(
    packet: MergeEvidencePacket,
    *,
    ctx: ToolContext,
    run_succeeded: bool,
    decision_reason_suffix: str | None = None,
    pinned: bool = False,
) -> MergeEvidencePacket:
    """Attach structural verdict and gate action to an assembled packet."""
    from mergecraft.agents.gates import decide_action, decide_approval

    gate_mode = _resolve_gate_mode(ctx, pinned=pinned)
    gate_policy = _resolve_gate_policy(ctx, pinned=pinned)
    decision = decide_approval(packet, run_succeeded=run_succeeded, tier=ctx.authority_trust)
    packet_with_decision = packet.model_copy(update={"decision": decision})
    action = decide_action(packet_with_decision, mode=gate_mode, policy=gate_policy)
    reason = decision.reason
    if decision_reason_suffix:
        reason = f"{reason}; {decision_reason_suffix}"
    final_decision = decision.model_copy(
        update={
            "action": action.value,
            "decided_by_action": "mergecraft.agents.gates.decide_action",
            "mode": gate_mode,
            "reason": reason,
        }
    )
    return packet_with_decision.model_copy(update={"decision": final_decision})


_ANALYZER_TOOLS: frozenset[str] = frozenset(
    {"run_analyzers", "run_static_checks", "analyze_ci_failures", "analyzer_findings"}
)
_JUDGE_TOOLS: frozenset[str] = frozenset({"verify_agent_findings", "record_finding_verdict"})


def _read_tool_turns(calls: Sequence[Any]) -> int:
    """Count runs of consecutive read-intent calls.

    MCP has no assistant-turn boundary, so this is the cheap proxy for
    "batched independent reads": one read call is one turn, and N adjacent
    read calls are one turn. Dependent calls break the run naturally.
    """
    turns = 0
    previous_read = False
    for call in calls:
        is_read = getattr(call, "intent", None) == "read"
        if is_read and not previous_read:
            turns += 1
        previous_read = is_read
    return turns


def _run_metrics(
    ctx: ToolContext,
    *,
    trajectory: Any,
    diff_text: str,
    now: Callable[[], float] = time.monotonic,
) -> RunMetrics:
    """Build the measurement-only run metrics (slice 7).

    The ``agent`` phase is stamped in ``main.py`` only *after* the dispatch
    returns, so a record rendered inside the terminal publish call would read
    ``agent 0s`` on exactly the runs that self-publish (#1075). When the stamp
    is missing but the dispatch start marker exists, the honest value is the
    elapsed-so-far. ``publish`` gets no such fill-in: it is stamped after the
    publish call returns, which is structurally after its own record renders,
    so an unstamped ``publish`` is omitted rather than rendered as ``0s``.
    """
    state = ctx.tool_state
    calls = list(getattr(trajectory, "tool_calls", []) or [])
    phases = dict(getattr(state, "phase_elapsed_s", {}) or {})
    analyzer_ms = sum(
        int(getattr(call, "duration_ms", 0) or 0)
        for call in calls
        if getattr(call, "tool", "") in _ANALYZER_TOOLS
    )
    judge_ms = sum(
        int(getattr(call, "duration_ms", 0) or 0)
        for call in calls
        if getattr(call, "tool", "") in _JUDGE_TOOLS
    )
    phases.setdefault("analyzers", round(analyzer_ms / 1000, 3))
    phases.setdefault("judge", round(judge_ms / 1000, 3))
    if "agent" not in phases:
        agent_started = getattr(state, "agent_started_monotonic", None)
        phases["agent"] = round(now() - agent_started, 3) if agent_started is not None else 0.0
    phases.setdefault("setup", 0.0)
    # ``publish`` gets no setdefault: the stamp lands after
    # ``publish_pull_request_review`` returns, while the record renders inside
    # that call, so an unstamped publish must be omitted rather than rendered
    # as ``0s`` (#1075). A genuinely stamped value still renders.
    added = deleted = 0
    for line in diff_text.splitlines():
        if line.startswith("+") and not line.startswith("+++ "):
            added += 1
        elif line.startswith("-") and not line.startswith("--- "):
            deleted += 1
    diagnostic = getattr(state, "agent_diagnostic", None)
    diagnostic_text = None
    if isinstance(diagnostic, dict):
        diagnostic_text = diagnostic.get("diagnostic")
    return RunMetrics(
        tool_calls=len(calls),
        read_tool_calls=sum(1 for call in calls if getattr(call, "intent", None) == "read"),
        read_tool_turns=_read_tool_turns(calls),
        distinct_files_read=len(set(getattr(trajectory, "files_read", []) or [])),
        diff_lines=len(diff_text.splitlines()),
        diff_added_lines=added,
        diff_deleted_lines=deleted,
        phase_elapsed_s={
            key: round(float(value), 3) for key, value in phases.items() if value is not None
        },
        agent_diagnostic=diagnostic_text,
    )


def _assemble_packet_core(
    ctx: ToolContext,
    *,
    change_id: str,
    files_changed: list[str],
    findings: list[Finding],
    deterministic_checks: list[DeterministicCheck],
    blast_radius: BlastRadiusClassification | None,
    trajectory: dict[str, Any] | None,
    analyzers: AnalyzersEvidence | None = None,
    run_metrics: RunMetrics | None = None,
) -> MergeEvidencePacket:
    """Shared evidence shell for happy-path and fail-closed packet assembly."""
    state = ctx.tool_state
    executed_model = ctx.resolved_model or state.model or "(unresolved)"
    requested_model = state.requested_model or executed_model
    provider = _provider_for_model_evidence(
        executed_model=executed_model,
        requested_model=requested_model,
        agent_id=ctx.agent_id,
    )
    packet = build_packet(
        change_id=change_id,
        agent_id=ctx.agent_id,
        agent_version=_agent_version(),
        model=executed_model,
        requested_model=requested_model,
        executed_model=executed_model,
        provider=provider,
        fallback_index=state.fallback_index,
        fallback_occurred=state.fallback_occurred,
        files_changed=files_changed,
        findings=findings,
        deterministic_checks=deterministic_checks,
        self_assessment=_self_assessment(state),
        blast_radius=blast_radius,
        trajectory=trajectory,
        mode_prompt_versions=_mode_prompt_versions(_selected_modes(state, ctx)),
        dispatched_lens_ids=list(state.dispatched_lens_ids),
        agent_terminal_verdict=(
            state.terminal_submission.verdict if state.terminal_submission is not None else None
        ),
        analyzers=analyzers,
        run_metrics=run_metrics,
    )
    return packet.model_copy(
        update={
            "reviewed_head_sha": _run_bound_reviewed_head_sha(state),
            "progress_comment_id": _run_bound_progress_comment_id(state),
        }
    )


def _run_bound_reviewed_head_sha(state: ToolState) -> str | None:
    """Return the PR head this run checked out, or ``None`` (HS8).

    The value comes from the run's own checkout state, so it is orchestrator-written
    and never agent-controlled.
    """
    from mergecraft.mcp.tool_state import primary_repo_state

    return primary_repo_state(state).checkout_sha or None


def _run_bound_progress_comment_id(state: ToolState) -> int | None:
    """Return the sticky comment id this run owns, or ``None`` (HS8).

    Only an active ``ProgressComment`` names a sticky; an unset or deliberately
    deleted comment records ``None`` rather than a fabricated id.
    """
    from mergecraft.mcp.tool_state import ProgressComment

    progress = state.progress_comment
    if not isinstance(progress, ProgressComment):
        return None
    try:
        return int(progress.id)
    except (TypeError, ValueError):
        return None


def build_run_packet(
    ctx: ToolContext,
    *,
    run_succeeded: bool,
    change_id: str | None = None,
    extra_findings: list[Finding] | None = None,
    in_flight_tool: str | None = None,
) -> MergeEvidencePacket:
    """Assemble the packet for a completed run, decision included.

    The decision is computed in two passes because the gate consumes a
    packet: build the evidence, hand it to ``decide_approval``, then attach
    the returned verdict. That keeps the verdict a pure function of the
    evidence actually recorded, rather than of a parallel set of inputs.
    ``change_id`` defaults to the PR-derived identifier on ``ctx``.

    ``in_flight_tool`` names the tool call this assembly runs inside of, when
    the caller is a tool body (#1074): the terminal publish call is appended
    to the trajectory only after it returns, so the trajectory audit needs
    the name to see the completion signal being sent right now.
    """
    from mergecraft.evidence.findings import load_run_findings_with_drops
    from mergecraft.mcp.tool_state import primary_repo_state

    resolved_change_id = change_id or _change_id(ctx)
    if resolved_change_id is None:
        msg = "evidence packet: run has no pull request"
        raise ValueError(msg)

    state = ctx.tool_state
    repo_state = primary_repo_state(state)
    diff_text = _read_diff_text(repo_state)
    blast_radius = classify_run_blast_radius(diff_text)

    from mergecraft.evidence.trajectory import build_trajectory_record
    from mergecraft.evidence.trajectory_audit import audit_trajectory

    changed_paths = changed_paths_from_diff(diff_text)
    coverage_diff, coverage_path = _read_coverage_scope(repo_state)
    # Plan 12 D2/D4: trajectory findings are run-scoped and partition into
    # ``run_health`` at build time. They are advisory-only — never block via
    # ``blocking_findings`` — while gate-policy predicates still read them from
    # ``run_health.findings`` (see ``agents/gates._packet_attested_findings``).
    trajectory = build_trajectory_record(state, files_modified=changed_paths)
    trajectory_findings = audit_trajectory(
        trajectory,
        diff_text=coverage_diff or None,
        diff_path=coverage_path,
        in_flight_tool=in_flight_tool,
    )
    run_metrics = _run_metrics(ctx, trajectory=trajectory, diff_text=diff_text)

    loaded_findings, dropped_finding_rows = load_run_findings_with_drops(ctx, extra=extra_findings)
    health_finding = _dropped_findings_health(dropped_finding_rows)
    run_health_findings = [health_finding] if health_finding is not None else []

    # #941 closure check: every raw analyzer hit must have ended with a disposition.
    # An open ledger makes the run inconclusive (a non-passing run → ``neutral`` at
    # best) and a run-scoped finding names the orphans. ``run_succeeded=False`` never
    # outranks a blocker: ``decide_approval`` is monotone in blockers.
    analyzers_evidence, orphaned_hits = _analyzers_evidence(state)
    ledger_findings = [_open_ledger_health(orphaned_hits)] if orphaned_hits else []

    packet = _assemble_packet_core(
        ctx,
        change_id=resolved_change_id,
        files_changed=changed_paths,
        findings=[
            *loaded_findings,
            *run_health_findings,
            *ledger_findings,
            *trajectory_findings,
        ],
        deterministic_checks=_deterministic_checks(state),
        blast_radius=blast_radius,
        trajectory=trajectory.model_dump(mode="json"),
        analyzers=analyzers_evidence,
        run_metrics=run_metrics,
    )
    return _finalize_packet_with_gate(
        packet,
        ctx=ctx,
        run_succeeded=run_succeeded and not orphaned_hits,
        decision_reason_suffix=_open_ledger_reason(orphaned_hits),
    )


def _agent_version() -> str:
    from mergecraft import __version__

    return __version__


def _provider_for_model_evidence(
    *,
    executed_model: str,
    requested_model: str,
    agent_id: str,
) -> str:
    """Resolve a truthy provider label for packet agent metadata (W10.2).

    Prefer the executed slug's catalog provider; fall back to the requested
    slug, then the agent id (always set on ``ToolContext``), then ``unknown``.
    """
    from mergecraft.models import get_model_provider

    for slug in (executed_model, requested_model):
        if not slug or slug == "(unresolved)":
            continue
        try:
            return get_model_provider(slug)
        except ValueError:
            continue
    if agent_id:
        return str(agent_id)
    return "unknown"


def _resolve_gate_mode(ctx: ToolContext, *, pinned: bool = False) -> str:
    """Return the gate mode (``shadow`` / ``enforce``) for this run.

    D5 / MCB-17: read ``gates.gate_action`` from the AG2 settings snapshot
    on ``ToolContext``, not from package defaults. D12: every new gate
    defaults to ``shadow``. Pydantic validation on ``GateMode`` ensures a
    typo'd value widens to ``shadow``, never to ``enforce``.

    When ``pinned`` is true, use the snapshotted value without re-checking
    disk — for fail-closed assembly paths that must not throw on config drift.
    """
    from mergecraft.config import default_settings
    from mergecraft.config.settings_snapshot import (
        pinned_repo_settings_from_context,
        repo_settings_from_context,
    )

    if pinned:
        settings = pinned_repo_settings_from_context(ctx)
        if settings is not None:
            return settings.gates.gate_action
        return default_settings().gates.gate_action
    return repo_settings_from_context(ctx).gates.gate_action


def _resolve_gate_policy(ctx: ToolContext, *, pinned: bool = False) -> GateActionPolicy:
    """Merge repo ``gates.override`` onto the default gate-action policy."""
    from mergecraft.config import default_settings
    from mergecraft.config.settings_snapshot import (
        pinned_repo_settings_from_context,
        repo_settings_from_context,
    )
    from mergecraft.evidence.gate_policy import resolve_effective_gate_policies

    if pinned:
        settings = pinned_repo_settings_from_context(ctx)
        if settings is None:
            settings = default_settings()
    else:
        settings = repo_settings_from_context(ctx)
    return resolve_effective_gate_policies(settings.gates.override)


def _shadow_run_id(ctx: ToolContext) -> str:
    """Return a stable per-run identifier for the shadow record.

    The shadow record carries the run id so the disagreement report can
    join the audit row back to the run that produced it. ``GITHUB_RUN_ID``
    is the canonical GitHub Actions identifier; falls back to the
    payload delivery id, then ``"local"`` so offline runs still emit a row.
    """
    run_id = os.environ.get("GITHUB_RUN_ID")
    if run_id:
        return run_id
    extra = ctx.payload.extra
    delivery_id = extra.get("delivery_id") or extra.get("deliveryId")
    if isinstance(delivery_id, str) and delivery_id:
        return delivery_id
    return "local"


def _change_id(ctx: ToolContext) -> str | None:
    """Return ``owner/repo#123`` for a PR run, or ``None`` when there is no change.

    The packet is evidence *for one proposed merge*. A run with no pull
    request (an issue comment, a scheduled job) has no merge to attest to,
    so it emits nothing rather than a packet with an invented ``change_id``.
    """
    pull_number = ctx.tool_state.pr_number or ctx.payload.event.issue_number
    if not isinstance(pull_number, int) or ctx.payload.event.is_pr is not True:
        return None
    return f"{ctx.repo.owner}/{ctx.repo.name}#{pull_number}"


def _fail_closed_assembly_packet(
    ctx: ToolContext,
    *,
    change_id: str,
    run_succeeded: bool,
    reason: str,
) -> MergeEvidencePacket:
    """Return a neutral packet when assembly fails in ``enforce`` mode (MCB-17)."""
    packet = _assemble_packet_core(
        ctx,
        change_id=change_id,
        files_changed=[],
        findings=[],
        deterministic_checks=[],
        blast_radius=None,
        trajectory=None,
    )
    return _finalize_packet_with_gate(
        packet,
        ctx=ctx,
        run_succeeded=run_succeeded,
        decision_reason_suffix=f"assembly failed — {reason}",
        pinned=True,
    )


def _cached_packet_shell(cached: MergeEvidencePacket) -> MergeEvidencePacket:
    """Return the cached evidence shell without a baked-in decision row."""
    if cached.decision is None:
        return cached
    return cached.model_copy(update={"decision": None})


def _orphaned_hit_ids(packet: MergeEvidencePacket) -> list[str]:
    """Every raw analyzer hit the packet's ledgers leave unaccounted for (#941)."""
    analyzers = packet.analyzers
    if analyzers is None:
        return []
    orphans: list[str] = []
    for section in analyzers.dispositions:
        orphans.extend(section.orphaned_hit_ids)
    return orphans


def _open_ledger_reason(orphans: list[str]) -> str | None:
    """The decision-reason suffix an open ledger carries, or ``None`` when closed."""
    if not orphans:
        return None
    return f"analyzer disposition ledger open ({len(orphans)} orphaned hit(s)) — inconclusive"


def resolve_prepared_run_packet(
    ctx: ToolContext,
    *,
    run_succeeded: bool,
    change_id: str | None = None,
    extra_findings: list[Finding] | None = None,
    in_flight_tool: str | None = None,
) -> MergeEvidencePacket | None:
    """Return the run's cached packet snapshot, assembling it at most once (D7).

    The review-body preamble and the sticky progress comment must render from
    the same evidence shell so findings cannot drift between publish time and
    finalize. The structural decision is re-finalized on every call so a
    publish-time ``run_succeeded=True`` snapshot does not stick when finalize
    reports failed, timed_out, or inconclusive. ``in_flight_tool`` is used only
    on the first (assembling) call — the cached shell already carries the
    audit outcome it produced.
    """
    cached = ctx.tool_state.prepared_run_packet
    if cached is not None:
        shell = _cached_packet_shell(
            cast("MergeEvidencePacket", cached),  # prepared_run_packet is Any on ToolState
        )
        if shell is not cached:
            ctx.tool_state.prepared_run_packet = shell
        # A re-finalization must reach the same verdict the first assembly would:
        # the cached shell already names an open ledger's orphans, so the
        # correction below cannot live only on the assembly path (#941).
        orphans = _orphaned_hit_ids(shell)
        return _finalize_packet_with_gate(
            shell,
            ctx=ctx,
            run_succeeded=run_succeeded and not orphans,
            decision_reason_suffix=_open_ledger_reason(orphans),
        )
    packet = prepare_run_packet(
        ctx,
        run_succeeded=run_succeeded,
        change_id=change_id,
        extra_findings=extra_findings,
        in_flight_tool=in_flight_tool,
    )
    if packet is not None:
        ctx.tool_state.prepared_run_packet = _cached_packet_shell(packet)
    return packet


def prepare_run_packet(
    ctx: ToolContext,
    *,
    run_succeeded: bool,
    change_id: str | None = None,
    extra_findings: list[Finding] | None = None,
    in_flight_tool: str | None = None,
) -> MergeEvidencePacket | None:
    """Assemble once. ``None`` means skip write/approval, never rebuild."""
    resolved = change_id or _change_id(ctx)
    if resolved is None:
        return None
    try:
        return build_run_packet(
            ctx,
            change_id=resolved,
            run_succeeded=run_succeeded,
            extra_findings=extra_findings,
            in_flight_tool=in_flight_tool,
        )
    except (KeyError, OSError, RuntimeError, ValueError, ValidationError) as err:
        logger.warning("evidence packet: assembly failed — {}", err)
        if _resolve_gate_mode(ctx, pinned=True) == "enforce":
            return _fail_closed_assembly_packet(
                ctx,
                change_id=resolved,
                run_succeeded=run_succeeded,
                reason=str(err),
            )
        return None


def _resolve_shadow_tracer(ctx: ToolContext) -> Any | None:
    """Resolve a tracer for the shadow span, or ``None`` when unavailable.

    Best-effort by construction: tracing must never fail the run, so every
    resolution failure degrades to ``None`` (a silent no-op span). The shadow
    recorder still writes its JSONL row either way — the row is the audit trail
    and the span is the optional second surface (#737).
    """
    try:
        from mergecraft.config.settings_snapshot import repo_settings_from_context
        from mergecraft.tracing.tracer import get_tracer_from_settings

        return get_tracer_from_settings(repo_settings_from_context(ctx))
    except Exception as tracer_err:  # pragma: no cover — tracing is non-fatal
        logger.debug("shadow record: tracer resolution failed — {}", tracer_err)
        return None


def emit_run_packet(
    ctx: ToolContext,
    *,
    change_id: str | None = None,
    output_path: Path | None = None,
    verdict_prediction: Any | None = None,
    actual_outcome: str | None = None,
    packet: MergeEvidencePacket | None = None,
) -> Path | None:
    """Write this run's evidence packet; return its path.

    Best-effort by construction: a packet is an audit artifact, so failing
    to write one must never turn a successful review into a failed run. All
    failures are logged and swallowed, and ``None`` means "no packet", never
    "the run is broken".

    Assembly belongs on :func:`prepare_run_packet` / :func:`build_run_packet`.
    Pass that result as ``packet``; this function does not rebuild.
    """
    assembled = packet
    if assembled is None:
        return None
    resolved_change_id = change_id or assembled.change_id or _change_id(ctx)
    if resolved_change_id is None:
        logger.debug("evidence packet: run has no pull request — nothing to attest")
        return None

    try:
        path = output_path or resolve_packet_path(
            tmpdir=ctx.tmpdir, change_slug=_slugify(resolved_change_id)
        )
        written = write_packet(assembled, output_path=path)
        # W10.2 (#50): in shadow mode the predicted action is recorded as
        # an audit breadcrumb beside the packet. The record is the row
        # the disagreement report reads; the gate itself is never
        # applied (D11, D12). The shadow recorder is a no-op in enforce
        # mode — applying the action is the gate's job, not a side
        # effect of emit.
        if assembled.decision is not None and assembled.decision.mode == "shadow":
            from mergecraft.evidence.shadow import record_pinned_targets

            shadow_path = path.with_name("merge-evidence-shadow.jsonl")
            try:
                record_pinned_targets(
                    assembled,
                    change_id=resolved_change_id,
                    run_id=_shadow_run_id(ctx),
                    output_path=shadow_path,
                    tracer=_resolve_shadow_tracer(ctx),
                )
            except Exception as shadow_err:  # a shadow record never fails the run
                logger.warning("shadow record: emission failed — {}", shadow_err)
        if verdict_prediction is not None:
            from mergecraft.evidence.shadow import live_target_for_packet, record_shadow_prediction

            shadow_path = path.with_name("merge-evidence-shadow.jsonl")
            try:
                record_shadow_prediction(
                    assembled,
                    change_id=resolved_change_id,
                    run_id=_shadow_run_id(ctx),
                    policy_id="verdict-protocol",
                    output_path=shadow_path,
                    prediction=verdict_prediction,
                    actual_outcome=actual_outcome,
                    target=live_target_for_packet(assembled),
                    tracer=_resolve_shadow_tracer(ctx),
                )
            except Exception as shadow_err:  # a shadow record never fails the run
                logger.warning("verdict-protocol shadow record: emission failed — {}", shadow_err)
    except Exception as err:  # an audit artifact never fails the run
        logger.warning("evidence packet: emission failed — {}", err)
        return None
    lane = assembled.blast_radius.lane if assembled.blast_radius else "(unclassified)"
    verdict = assembled.decision.verdict if assembled.decision else "(none)"
    action = assembled.decision.action if assembled.decision else "(none)"
    mode = assembled.decision.mode if assembled.decision else "(none)"
    # W9.3 — the action is the next required action: the only thing the
    # operator or downstream gate needs to act on. The numeric score
    # never appears; verdict + action + lane + mode is the full wire.
    logger.info(
        "» merge evidence packet: {} (change={}, lane={}, verdict={}, action={}, mode={})",
        written,
        resolved_change_id,
        lane,
        verdict,
        action,
        mode,
    )
    return written


__all__ = [
    "PACKET_FILENAME",
    "build_run_packet",
    "classify_run_blast_radius",
    "emit_run_packet",
    "prepare_run_packet",
    "resolve_evidence_dir",
    "resolve_packet_path",
    "resolve_prepared_run_packet",
]
