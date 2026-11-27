"""Render merge-attention blocks for review summary and run record."""

from __future__ import annotations

from mergecraft.merge_attention.types import AXIS_ORDER, MergeAttentionSection

_AXIS_LABELS: dict[str, str] = {
    "alignment": "Alignment",
    "impact": "Impact / blast radius",
    "verification": "Verification",
    "rollback_cost": "Rollback cost",
    "error_detection": "Error detection",
}


def merge_attention_summary_block(section: MergeAttentionSection | None) -> str:
    """Markdown block appended to the published review summary."""
    if section is None:
        return ""
    lines = [
        "### Merge-attention grade",
        "",
        f"**Overall:** `{section.overall}` — human-attention heuristic only; does not gate merge.",
        "",
        "| Axis | Grade | Verdict |",
        "| --- | --- | --- |",
    ]
    by_axis = {row.axis: row for row in section.axes}
    for axis in AXIS_ORDER:
        row = by_axis[axis]
        source = " (model)" if row.source == "model" else ""
        cell = f"{row.verdict}{source}"
        if row.verification_gaps:
            cell += " " + " ".join(f"⚠ {gap}" for gap in row.verification_gaps)
        lines.append(f"| {_AXIS_LABELS[axis]} | `{row.level}` | {cell} |")
    lines.append("")
    doc = section.rubric_doc if section.uncalibrated else "docs/merge-attention.md"
    lines.append(
        f"_Uncalibrated rubric — see `{doc}`. "
        "This grade never changes approval or check conclusions._"
    )
    return "\n".join(lines)


def merge_attention_record_lines(section: MergeAttentionSection | None) -> list[str]:
    """Bullet lines for the deterministic run record."""
    if section is None:
        return []
    lines = [
        f"- **Merge-attention:** `{section.overall}` (uncalibrated; does not gate merge)",
    ]
    by_axis = {row.axis: row for row in section.axes}
    for axis in AXIS_ORDER:
        row = by_axis[axis]
        label = _AXIS_LABELS[axis]
        suffix = " · model judgement" if row.source == "model" else ""
        lines.append(f"  - {label}: `{row.level}` — {row.verdict}{suffix}")
        for gap in row.verification_gaps:
            lines.append(f"    - Verification gap: {gap}")
    return lines


__all__ = ["merge_attention_record_lines", "merge_attention_summary_block"]
