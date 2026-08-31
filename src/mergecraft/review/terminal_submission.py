"""Terminal verdict preparation for multi-reviewer roster runs (D6/D7/D15)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.agents.ensemble import finding_key
from mergecraft.analyzers.budget import default_inline_budget, place_findings
from mergecraft.findings.severity import normalized_severity_rank

if TYPE_CHECKING:
    from mergecraft.agents.registry import Registry

# One orchestrator ``submit_review_verdict`` per run regardless of reviewer count (D7).
TERMINAL_SUBMISSION_COUNT = 1

# Server-stamped provenance for findings whose reviewer cannot be determined (D7).
UNKNOWN_RAISED_BY = "unknown"


@dataclass(frozen=True, slots=True)
class ReviewerRun:
    """One reviewer dispatch outcome for terminal-submission accounting."""

    agent_id: str
    findings: list[dict[str, Any]]
    error: str | None = None


def merge_reviewer_findings(
    groups: list[tuple[str, list[dict[str, Any]]]],
    *,
    errors: dict[str, str] | None = None,
    inline_budget: int | None = None,
    apply_placement: bool = True,
) -> list[dict[str, Any]]:
    """Merge reviewer findings with ``finding_key`` dedup and provenance (D6)."""
    if errors:
        for agent_name, reason in sorted(errors.items()):
            logger.debug("reviewer {} produced no findings: {}", agent_name, reason)

    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    provenance: dict[tuple[str, str, str], list[str]] = {}
    for agent_name, findings in groups:
        for row in findings:
            item = dict(row)
            if item.get("raised_by") is None:
                item["raised_by"] = agent_name
            key = finding_key(item)
            provenance.setdefault(key, []).append(agent_name)
            if key not in merged:
                merged[key] = item
                continue
            existing = merged[key]
            if normalized_severity_rank(item.get("severity")) > normalized_severity_rank(
                existing.get("severity")
            ):
                merged[key] = item

    ordered = sorted(
        merged.items(),
        key=lambda item: (
            -normalized_severity_rank(item[1].get("severity")),
            str(item[1].get("path", "")),
            str(item[1].get("line", "")),
            str(item[1].get("body", "")),
        ),
    )
    result: list[dict[str, Any]] = []
    for key, row in ordered:
        enriched = dict(row)
        agents = provenance.get(key, [])
        if agents:
            enriched["raised_by"] = agents[0] if len(agents) == 1 else agents
        result.append(enriched)

    if not apply_placement:
        return result

    budget = inline_budget if inline_budget is not None else default_inline_budget()
    placement = place_findings([], inline_budget=budget, agent_findings=result)
    return [row for row in placement.inline if isinstance(row, dict)]


def verdict_from_merged_findings(findings: list[dict[str, Any]]) -> str:
    """Map merged findings to one MCP terminal verdict — strictest severity wins (D7)."""
    if not findings:
        return "approve"
    max_rank = max(normalized_severity_rank(row.get("severity")) for row in findings)
    if max_rank >= normalized_severity_rank("Major"):
        return "request_changes"
    return "approve"


def terminal_submission_count_from_review_runs(runs: list[ReviewerRun]) -> int:
    """Terminal verdict cardinality stays one regardless of reviewer count (D7)."""
    _ = runs
    return TERMINAL_SUBMISSION_COUNT


def format_reviewer_degradation_summary(
    errors: dict[str, str] | None = None,
) -> str:
    """Summarize reviewers that produced no findings and why (D15)."""
    if not errors:
        return ""
    lines = ["Some reviewers did not produce findings:"]
    for agent_name in sorted(errors):
        reason = errors[agent_name]
        lines.append(f"- {agent_name}: {reason}")
    return "\n".join(lines)


def stamp_findings_with_reviewer(
    reviewer_id: str,
    findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Stamp ``raised_by`` from dispatch pairing before flattening (D6/D7)."""
    stamped: list[dict[str, Any]] = []
    for row in findings:
        item = dict(row)
        if item.get("raised_by") is None:
            item["raised_by"] = reviewer_id
        stamped.append(item)
    return stamped


def reviewer_groups_from_runs(
    runs: list[ReviewerRun],
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Build ``(reviewer_id, findings)`` groups from dispatch runs (D7)."""
    return [
        (run.agent_id, stamp_findings_with_reviewer(run.agent_id, run.findings)) for run in runs
    ]


def stamped_findings_for_terminal_submission(
    *,
    registry: Registry,
    terminal_findings: list[dict[str, Any]],
    dispatch_runs: list[ReviewerRun],
) -> list[dict[str, Any]]:
    """Stamp ``raised_by`` from dispatch pairing before terminal merge (D7)."""
    from mergecraft.agents.registry import AgentRole

    reviewers = registry.resolve_roles(AgentRole.reviewer)
    primary_id = reviewers[0].agent_id if reviewers else "reviewer"
    runs = list(dispatch_runs)
    runs.append(ReviewerRun(agent_id=primary_id, findings=terminal_findings))
    groups = reviewer_groups_from_runs(runs)
    return [row for _, rows in groups for row in rows]


def should_render_finding_provenance(findings: list[dict[str, Any]]) -> bool:
    """Return whether multi-reviewer provenance lines belong in the review body (D8)."""
    agents: set[str] = set()
    for row in findings:
        raised = row.get("raised_by")
        if isinstance(raised, str):
            agents.add(raised)
        elif isinstance(raised, list):
            agents.update(str(agent) for agent in raised)
    return len(agents) > 1


def format_finding_provenance_line(raised_by: str | list[str] | None) -> str | None:
    """Format one finding's ``raised_by`` for display in the review body (D8)."""
    if not raised_by:
        return None
    if isinstance(raised_by, list):
        agents = ", ".join(f"`{agent}`" for agent in raised_by)
        return f"_Raised by: {agents}_"
    return f"_Raised by: `{raised_by}`_"


def enrich_finding_body_with_provenance(
    body: str,
    raised_by: str | list[str] | None,
    *,
    show_provenance: bool,
) -> str:
    """Append a provenance line to a finding body when multi-reviewer display is active (D8)."""
    if not show_provenance:
        return body
    line = format_finding_provenance_line(raised_by)
    if not line or line in body:
        return body
    if not body.strip():
        return line
    return f"{body.rstrip()}\n\n{line}"


def append_degradation_to_summary(
    summary: str,
    errors: dict[str, str] | None = None,
) -> str:
    """Append a degradation block to *summary* when reviewers failed."""
    block = format_reviewer_degradation_summary(errors)
    if not block:
        return summary
    if not summary.strip():
        return block
    return f"{summary.rstrip()}\n\n{block}"


def prepare_terminal_submission(
    *,
    registry: Registry,
    findings: list[dict[str, Any]],
    verdict: str,
    errors: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Merge multi-reviewer findings and enforce strictest-wins verdict (D6/D7)."""
    from mergecraft.agents.registry import AgentRole

    reviewers = registry.resolve_roles(AgentRole.reviewer)
    if not reviewers:
        groups = [("reviewer", findings)]
    elif len(reviewers) == 1:
        groups = [(reviewers[0].agent_id, findings)]
    else:
        groups = _group_findings_by_reviewer(findings, reviewers)
    merged = merge_reviewer_findings(groups, errors=errors, apply_placement=False)
    if _every_reviewer_degraded(reviewers, errors) and not merged:
        return merged, "request_changes"
    merged_verdict = verdict_from_merged_findings(merged)
    enforced = _strictest_terminal_verdict(verdict, merged_verdict)
    return merged, enforced


def _every_reviewer_degraded(
    reviewers: tuple[Any, ...],
    errors: dict[str, str] | None,
) -> bool:
    if not reviewers or not errors:
        return False
    reviewer_ids = {binding.agent_id for binding in reviewers}
    return reviewer_ids <= set(errors)


def _group_findings_by_reviewer(
    findings: list[dict[str, Any]],
    reviewers: tuple[Any, ...],
) -> list[tuple[str, list[dict[str, Any]]]]:
    reviewer_ids = {binding.agent_id for binding in reviewers}
    by_agent: dict[str, list[dict[str, Any]]] = {agent_id: [] for agent_id in reviewer_ids}
    unassigned: list[dict[str, Any]] = []
    unknown_group: list[dict[str, Any]] = []
    for row in findings:
        if not isinstance(row, dict):
            continue
        raised = row.get("raised_by")
        agent: str | None = None
        if isinstance(raised, str):
            agent = raised
        elif isinstance(raised, list) and raised:
            agent = str(raised[0])
        if agent == UNKNOWN_RAISED_BY:
            unknown_group.append(row)
        elif agent is not None and agent in by_agent:
            by_agent[agent].append(row)
        elif agent is not None:
            unknown_group.append(dict(row, raised_by=UNKNOWN_RAISED_BY))
        else:
            unassigned.append(row)
    groups = [(agent_id, by_agent[agent_id]) for agent_id in sorted(by_agent) if by_agent[agent_id]]
    if unknown_group:
        groups.append((UNKNOWN_RAISED_BY, unknown_group))
    if unassigned:
        groups.append((UNKNOWN_RAISED_BY, unassigned))
    if not groups:
        groups = [(reviewers[0].agent_id, list(findings))]
    return groups


def _strictest_terminal_verdict(requested: str, from_findings: str) -> str:
    """Pick the strictest terminal verdict allowed by the MCP schema."""
    if from_findings == "request_changes":
        return "request_changes"
    if requested == "request_changes":
        return "request_changes"
    return "approve"


__all__ = [
    "TERMINAL_SUBMISSION_COUNT",
    "UNKNOWN_RAISED_BY",
    "ReviewerRun",
    "append_degradation_to_summary",
    "enrich_finding_body_with_provenance",
    "format_finding_provenance_line",
    "format_reviewer_degradation_summary",
    "merge_reviewer_findings",
    "prepare_terminal_submission",
    "reviewer_groups_from_runs",
    "should_render_finding_provenance",
    "stamp_findings_with_reviewer",
    "stamped_findings_for_terminal_submission",
    "terminal_submission_count_from_review_runs",
    "verdict_from_merged_findings",
]
