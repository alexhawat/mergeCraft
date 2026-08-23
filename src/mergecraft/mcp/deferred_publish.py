"""Deferred overflow publish helpers — extracted from review MCP (RC2, D1)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.analyzers.budget import FIX_ALL_DEFERRED_HEADING
from mergecraft.review_taxonomy import FINDING_MARKER_PREFIX, finding_fingerprint

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext


def deferred_findings_for_publish(ctx: ToolContext) -> list[dict[str, Any]]:
    """Return analyzer deferred overflow rows for publish stamping."""
    analyzer_run = ctx.tool_state.analyzer_run
    if analyzer_run is None:
        return []
    return list(analyzer_run.deferred_findings)


def section_present(body: str, heading: str) -> bool:
    return heading in body


def append_section(body: str, section: str | None, heading: str) -> str:
    if not section or section_present(body, heading):
        return body
    if body.rstrip():
        return f"{body.rstrip()}\n\n{section}"
    return section


def stamp_deferred_section(section: str, findings: list[dict[str, Any]]) -> str:
    markers: list[str] = []
    for row in findings:
        path = str(row.get("path", ""))
        message = str(row.get("body", row.get("message", "")))
        if not path or not message:
            continue
        marker = f"{FINDING_MARKER_PREFIX}{finding_fingerprint(path=path, body=message)} -->"
        if marker in section:
            continue
        markers.append(marker)
    if not markers:
        return section
    injection = "\n\n".join(markers) + "\n\n"
    if "</details>" in section:
        return section.replace("</details>", f"\n\n{injection}</details>", 1)
    return f"{section}\n\n{injection}"


def inject_deferred_fix_all_brief(body: str, findings: list[dict[str, Any]]) -> str:
    if not findings or FIX_ALL_DEFERRED_HEADING in body:
        return body
    if "### 🤖 Fix all findings" not in body:
        return body
    lines: list[str] = []
    for row in findings:
        path = str(row.get("path", ""))
        message = str(row.get("body", row.get("message", "")))
        if not path or not message:
            continue
        line = row.get("line", row.get("start_line"))
        anchor = f"{path}:{line}" if line is not None else path
        lines.append(f"- `{anchor}` — {message}")
    if not lines:
        return body
    block = f"{FIX_ALL_DEFERRED_HEADING}\n" + "\n".join(lines)
    fence_close = "````"
    idx = body.rfind(fence_close)
    if idx == -1:
        return f"{body}\n\n{block}"
    return f"{body[:idx].rstrip()}\n\n{block}\n\n{body[idx:]}"


def merge_analyzer_sections_into_review_body(ctx: ToolContext, body: str) -> str:
    analyzer_run = ctx.tool_state.analyzer_run
    if analyzer_run is None:
        return body
    from mergecraft.analyzers.budget import DEFERRED_SECTION_HEADING, MECHANICAL_SECTION_HEADING

    merged = body
    merged = append_section(merged, analyzer_run.mechanical_section, MECHANICAL_SECTION_HEADING)
    deferred_findings = deferred_findings_for_publish(ctx)
    deferred_section = analyzer_run.deferred_section
    if deferred_section:
        deferred_section = stamp_deferred_section(deferred_section, deferred_findings)
        merged = append_section(merged, deferred_section, DEFERRED_SECTION_HEADING)
    return inject_deferred_fix_all_brief(merged, deferred_findings)


__all__ = [
    "append_section",
    "deferred_findings_for_publish",
    "inject_deferred_fix_all_brief",
    "merge_analyzer_sections_into_review_body",
    "section_present",
    "stamp_deferred_section",
]
