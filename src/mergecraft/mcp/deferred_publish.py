"""Deferred overflow publish helpers — extracted from review MCP (RC2, D1)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.analyzers.budget import FIX_ALL_DEFERRED_HEADING
from mergecraft.review_taxonomy import FINDING_MARKER_PREFIX, finding_fingerprint

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext
    from mergecraft.mcp.tool_state import AnalyzerRunState


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


def _analyzer_inline_fingerprints(analyzer_run: AnalyzerRunState) -> set[str]:
    fingerprints: set[str] = set()
    for row in analyzer_run.inline:
        if not isinstance(row, dict):
            continue
        finding = row.get("finding")
        if isinstance(finding, dict):
            fp = str(finding.get("fingerprint", "")).strip()
            if fp:
                fingerprints.add(fp)
    return fingerprints


def refresh_analyzer_sections_for_publish(
    analyzer_run: AnalyzerRunState,
    *,
    short_ids: dict[str, str],
    inline_comment_fingerprints: set[str] | None = None,
) -> None:
    """Re-render body-appended analyzer sections with publish-time short ids."""
    from mergecraft.analyzers.budget import (
        _render_mechanical_section,
        render_deferred_section_from_rows,
    )
    from mergecraft.analyzers.finding import Finding, FindingValidationError

    exclude_fps = _analyzer_inline_fingerprints(analyzer_run)
    if inline_comment_fingerprints:
        exclude_fps |= inline_comment_fingerprints
    mechanical: list[Finding] = []
    for row in analyzer_run.findings:
        if not isinstance(row, dict):
            continue
        try:
            finding = Finding.model_validate(row)
        except (FindingValidationError, ValueError):
            continue
        if finding.fingerprint not in exclude_fps:
            mechanical.append(finding)

    if analyzer_run.mechanical_section is not None:
        analyzer_run.mechanical_section = _render_mechanical_section(
            mechanical,
            short_ids=short_ids,
        )
    if analyzer_run.deferred_section is not None:
        analyzer_run.deferred_section = render_deferred_section_from_rows(
            analyzer_run.deferred_findings,
            short_ids=short_ids,
        )


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
    "refresh_analyzer_sections_for_publish",
    "section_present",
    "stamp_deferred_section",
]
