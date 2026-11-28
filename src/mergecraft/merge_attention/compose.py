"""Compose merge-attention grade from deterministic run evidence (#1610)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mergecraft.merge_attention.e2e_proof import (
    detect_user_facing_changes,
    scan_e2e_proof,
    verification_gaps_for_user_facing,
)
from mergecraft.merge_attention.rubric import lane_to_attention, max_level
from mergecraft.merge_attention.types import (
    AXIS_ORDER,
    AttentionLevel,
    AxisVerdict,
    MergeAttentionSection,
    VerdictSource,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mergecraft.config.settings import MergeAttentionSettings
    from mergecraft.evidence.packet import MergeEvidencePacket
    from mergecraft.mcp.context import ToolContext
    from mergecraft.policy.evidence_producers import PolicyEvidence


@dataclass(frozen=True, slots=True)
class MergeAttentionInputs:
    """Optional run-local inputs not stored on the packet."""

    policy_evidence: PolicyEvidence | None = None
    static_checks: Sequence[dict[str, Any]] | None = None
    pr_body: str | None = None
    review_summary: str | None = None
    run_artifact_paths: Sequence[str] | None = None
    verified_fingerprint_count: int = 0
    analyzer_ran: bool = False
    ci_failed: bool = False


def _blast_codes(packet: MergeEvidencePacket) -> set[str]:
    blast = packet.blast_radius
    if blast is None:
        return set()
    return {str(reason.code) for reason in blast.reasons if getattr(reason, "code", None)}


def _axis_impact(packet: MergeEvidencePacket) -> AxisVerdict:
    blast = packet.blast_radius
    lane = getattr(blast, "lane", None) if blast is not None else None
    level = lane_to_attention(str(lane) if lane is not None else None)
    codes = sorted(_blast_codes(packet))
    tail = f" ({', '.join(codes[:4])})" if codes else ""
    return AxisVerdict(
        axis="impact",
        level=level,
        verdict=f"Blast-radius lane is `{lane or 'unknown'}`{tail}.",
        source="deterministic",
    )


def _policy_key_present(evidence: PolicyEvidence | None, key: str) -> bool | None:
    if evidence is None:
        return None
    return key in evidence.present


def _axis_rollback(
    packet: MergeEvidencePacket,
    evidence: PolicyEvidence | None,
) -> AxisVerdict:
    codes = _blast_codes(packet)
    destructive = bool(
        codes
        & {
            "paths.migrations",
            "diff.destructive_sql",
            "paths.irreversible_infra",
            "diff.irreversible_command",
            "diff.data_deletion_outside",
        }
    )
    present = _policy_key_present(evidence, "rollback_plan")
    if destructive and present is False:
        return AxisVerdict(
            axis="rollback_cost",
            level="high",
            verdict="Destructive or migration-like change with no `rollback_plan` policy evidence.",
            source="deterministic",
        )
    if destructive and present is True:
        return AxisVerdict(
            axis="rollback_cost",
            level="low",
            verdict="Destructive change carries declared `rollback_plan` evidence.",
            source="deterministic",
        )
    if present is False:
        return AxisVerdict(
            axis="rollback_cost",
            level="medium",
            verdict="No `rollback_plan` evidence was collected for this run.",
            source="deterministic",
        )
    if present is True:
        return AxisVerdict(
            axis="rollback_cost",
            level="low",
            verdict="Declared `rollback_plan` evidence is present.",
            source="deterministic",
        )
    lane = lane_to_attention(
        getattr(packet.blast_radius, "lane", None) if packet.blast_radius else None
    )
    return AxisVerdict(
        axis="rollback_cost",
        level=lane,
        verdict="Rollback cost tracks blast-radius lane; no rollback policy evidence was required.",
        source="deterministic",
    )


def _axis_error_detection(
    packet: MergeEvidencePacket,
    evidence: PolicyEvidence | None,
) -> AxisVerdict:
    present = _policy_key_present(evidence, "health_check")
    lane = lane_to_attention(
        getattr(packet.blast_radius, "lane", None) if packet.blast_radius else None
    )
    if present is True:
        return AxisVerdict(
            axis="error_detection",
            level="low",
            verdict="Declared `health_check` evidence is present for production detection.",
            source="deterministic",
        )
    if present is False and lane == "high":
        return AxisVerdict(
            axis="error_detection",
            level="high",
            verdict="High-impact change without `health_check` policy evidence.",
            source="deterministic",
        )
    if present is False:
        return AxisVerdict(
            axis="error_detection",
            level="medium",
            verdict="No `health_check` evidence; monitoring proof was not collected.",
            source="deterministic",
        )
    return AxisVerdict(
        axis="error_detection",
        level=lane,
        verdict="Error-detection posture follows blast-radius; no health-check evidence required.",
        source="deterministic",
    )


def _mechanical_failed(checks: Sequence[dict[str, Any]] | None) -> bool:
    for row in checks or ():
        status = str(row.get("status") or row.get("conclusion") or "").lower()
        if status in {"failed", "failure", "error"}:
            return True
    return False


def _axis_verification(
    packet: MergeEvidencePacket,
    inputs: MergeAttentionInputs,
    settings: MergeAttentionSettings,
) -> AxisVerdict:
    gaps = verification_gaps_for_user_facing(
        detect_user_facing_changes(
            packet.files_changed,
            user_facing_globs=settings.user_facing_globs or None,
            perf_globs=settings.perf_sensitive_globs or None,
        ),
        scan_e2e_proof(
            pr_body=inputs.pr_body,
            review_summary=inputs.review_summary,
            run_artifact_paths=inputs.run_artifact_paths,
        ),
    )
    from mergecraft.agents.gates import blocking_findings

    blockers = blocking_findings(list(packet.findings))
    level: AttentionLevel = "low"
    if gaps or blockers:
        level = "high" if blockers else "medium"
    elif inputs.ci_failed or _mechanical_failed(inputs.static_checks) or not inputs.analyzer_ran:
        level = "medium"
    pieces: list[str] = []
    if inputs.analyzer_ran:
        pieces.append("Deterministic analyzers ran on this change.")
    else:
        pieces.append("Analyzers did not run or recorded no scope.")
    if inputs.verified_fingerprint_count:
        pieces.append(f"Verifier confirmed {inputs.verified_fingerprint_count} finding(s).")
    if inputs.ci_failed:
        pieces.append("CI reported failures on the PR head.")
    if blockers:
        pieces.append(f"{len(blockers)} blocking finding(s) remain.")
    verdict = " ".join(pieces) if pieces else "Verification signals are thin."
    return AxisVerdict(
        axis="verification",
        level=level,
        verdict=verdict,
        source="deterministic",
        verification_gaps=gaps,
    )


def _axis_alignment(packet: MergeEvidencePacket) -> AxisVerdict:
    from mergecraft.agents.gates import blocking_findings

    codes = _blast_codes(packet)
    level: AttentionLevel = "low"
    source: VerdictSource = "deterministic"
    if {
        "scope.drift",
        "scope.invalid",
        "scope.undeclared",
        "fix.not-proven",
        "fix.no-receipt",
    } & codes:
        level = "medium"
        verdict = "Scope or fix-proof signals suggest the change may not match declared intent."
    elif "scope.unknown" in codes:
        level = "medium"
        verdict = "Declared scope was not read; alignment with linked issues is uncertain."
    elif packet.agent_terminal_verdict == "request_changes":
        level = "medium"
        source = "model"
        verdict = "Reviewer recorded `request_changes` (model judgement on alignment risk)."
    elif packet.agent_terminal_verdict == "approve" and blocking_findings(list(packet.findings)):
        level = "high"
        source = "model"
        verdict = (
            "Terminal approval with blocking findings present — alignment tension "
            "(model judgement)."
        )
    elif packet.self_assessment is not None and packet.self_assessment.approved is False:
        level = "medium"
        source = "model"
        verdict = "Recorded self-assessment was not approving (model judgement)."
    else:
        verdict = (
            "No scope-drift or fix-proof lane reasons; alignment looks consistent with evidence."
        )
    return AxisVerdict(axis="alignment", level=level, verdict=verdict, source=source)


def compose_merge_attention(
    packet: MergeEvidencePacket,
    *,
    inputs: MergeAttentionInputs | None = None,
    settings: MergeAttentionSettings | None = None,
) -> MergeAttentionSection:
    """Build the merge-attention section from a finalized packet."""
    from mergecraft.config.settings import MergeAttentionSettings

    resolved_settings = settings or MergeAttentionSettings()
    resolved_inputs = inputs or MergeAttentionInputs()
    axes_by_name = {
        "alignment": _axis_alignment(packet),
        "impact": _axis_impact(packet),
        "verification": _axis_verification(packet, resolved_inputs, resolved_settings),
        "rollback_cost": _axis_rollback(packet, resolved_inputs.policy_evidence),
        "error_detection": _axis_error_detection(packet, resolved_inputs.policy_evidence),
    }
    axes = [axes_by_name[name] for name in AXIS_ORDER]
    overall = max_level(*(axis.level for axis in axes))
    return MergeAttentionSection(overall=overall, axes=axes)


def merge_attention_section_for_run(
    packet: MergeEvidencePacket,
    ctx: ToolContext,
    settings: MergeAttentionSettings | None = None,
) -> MergeAttentionSection | None:
    """Compose the grade when enabled for packet and/or summary output."""
    from mergecraft.config.settings_snapshot import repo_settings_from_context

    resolved = settings or repo_settings_from_context(ctx).review.merge_attention
    if not resolved.enabled:
        return None
    if not resolved.include_in_packet and not resolved.display_in_summary:
        return None
    return compose_merge_attention(
        packet,
        inputs=inputs_from_context(ctx),
        settings=resolved,
    )


def inputs_from_context(ctx: ToolContext) -> MergeAttentionInputs:
    """Gather run-local evidence for merge-attention composition."""
    from mergecraft.mcp.tool_state import primary_repo_state

    state = ctx.tool_state
    policy_evidence = None
    evaluation = getattr(state, "policy_evaluation", None)
    if evaluation is not None:
        policy_evidence = getattr(evaluation, "evidence", None)
    analyzer = state.analyzer_run
    ci_failed = any(
        "fail" in note.lower()
        for note in (state.ci_evidence.run_notes if state.ci_evidence else [])
    )
    pr_body: str | None = None
    payload = getattr(ctx, "payload", None)
    if payload is not None:
        event = getattr(payload, "event", None)
        if event is not None:
            pull = getattr(event, "pull_request", None)
            if isinstance(pull, dict):
                body = pull.get("body")
                if isinstance(body, str):
                    pr_body = body
            if pr_body is None:
                body = getattr(event, "body", None)
                if isinstance(body, str) and body.strip():
                    pr_body = body
    summary = None
    if state.terminal_submission is not None:
        summary = str(getattr(state.terminal_submission, "summary", "") or "") or None
    run_artifacts: list[str] = []
    tmpdir = getattr(ctx, "tmpdir", None)
    if tmpdir:
        from mergecraft.evidence.run_packet import resolve_evidence_dir

        root = resolve_evidence_dir(tmpdir=str(tmpdir))
        if root.is_dir():
            for path in root.rglob("*"):
                if path.is_file():
                    run_artifacts.append(str(path.relative_to(root)))
    _ = primary_repo_state(state)  # reserved for future PR body fallback via API
    return MergeAttentionInputs(
        policy_evidence=policy_evidence,
        static_checks=list(state.static_checks),
        pr_body=pr_body,
        review_summary=summary,
        run_artifact_paths=run_artifacts,
        verified_fingerprint_count=len(state.verified_ids),
        analyzer_ran=bool(analyzer and analyzer.ran),
        ci_failed=ci_failed,
    )


def attach_merge_attention_to_packet(
    packet: MergeEvidencePacket,
    ctx: ToolContext,
) -> MergeEvidencePacket:
    """Attach merge-attention when enabled; never mutates gating inputs."""
    from mergecraft.config.settings_snapshot import repo_settings_from_context

    settings = repo_settings_from_context(ctx).review.merge_attention
    section = merge_attention_section_for_run(packet, ctx, settings=settings)
    if section is None or not settings.include_in_packet:
        return packet
    return packet.model_copy(update={"merge_attention": section})


__all__ = [
    "MergeAttentionInputs",
    "attach_merge_attention_to_packet",
    "compose_merge_attention",
    "inputs_from_context",
    "merge_attention_section_for_run",
]
