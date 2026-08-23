"""Production wiring for review-convergence helpers (RC6-RC12)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mergecraft.analyzers.budget import (
    agent_dict_to_finding,
    finding_to_deferred_row,
    place_findings,
)
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
        deferred_rows.append(finding_to_deferred_row(finding))
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
    collateral_map: Mapping[str, list[str]] | None = None,
    incremental_diff_text: str | None = None,
) -> str:
    """Apply incremental miss labelling and collateral append at publish time."""
    from mergecraft.mcp.tool_state import primary_repo_state
    from mergecraft.review_taxonomy import finding_fingerprint
    from mergecraft.types import INCREMENTAL_REVIEW_MODE

    prepared = body
    if ctx.tool_state.selected_mode == INCREMENTAL_REVIEW_MODE and line is not None:
        resolved_diff = incremental_diff_text
        if resolved_diff is None:
            primary = primary_repo_state(ctx.tool_state)
            incremental_path = primary.incremental_diff_path
            if incremental_path:
                from pathlib import Path

                resolved_diff = Path(incremental_path).read_text(encoding="utf-8")
        if resolved_diff:
            prepared = apply_first_pass_miss_label(
                prepared,
                path=path,
                line=line,
                incremental_diff_text=resolved_diff,
            )
    resolved_collateral = list(collateral) if collateral else None
    if not resolved_collateral:
        lookup_fp = fingerprint or finding_fingerprint(path=path, body=body)
        mapping = collateral_map if collateral_map is not None else collateral_by_fingerprint(ctx)
        resolved_collateral = mapping.get(lookup_fp)
    if resolved_collateral:
        prepared = append_collateral_to_inline_body(prepared, list(resolved_collateral))
    return prepared


def apply_recall_pass_post_process(
    ctx: ToolContext,
    recalled: Sequence[Mapping[str, object]],
    *,
    publish_sets: RecallPublishSets | None = None,
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
    resolved_sets = publish_sets or recall_publish_sets(ctx)
    merge_recall_findings_into_analyzer_run(
        analyzer_run,
        draft=resolved_sets.draft_rows,
        recalled=recalled,
    )
    from mergecraft.findings.ledger import record_deferred_from_analyzer_run

    record_deferred_from_analyzer_run(ctx.tool_state, analyzer_run)


def _withdrawn_fingerprints_for_recall(ctx: ToolContext) -> set[str]:
    """Fingerprints a verifier ``drop`` retired — live set plus learnings memory."""
    from mergecraft.mcp.verdict import withdrawn_fingerprints_for_state

    return withdrawn_fingerprints_for_state(ctx.tool_state, tmpdir=ctx.tmpdir)


@dataclass(frozen=True, slots=True)
class RecallPublishSets:
    """Draft inline rows and recall-candidate fingerprints from one publish scan."""

    draft_rows: list[Mapping[str, object]]
    recall_candidate_rows: list[dict[str, object]]
    recall_candidate_fingerprints: frozenset[str]


def recall_publish_sets(ctx: ToolContext) -> RecallPublishSets:
    """Collect draft inline rows and recall candidates in one fingerprint scan."""
    draft_rows: list[Mapping[str, object]] = []
    submission = ctx.tool_state.terminal_submission
    if submission is not None:
        draft_rows.extend(submission.findings)
    draft_rows.extend(row for row in ctx.tool_state.confirmed_findings if isinstance(row, dict))
    draft_fps = {
        str(row.get("fingerprint") or "")
        for row in draft_rows
        if isinstance(row, dict) and row.get("fingerprint")
    }
    withdrawn = _withdrawn_fingerprints_for_recall(ctx)
    recall_candidate_rows: list[dict[str, object]] = []
    recall_candidate_fingerprints: set[str] = set()
    for row in ctx.tool_state.agent_findings:
        if not isinstance(row, dict):
            continue
        fingerprint = str(row.get("fingerprint") or "")
        if fingerprint and fingerprint not in draft_fps and fingerprint not in withdrawn:
            recall_candidate_rows.append(row)
            recall_candidate_fingerprints.add(fingerprint)
    return RecallPublishSets(
        draft_rows=draft_rows,
        recall_candidate_rows=recall_candidate_rows,
        recall_candidate_fingerprints=frozenset(recall_candidate_fingerprints),
    )


def enforce_recall_deferred_lane_at_publish(
    ctx: ToolContext,
    *,
    publish_sets: RecallPublishSets | None = None,
) -> None:
    """Server-side D1 — recall output never publishes inline; merge into deferred."""
    resolved_sets = publish_sets or recall_publish_sets(ctx)
    recalled = resolved_sets.recall_candidate_rows
    if recalled:
        apply_recall_pass_post_process(ctx, recalled, publish_sets=resolved_sets)


def strip_recall_inline_comments(
    ctx: ToolContext,
    inline: list[dict[str, Any]],
    *,
    publish_sets: RecallPublishSets | None = None,
) -> list[dict[str, Any]]:
    """Remove inline comments that duplicate recall-candidate fingerprints."""
    recalled_fps = (
        publish_sets.recall_candidate_fingerprints
        if publish_sets is not None
        else recall_publish_sets(ctx).recall_candidate_fingerprints
    )
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
    "recall_publish_sets",
    "strip_recall_inline_comments",
]
