"""Merge findings from multiple reviewer-role bindings into one verdict (D6, D7, D15)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mergecraft.agents.ensemble import finding_key
from mergecraft.agents.gates import BLOCKING_SEVERITIES
from mergecraft.agents.registry import AgentRole, Registry
from mergecraft.analyzers.budget import default_inline_budget, place_findings

_SEVERITY_ALIASES: dict[str, str] = {
    "critical": "Critical",
    "major": "Major",
    "minor": "Minor",
    "trivial": "Trivial",
    "warning": "Minor",
    "error": "Major",
}


@dataclass(frozen=True, slots=True)
class ReviewerRun:
    """One reviewer dispatch outcome for terminal-submission accounting."""

    agent_id: str
    findings: list[dict[str, Any]]
    error: str | None = None


def reviewer_dispatch_batches(registry: Registry) -> tuple[tuple[str, ...], ...]:
    """Return reviewer ``agent_id`` batches per dispatch level (D15)."""
    levels = registry.resolve_role_levels(AgentRole.reviewer)
    return tuple(tuple(binding.agent_id for binding in level) for level in levels)


def merge_reviewer_findings(
    groups: list[tuple[str, list[dict[str, Any]]]],
    *,
    errors: dict[str, str] | None = None,
    inline_budget: int | None = None,
) -> list[dict[str, Any]]:
    """Merge reviewer findings with ``finding_key`` dedup and provenance (D6)."""
    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    provenance: dict[tuple[str, str, str], list[str]] = {}
    for agent_name, findings in groups:
        for row in findings:
            item = dict(row)
            key = finding_key(item)
            provenance.setdefault(key, []).append(agent_name)
            if key not in merged:
                merged[key] = item
                continue
            existing = merged[key]
            existing_sev = _severity_rank(existing.get("severity"))
            new_sev = _severity_rank(item.get("severity"))
            if new_sev > existing_sev:
                merged[key] = item

    ordered: list[dict[str, Any]] = []
    for key, row in merged.items():
        enriched = dict(row)
        agents = provenance.get(key, [])
        if agents:
            enriched["raised_by"] = agents[0] if len(agents) == 1 else agents
        ordered.append(enriched)

    budget = inline_budget if inline_budget is not None else default_inline_budget()
    placement = place_findings([], inline_budget=budget, agent_findings=ordered)
    inline_rows = [row for row in placement.inline if isinstance(row, dict)]
    if inline_rows:
        return inline_rows
    return [row for row in placement.inline]


def verdict_from_merged_findings(findings: list[dict[str, Any]]) -> str:
    """Map merged findings to one terminal verdict — strictest severity wins (D7)."""
    if not findings:
        return "approve"
    max_rank = max(_severity_rank(row.get("severity")) for row in findings)
    if max_rank >= _severity_rank("Major"):
        return "request_changes"
    return "comment"


def terminal_submission_count_from_review_runs(runs: list[ReviewerRun]) -> int:
    """Terminal verdict cardinality stays one regardless of reviewer count (D7)."""
    del runs
    return 1


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


def _normalized_severity(value: object) -> str:
    text = str(value or "Minor").strip()
    lowered = text.casefold()
    if lowered in _SEVERITY_ALIASES:
        return _SEVERITY_ALIASES[lowered]
    if text in BLOCKING_SEVERITIES or text in {"Minor", "Trivial"}:
        return text
    return "Minor"


def _severity_rank(value: object) -> int:
    from mergecraft.orchestrator.pipeline import _SEVERITY_ORDER

    normalized = _normalized_severity(value)
    return _SEVERITY_ORDER.get(normalized, 0)


__all__ = [
    "ReviewerRun",
    "format_reviewer_degradation_summary",
    "merge_reviewer_findings",
    "reviewer_dispatch_batches",
    "terminal_submission_count_from_review_runs",
    "verdict_from_merged_findings",
]
