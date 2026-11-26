"""Diff → hunk units with bounded context and residual filtering (D2, J3.1/J3.6).

Function-level units are a named follow-up: the symbol index has no line spans.

Exports:
    JevError: Structured failure (``invalid_diff``).
    HunkUnit: One hunk-shaped review unit.
    segment_hunks: Parse a unified diff into hunk units.
    unit_id: Stable id for a unit.
    unit_cache_key: Cache key ``(content hash, pack id, pinned model)``.
    residual_units: Drop hunks an analyzer already flagged.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from mergecraft.diff import diff_lines, parse_diff
from mergecraft.jev.types import HunkUnit, JevError

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_DEFAULT_CONTEXT_LINES = 3
_BODY_PREFIXES = frozenset({" ", "+", "-", "\\"})


def segment_hunks(
    diff_text: str | None,
    *,
    context_lines: int = _DEFAULT_CONTEXT_LINES,
) -> list[HunkUnit]:
    """Split a unified diff into hunk units with bounded context.

    Each unit's path is the post-image path :func:`mergecraft.diff.parse_diff`
    names for its ``diff --git`` section (the removed path for a deletion), so a
    quoted or prefixed Git path reads the same here as everywhere else. Text
    before the first ``diff --git`` line is not a file section and yields no
    units.

    A line inside a hunk is content whatever it looks like: a removed
    ``-- comment`` renders as ``--- comment`` and an added ``++ x`` as
    ``+++ x``. ``--- ``/``+++ `` lines are read as headers only once the open
    hunk's declared old and new line counts are consumed, so they never rename
    a unit or drop an edit from its body.

    Args:
        diff_text: Unified diff text. ``None`` is ``invalid_diff``.
        context_lines: Maximum unchanged context lines kept around edits.

    Returns:
        list[HunkUnit]: One unit per hunk. Empty input yields no units.

    Raises:
        JevError: When ``diff_text`` is not a string.
    """
    if diff_text is None or not isinstance(diff_text, str):
        raise JevError("diff text must be a string", code="invalid_diff")
    if not diff_text.strip():
        return []

    bound = max(0, context_lines)
    units: list[HunkUnit] = []
    for section in parse_diff(diff_text).files:
        if section.path is None:
            continue
        units.extend(_section_units(section.path, section.text, bound))
    return units


def _section_units(path: str, section_text: str, bound: int) -> list[HunkUnit]:
    """Return the hunk units of one ``diff --git`` section."""
    units: list[HunkUnit] = []
    hunk_header: str | None = None
    hunk_start = 0
    hunk_new_count = 0
    old_remaining = 0
    new_remaining = 0
    hunk_body: list[str] = []

    def flush() -> None:
        if hunk_header is None:
            return
        trimmed = _bound_context(hunk_body, bound)
        content = "\n".join([hunk_header, *trimmed])
        end_line = hunk_start + max(hunk_new_count, 1) - 1
        actual_context = sum(1 for line in trimmed if line.startswith(" "))
        unit = HunkUnit(
            kind="hunk",
            path=path,
            content=content,
            context_lines=min(bound, actual_context),
            unit_id="",
            start_line=hunk_start,
            end_line=end_line,
        )
        units.append(unit.model_copy(update={"unit_id": unit_id(unit)}))

    # The first line is the ``diff --git`` header itself.
    for raw_line in diff_lines(section_text, strip_cr=True)[1:]:
        hunk_match = _HUNK_RE.match(raw_line)
        if hunk_match:
            flush()
            hunk_start = int(hunk_match.group(3))
            hunk_new_count = int(hunk_match.group(4) or "1")
            old_remaining = int(hunk_match.group(2) or "1")
            new_remaining = hunk_new_count
            hunk_header = raw_line
            hunk_body = []
            continue
        if hunk_header is None:
            # Extended header lines before the section's first hunk.
            continue
        in_body = old_remaining > 0 or new_remaining > 0
        if not in_body and raw_line.startswith(("--- ", "+++ ")):
            # A header pair after a completed hunk, not content.
            continue
        prefix = raw_line[:1]
        if prefix not in _BODY_PREFIXES:
            continue
        hunk_body.append(raw_line)
        if prefix in {" ", "-"}:
            old_remaining -= 1
        if prefix in {" ", "+"}:
            new_remaining -= 1
    flush()
    return units


def unit_id(unit: HunkUnit) -> str:
    """Return the stable id for ``unit``.

    Args:
        unit: Segmented hunk.

    Returns:
        str: Deterministic id over path, start line, and content.
    """
    if unit.unit_id:
        return unit.unit_id
    return _compute_unit_id(unit.path, unit.start_line, unit.content)


def unit_cache_key(unit: HunkUnit, *, pack_id: str, model: str) -> tuple[str, str, str]:
    """Cache key covering content hash, pack id, and pinned model (D2).

    Args:
        unit: Segmented hunk.
        pack_id: Versioned question-pack id.
        model: Pinned model id.

    Returns:
        tuple[str, str, str]: ``(content_hash, pack_id, model)``.
    """
    digest = hashlib.sha256(unit.content.encode("utf-8")).hexdigest()
    return (digest, pack_id, model)


def residual_units(
    units: list[HunkUnit],
    analyzer_findings: list[Any],
) -> list[HunkUnit]:
    """Return hunks no analyzer finding already covers (J3.6).

    Args:
        units: Segmented hunks.
        analyzer_findings: Analyzer findings as ``Finding`` or path/line mappings.

    Returns:
        list[HunkUnit]: Units that still need a Jev battery.
    """
    return [unit for unit in units if not _flagged_by_analyzer(unit, analyzer_findings)]


def _compute_unit_id(path: str, start_line: int, content: str) -> str:
    payload = f"{path}\n{start_line}\n{content}".encode()
    digest = hashlib.sha256(payload).hexdigest()[:16]
    return f"hunk:{path}:{digest}"


def _bound_context(body: list[str], context_lines: int) -> list[str]:
    if context_lines <= 0:
        return [line for line in body if not line.startswith(" ")]
    change_indexes = [idx for idx, line in enumerate(body) if line[:1] in {"+", "-"}]
    if not change_indexes:
        return body[:context_lines]
    first = change_indexes[0]
    last = change_indexes[-1]
    leading = [line for line in body[:first] if line.startswith(" ")][-context_lines:]
    trailing = [line for line in body[last + 1 :] if line.startswith(" ")][:context_lines]
    middle: list[str] = []
    pending_context: list[str] = []
    for line in body[first : last + 1]:
        if line.startswith(" "):
            pending_context.append(line)
            continue
        if pending_context:
            kept = pending_context[:context_lines]
            if len(pending_context) > context_lines:
                kept = pending_context[:context_lines] + pending_context[-context_lines:]
                if len(pending_context) <= 2 * context_lines:
                    kept = pending_context
            middle.extend(kept)
            pending_context = []
        middle.append(line)
    return [*leading, *middle, *trailing]


def _flagged_by_analyzer(unit: HunkUnit, analyzer_findings: list[Any]) -> bool:
    for finding in analyzer_findings:
        path, start_line, end_line = _finding_span(finding)
        if path != unit.path:
            continue
        if start_line is None:
            return True
        finding_end = end_line if end_line is not None else start_line
        if start_line <= unit.end_line and finding_end >= unit.start_line:
            return True
    return False


def _finding_span(finding: Any) -> tuple[str | None, int | None, int | None]:
    if isinstance(finding, dict):
        path = finding.get("path")
        start = finding.get("start_line")
        end = finding.get("end_line", start)
        return (
            str(path) if path is not None else None,
            start if isinstance(start, int) else None,
            end if isinstance(end, int) else None,
        )
    path = getattr(finding, "path", None)
    start = getattr(finding, "start_line", None)
    end = getattr(finding, "end_line", start)
    return (
        str(path) if path is not None else None,
        start if isinstance(start, int) else None,
        end if isinstance(end, int) else None,
    )


__all__ = [
    "HunkUnit",
    "JevError",
    "residual_units",
    "segment_hunks",
    "unit_cache_key",
    "unit_id",
]
