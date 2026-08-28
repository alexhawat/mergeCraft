"""Inline noise budget and mechanical-section placement (D14)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from mergecraft.analyzers.finding import Finding, try_resolve_finding_short_ids

if TYPE_CHECKING:
    from mergecraft.mcp.tool_state import AnalyzerRunState
from mergecraft.review_taxonomy import (
    BODY_ONLY_EFFORT,
    BODY_ONLY_SEVERITY,
    FINDING_SEVERITIES,
    finding_fingerprint,
)

MECHANICAL_SECTION_HEADING = "### 🔧 Mechanical findings"
DEFERRED_SECTION_HEADING = "### 🗂 Deferred findings"
FIX_ALL_DEFERRED_HEADING = "## Deferred (non-blocking)"

_DEFAULT_INLINE_BUDGET = 8
_SEVERITY_RANK = {name: index for index, name in enumerate(FINDING_SEVERITIES)}


@dataclass
class FindingPlacement:
    """Inline vs mechanical/deferred placement for normalized and agent findings."""

    inline: list[Any] = field(default_factory=list)
    mechanical: list[Finding] = field(default_factory=list)
    mechanical_section: str | None = None
    deferred: list[Finding] = field(default_factory=list)
    deferred_section: str | None = None
    short_ids: dict[str, str] = field(default_factory=dict)


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


def _fingerprint_from_inline_item(item: Finding | dict[str, Any]) -> str | None:
    if isinstance(item, Finding):
        return item.fingerprint
    supplied = str(item.get("fingerprint", "") or "").strip()
    if supplied:
        return supplied
    path = str(item.get("path", ""))
    message = str(item.get("message", item.get("body", "")))
    return _overflow_fingerprint(item, path=path, message=message)


def _placement_fingerprints(
    inline: list[Any],
    mechanical: list[Finding],
    deferred: list[Finding],
) -> list[str]:
    fingerprints: list[str] = []
    for item in inline:
        fingerprint = _fingerprint_from_inline_item(item)
        if fingerprint:
            fingerprints.append(fingerprint)
    fingerprints.extend(row.fingerprint for row in mechanical)
    fingerprints.extend(row.fingerprint for row in deferred)
    return fingerprints


def _path_by_fingerprint(
    inline: list[Any],
    mechanical: list[Finding],
    deferred: list[Finding],
) -> dict[str, str]:
    paths: dict[str, str] = {}
    for item in inline:
        if isinstance(item, Finding):
            paths[item.fingerprint] = item.path
            continue
        if isinstance(item, dict):
            fingerprint = _fingerprint_from_inline_item(item)
            if fingerprint:
                paths[fingerprint] = str(item.get("path", ""))
    for finding in mechanical + deferred:
        paths[finding.fingerprint] = finding.path
    return paths


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


def _finding_anchor(finding: Finding) -> str:
    if finding.start_line is None:
        return finding.path
    return f"{finding.path}:{finding.start_line}"


def _render_mechanical_section(
    mechanical: list[Finding],
    *,
    short_ids: dict[str, str] | None = None,
) -> str | None:
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
        short_id = short_ids.get(finding.fingerprint) if short_ids else None
        prefix = f"**{short_id}** " if short_id else ""
        lines.append(
            f"- {prefix}**{finding.tool}** `{finding.rule_id}` — "
            f"{_finding_anchor(finding)} — {finding.message}"
        )
    return "\n".join(lines)


def render_deferred_section(
    deferred: list[Finding],
    *,
    short_ids: dict[str, str] | None = None,
) -> str | None:
    if not deferred:
        return None
    lines = [
        DEFERRED_SECTION_HEADING,
        "",
        "<details><summary>Non-blocking deferred findings</summary>",
        "",
    ]
    for finding in deferred:
        short_id = short_ids.get(finding.fingerprint) if short_ids else None
        prefix = f"**{short_id}** " if short_id else ""
        lines.append(
            f"{prefix}**{finding.severity}** `{_finding_anchor(finding)}` — {finding.message}"
        )
        lines.append("")
    lines.append("</details>")
    return "\n".join(lines)


def _coerce_line_number(item: dict[str, Any], *keys: str, default: int = 1) -> int:
    for key in keys:
        value = item.get(key)
        if value is not None:
            return int(value)
    return default


def agent_dict_to_finding(item: dict[str, Any], *, rule_id: str = "review") -> Finding:
    message = str(item.get("message", item.get("body", "")))
    path = str(item.get("path", ""))
    start_line = _coerce_line_number(item, "line", "start_line")
    end_line_raw = item.get("end_line")
    end_line = (
        int(end_line_raw)
        if end_line_raw is not None
        else _coerce_line_number(item, "line", "start_line", default=start_line)
    )
    return Finding(
        tool=str(item.get("tool", "agent")),
        rule_id=str(item.get("rule_id", rule_id)),
        category=str(item.get("category", "Maintainability & Code Quality")),
        severity=str(item.get("severity", "Minor")),
        confidence=str(item.get("confidence", "likely")),
        message=message,
        path=path,
        start_line=start_line,
        end_line=end_line,
        fingerprint=_overflow_fingerprint(item, path=path, message=message),
        evidence=[],
        remediation=None,
        autofix=None,
        introduced_by_pr="unknown",
        source="agent",
        cluster_id=None,
        collateral=[str(path) for path in item.get("collateral", []) if str(path).strip()],
    )


def _demote_unidentified_inline(
    inline: list[Any],
    *,
    short_ids: dict[str, str],
    mechanical: list[Finding],
    deferred: list[Finding],
) -> tuple[list[Any], list[Finding], list[Finding], bool]:
    """Move inline findings without short ids into mechanical/deferred lanes."""
    demoted_any = False
    kept_inline: list[Any] = []
    for item in inline:
        fingerprint = _fingerprint_from_inline_item(item)
        if fingerprint and fingerprint not in short_ids:
            demoted_any = True
            if isinstance(item, Finding):
                if item.source == "agent":
                    deferred.append(item)
                else:
                    mechanical.append(item)
            else:
                deferred.append(agent_dict_to_finding(item))
            continue
        kept_inline.append(item)
    return kept_inline, mechanical, deferred, demoted_any


def place_findings(
    findings: list[Finding],
    *,
    inline_budget: int,
    agent_findings: list[dict[str, Any]] | None = None,
) -> FindingPlacement:
    """Place findings inline up to ``inline_budget``; overflow routes by source."""
    candidates: list[Finding | dict[str, Any]] = list(agent_findings or [])
    candidates.extend(findings)

    inline_eligible = [item for item in candidates if not _is_body_only_finding(item)]
    inline_eligible.sort(key=_sort_key)

    inline = inline_eligible[:inline_budget]
    inline_ids = {id(item) for item in inline}

    mechanical: list[Finding] = []
    deferred: list[Finding] = []
    for item in candidates:
        if id(item) in inline_ids:
            continue
        if isinstance(item, Finding):
            if item.source == "agent":
                deferred.append(item)
            else:
                mechanical.append(item)
        elif not _is_body_only_finding(item):
            deferred.append(agent_dict_to_finding(item))

    short_ids = try_resolve_finding_short_ids(
        _placement_fingerprints(inline, mechanical, deferred),
        path_by_fingerprint=_path_by_fingerprint(inline, mechanical, deferred),
    )

    inline, mechanical, deferred, _demoted_due_to_short_id = _demote_unidentified_inline(
        inline,
        short_ids=short_ids,
        mechanical=mechanical,
        deferred=deferred,
    )

    return FindingPlacement(
        inline=inline,
        mechanical=mechanical,
        mechanical_section=_render_mechanical_section(
            mechanical,
            short_ids=short_ids,
        ),
        deferred=deferred,
        deferred_section=render_deferred_section(
            deferred,
            short_ids=short_ids,
        ),
        short_ids=short_ids,
    )


def finding_to_deferred_row(finding: Finding) -> dict[str, Any]:
    """Serialize a deferred overflow finding for ``AnalyzerRunState.deferred_findings``."""
    return {
        "path": finding.path,
        "line": finding.start_line,
        "body": finding.message,
        "severity": finding.severity,
        "fingerprint": finding.fingerprint,
    }


def render_deferred_section_from_rows(
    rows: list[dict[str, Any]],
    *,
    short_ids: dict[str, str] | None = None,
    all_fingerprints: list[str] | None = None,
) -> str | None:
    """Render the deferred HTML section from serialized analyzer-run rows."""
    findings = [agent_dict_to_finding(row) for row in rows if isinstance(row, dict)]
    if not findings:
        return None
    resolved_short_ids = short_ids
    if resolved_short_ids is None:
        fingerprint_batch = all_fingerprints or [row.fingerprint for row in findings]
        resolved_short_ids = try_resolve_finding_short_ids(
            fingerprint_batch,
            path_by_fingerprint={row.fingerprint: row.path for row in findings},
        )
    return render_deferred_section(findings, short_ids=resolved_short_ids)


def sync_deferred_section(analyzer_run: AnalyzerRunState) -> None:
    """Re-render ``deferred_section`` from ``deferred_findings`` rows."""
    all_fingerprints = [
        str(row.get("fingerprint", ""))
        for row in analyzer_run.findings
        if isinstance(row, dict) and row.get("fingerprint")
    ]
    analyzer_run.deferred_section = render_deferred_section_from_rows(
        analyzer_run.deferred_findings,
        all_fingerprints=all_fingerprints,
    )


__all__ = [
    "DEFERRED_SECTION_HEADING",
    "FIX_ALL_DEFERRED_HEADING",
    "MECHANICAL_SECTION_HEADING",
    "FindingPlacement",
    "agent_dict_to_finding",
    "default_inline_budget",
    "finding_to_deferred_row",
    "place_findings",
    "render_deferred_section",
    "render_deferred_section_from_rows",
    "sync_deferred_section",
]
