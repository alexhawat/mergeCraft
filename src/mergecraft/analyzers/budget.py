"""Inline noise budget and mechanical-section placement (D14)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mergecraft.analyzers.finding import Finding
from mergecraft.review_taxonomy import (
    BODY_ONLY_EFFORT,
    BODY_ONLY_SEVERITY,
    FINDING_SEVERITIES,
    finding_fingerprint,
)

MECHANICAL_SECTION_HEADING = "### 🔧 Mechanical findings"

_DEFAULT_INLINE_BUDGET = 8
_SEVERITY_RANK = {name: index for index, name in enumerate(FINDING_SEVERITIES)}


@dataclass
class FindingPlacement:
    """Inline vs mechanical placement for normalized and agent findings."""

    inline: list[Any] = field(default_factory=list)
    mechanical: list[Finding] = field(default_factory=list)
    mechanical_section: str | None = None


def default_inline_budget() -> int:
    """Return the W0.2-measured inline cap (D14)."""
    return _DEFAULT_INLINE_BUDGET


def _is_body_only_finding(item: Finding | dict[str, Any]) -> bool:
    if isinstance(item, dict):
        return item.get("severity") == BODY_ONLY_SEVERITY or item.get("effort") == BODY_ONLY_EFFORT
    if item.start_line is None:
        return True
    return item.severity == BODY_ONLY_SEVERITY


def _source_rank(item: Finding | dict[str, Any]) -> int:
    source = item.source if isinstance(item, Finding) else item.get("source", "agent")
    if source == "agent":
        return 0
    if source == "ci":
        return 1
    return 2


def _severity_rank(item: Finding | dict[str, Any]) -> int:
    severity = item.severity if isinstance(item, Finding) else item.get("severity", "Minor")
    return _SEVERITY_RANK.get(str(severity), len(_SEVERITY_RANK))


def _sort_key(item: Finding | dict[str, Any]) -> tuple[int, int, str, int]:
    path = item.path if isinstance(item, Finding) else str(item.get("path", ""))
    if isinstance(item, Finding):
        line = item.start_line if item.start_line is not None else 0
    else:
        line = int(item.get("line", item.get("start_line", 0)))
    return (_source_rank(item), _severity_rank(item), path, line)


def _overflow_fingerprint(item: dict[str, Any], *, path: str, message: str) -> str:
    """Return a per-finding fingerprint for an overflowed agent finding.

    The agent rarely supplies its own ``fingerprint``. Falling back to a shared
    literal would give every overflow finding the same identity, so downstream
    dedup and the withdrawn-findings memory could not tell them apart. Derive
    one from the finding's own content instead, matching how inline agent
    comments are stamped (``path`` + comment body).
    """
    supplied = str(item.get("fingerprint", "") or "").strip()
    if supplied:
        return supplied
    body = str(item.get("body", "") or "") or message
    return finding_fingerprint(path=path, body=body)


def _render_mechanical_section(mechanical: list[Finding]) -> str | None:
    if not mechanical:
        return None
    by_tool: dict[str, list[Finding]] = {}
    for finding in mechanical:
        by_tool.setdefault(finding.tool, []).append(finding)

    lines = [MECHANICAL_SECTION_HEADING, ""]
    lines.append("| Tool | Findings |")
    lines.append("| --- | --- |")
    for tool in sorted(by_tool):
        count = len(by_tool[tool])
        lines.append(f"| {tool} | {count} |")
    lines.append("")
    for finding in mechanical:
        anchor = (
            finding.path if finding.start_line is None else f"{finding.path}:{finding.start_line}"
        )
        lines.append(f"- **{finding.tool}** `{finding.rule_id}` — {anchor}")
    return "\n".join(lines)


def place_findings(
    findings: list[Finding],
    *,
    inline_budget: int,
    agent_findings: list[dict[str, Any]] | None = None,
) -> FindingPlacement:
    """Place findings inline up to ``inline_budget``; overflow goes to the mechanical section."""
    candidates: list[Finding | dict[str, Any]] = list(agent_findings or [])
    candidates.extend(findings)

    inline_eligible = [item for item in candidates if not _is_body_only_finding(item)]
    inline_eligible.sort(key=_sort_key)

    inline = inline_eligible[:inline_budget]
    inline_ids = {id(item) for item in inline}

    mechanical: list[Finding] = []
    for item in candidates:
        if id(item) in inline_ids:
            continue
        if isinstance(item, Finding):
            mechanical.append(item)
        elif not _is_body_only_finding(item):
            message = str(item.get("message", item.get("body", "")))
            path = str(item.get("path", ""))
            mechanical.append(
                Finding(
                    tool=str(item.get("tool", "agent")),
                    rule_id=str(item.get("rule_id", "review")),
                    category=str(item.get("category", "Maintainability & Code Quality")),
                    severity=str(item.get("severity", "Minor")),
                    confidence=str(item.get("confidence", "likely")),
                    message=message,
                    path=path,
                    start_line=int(item.get("line", item.get("start_line", 1))),
                    end_line=int(item.get("end_line", item.get("line", item.get("start_line", 1)))),
                    fingerprint=_overflow_fingerprint(item, path=path, message=message),
                    evidence=[],
                    remediation=None,
                    autofix=None,
                    introduced_by_pr="unknown",
                    source="agent",
                    cluster_id=None,
                )
            )

    return FindingPlacement(
        inline=inline,
        mechanical=mechanical,
        mechanical_section=_render_mechanical_section(mechanical),
    )


__all__ = [
    "MECHANICAL_SECTION_HEADING",
    "FindingPlacement",
    "default_inline_budget",
    "place_findings",
]
