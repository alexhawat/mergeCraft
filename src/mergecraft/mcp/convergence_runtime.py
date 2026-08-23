"""Production wiring for review-convergence helpers (RC6-RC12)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.analyzers.budget import agent_dict_to_finding, place_findings
from mergecraft.modes._incremental_miss import apply_first_pass_miss_label
from mergecraft.modes._pr_summary_format import append_collateral_to_inline_body

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from mergecraft.analyzers.finding import Finding
    from mergecraft.mcp.context import ToolContext
    from mergecraft.mcp.tool_state import AnalyzerRunState


def _recall_row_to_finding(row: Mapping[str, object]) -> Finding:
    item = dict(row)
    item.setdefault("category", "Functional Correctness")
    item.setdefault("severity", "Major")
    return agent_dict_to_finding(item, rule_id="agent:recall")


def merge_recall_findings_into_analyzer_run(
    analyzer_run: AnalyzerRunState,
    *,
    draft: Sequence[Mapping[str, object]],
    recalled: Sequence[Mapping[str, object]],
) -> None:
    """Post-process recall output — novel findings always land in deferred (D1)."""
    if not recalled:
        return
    from mergecraft.agents.recall import filter_novel_recall_findings

    draft_findings = [_recall_row_to_finding(row) for row in draft]
    recalled_findings = [_recall_row_to_finding(row) for row in recalled]
    deferred_findings = [_recall_row_to_finding(row) for row in analyzer_run.deferred_findings]
    novel = filter_novel_recall_findings(
        [*draft_findings, *deferred_findings],
        recalled_findings,
    )
    if not novel:
        return
    placement = place_findings(novel, inline_budget=0)
    deferred_rows = list(analyzer_run.deferred_findings)
    for finding in placement.deferred:
        deferred_rows.append(
            {
                "path": finding.path,
                "line": finding.start_line,
                "body": finding.message,
                "severity": finding.severity,
                "fingerprint": finding.fingerprint,
            }
        )
    analyzer_run.deferred_findings = deferred_rows
    from mergecraft.analyzers.budget import sync_deferred_section

    sync_deferred_section(analyzer_run)


def collateral_by_fingerprint(ctx: ToolContext) -> dict[str, list[str]]:
    """Map analyzer finding fingerprints to optional collateral path lists (RC11)."""
    rows = ctx.tool_state.iter_finding_rows()
    mapping: dict[str, list[str]] = {}
    for row in rows:
        fingerprint = str(row.get("fingerprint") or "").strip()
        collateral = row.get("collateral")
        if not fingerprint or not isinstance(collateral, list):
            continue
        paths = [str(path).strip() for path in collateral if str(path).strip()]
        if paths:
            mapping[fingerprint] = paths
    return mapping


def prepare_inline_comment_for_publish(
    ctx: ToolContext,
    *,
    path: str,
    line: int | None,
    body: str,
    collateral: Sequence[str] | None = None,
    fingerprint: str | None = None,
) -> str:
    """Apply incremental miss labelling and collateral append at publish time."""
    from mergecraft.mcp.tool_state import primary_repo_state
    from mergecraft.review_taxonomy import finding_fingerprint
    from mergecraft.types import INCREMENTAL_REVIEW_MODE

    prepared = body
    if ctx.tool_state.selected_mode == INCREMENTAL_REVIEW_MODE and line is not None:
        primary = primary_repo_state(ctx.tool_state)
        incremental_path = primary.incremental_diff_path
        if incremental_path:
            from pathlib import Path

            incremental_diff = Path(incremental_path).read_text(encoding="utf-8")
            prepared = apply_first_pass_miss_label(
                prepared,
                path=path,
                line=line,
                incremental_diff_text=incremental_diff,
            )
    resolved_collateral = list(collateral) if collateral else None
    if not resolved_collateral:
        lookup_fp = fingerprint or finding_fingerprint(path=path, body=body)
        resolved_collateral = collateral_by_fingerprint(ctx).get(lookup_fp)
    if resolved_collateral:
        prepared = append_collateral_to_inline_body(prepared, list(resolved_collateral))
    return prepared


def apply_recall_pass_post_process(
    ctx: ToolContext, recalled: Sequence[Mapping[str, object]]
) -> None:
    """Merge recall subagent output into the analyzer deferred lane when enabled."""
    from pathlib import Path

    from mergecraft.config.settings import load_repo_settings
    from mergecraft.mcp.tool_state import primary_repo_state

    repo_root = Path(primary_repo_state(ctx.tool_state).dir or Path.cwd())
    settings = load_repo_settings(root=repo_root, load_learnings_files=False)
    if not settings.review.recall_pass or not recalled:
        return
    analyzer_run = ctx.tool_state.analyzer_run
    if analyzer_run is None:
        from mergecraft.mcp.tool_state import AnalyzerRunState

        analyzer_run = AnalyzerRunState(ran=True)
        ctx.tool_state.analyzer_run = analyzer_run
    merge_recall_findings_into_analyzer_run(
        analyzer_run,
        draft=_draft_rows_for_recall(ctx),
        recalled=recalled,
    )
    from mergecraft.findings.ledger import record_deferred_from_analyzer_run

    record_deferred_from_analyzer_run(ctx.tool_state, analyzer_run)


def _draft_rows_for_recall(ctx: ToolContext) -> list[Mapping[str, object]]:
    """Collect draft findings the orchestrator already plans to publish inline."""
    rows: list[Mapping[str, object]] = []
    submission = ctx.tool_state.terminal_submission
    if submission is not None:
        rows.extend(submission.findings)
    rows.extend(row for row in ctx.tool_state.confirmed_findings if isinstance(row, dict))
    return rows


def _withdrawn_fingerprints_for_recall(ctx: ToolContext) -> set[str]:
    """Fingerprints a verifier ``drop`` retired — live set plus learnings memory."""
    from mergecraft.mcp.verdict import withdrawn_fingerprints_for_state

    return withdrawn_fingerprints_for_state(ctx.tool_state, tmpdir=ctx.tmpdir)


def _recall_candidate_rows(ctx: ToolContext) -> list[dict[str, object]]:
    """Return agent findings absent from the inline draft — recall pass candidates."""
    draft_fps = {
        str(row.get("fingerprint") or "")
        for row in _draft_rows_for_recall(ctx)
        if isinstance(row, dict) and row.get("fingerprint")
    }
    withdrawn = _withdrawn_fingerprints_for_recall(ctx)
    recalled: list[dict[str, object]] = []
    for row in ctx.tool_state.agent_findings:
        if not isinstance(row, dict):
            continue
        fingerprint = str(row.get("fingerprint") or "")
        if fingerprint and fingerprint not in draft_fps and fingerprint not in withdrawn:
            recalled.append(row)
    return recalled


def enforce_recall_deferred_lane_at_publish(ctx: ToolContext) -> None:
    """Server-side D1 — recall output never publishes inline; merge into deferred."""
    recalled = _recall_candidate_rows(ctx)
    if recalled:
        apply_recall_pass_post_process(ctx, recalled)


def strip_recall_inline_comments(
    ctx: ToolContext,
    inline: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Remove inline comments that duplicate recall-candidate fingerprints."""
    recalled_fps = {
        str(row.get("fingerprint") or "")
        for row in _recall_candidate_rows(ctx)
        if row.get("fingerprint")
    }
    if not recalled_fps:
        return inline
    from mergecraft.review_resolution import finding_fingerprints_in

    kept: list[dict[str, Any]] = []
    for item in inline:
        body_fps = finding_fingerprints_in(str(item.get("body") or ""))
        if body_fps & recalled_fps:
            continue
        kept.append(item)
    return kept


__all__ = [
    "apply_recall_pass_post_process",
    "collateral_by_fingerprint",
    "enforce_recall_deferred_lane_at_publish",
    "merge_recall_findings_into_analyzer_run",
    "prepare_inline_comment_for_publish",
    "strip_recall_inline_comments",
]
