"""Exact cross-hunk move detection and symmetry validation (Go moves.go)."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from enum import IntEnum

from meat_python_plus.diffutil import (
    DiffLayout,
    DiffLineKind,
    SourceLine,
    analyze_diff,
    is_hunk_source,
    split_source_lines,
)
from meat_python_plus.editplan import DetectedMove, LineRange, PlannedReplacement, PlanState

MIN_MOVE_SUBSTANTIVE_ROWS = 3
MIN_MOVE_NONSPACE_BYTES = 48
MAX_MOVE_HINTS = 12


@dataclass
class MoveLineInfo:
    normalized: str
    indent: int
    substantive: bool


@dataclass
class MoveRun:
    start: int
    end: int
    hunk_id: int


@dataclass
class MoveOccurrence:
    index: int
    marker: str


@dataclass
class MoveAnchor:
    removed: int
    added: int


@dataclass(frozen=True)
class MoveAlignment:
    removed_run: int
    added_run: int
    delta: int


class MoveCompression(IntEnum):
    KEPT = 0
    REMOVED = 1
    FOLD_START = 2
    FOLD_MIDDLE = 3
    FOLD_END = 4


class MoveCompressionKind(IntEnum):
    KEPT = 0
    REMOVED = 1
    FOLDED = 2


def indentation_columns(indent: str) -> int:
    columns = 0
    for ch in indent:
        if ch == "\t":
            columns += 8 - columns % 8
        else:
            columns += 1
    return columns


def normalize_move_line(body: str) -> MoveLineInfo:
    body = body.rstrip(" \t")
    indent_text = leading_whitespace(body)
    normalized = body[len(indent_text) :]
    substantive = any(
        unicodedata.category(ch)[0] in ("L", "N") for ch in normalized
    )
    return MoveLineInfo(
        normalized=normalized,
        indent=indentation_columns(indent_text),
        substantive=substantive,
    )


def leading_whitespace(s: str) -> str:
    i = 0
    while i < len(s) and s[i] in " \t":
        i += 1
    return s[:i]


def move_rows_match(
    removed: MoveLineInfo, added: MoveLineInfo, indent_offset: int
) -> bool:
    if removed.normalized != added.normalized:
        return False
    if removed.normalized == "":
        return True
    return added.indent - removed.indent == indent_offset


def substantial_move(infos: list[MoveLineInfo], start: int, end: int) -> bool:
    substantive_rows = 0
    nonspace_bytes = 0
    for i in range(start, end + 1):
        if infos[i].substantive:
            substantive_rows += 1
        for ch in infos[i].normalized:
            if not ch.isspace():
                nonspace_bytes += len(ch.encode("utf-8"))
    return (
        substantive_rows >= MIN_MOVE_SUBSTANTIVE_ROWS
        and nonspace_bytes >= MIN_MOVE_NONSPACE_BYTES
    )


def ranges_overlap(a: LineRange, b: LineRange) -> bool:
    return a.start_line <= b.end_line and b.start_line <= a.end_line


def detect_exact_moves(
    lines: list[SourceLine], layout: DiffLayout
) -> list[DetectedMove]:
    if not lines or len(layout.kinds) != len(lines):
        return []

    infos: list[MoveLineInfo] = [MoveLineInfo("", 0, False) for _ in lines]
    occurrences: dict[str, list[MoveOccurrence]] = {}
    for i, line in enumerate(lines):
        if not is_hunk_source(layout.kinds[i]) or len(line.text) < 1:
            continue
        info = normalize_move_line(line.text[1:])
        infos[i] = info
        if info.substantive:
            occurrences.setdefault(info.normalized, []).append(
                MoveOccurrence(index=i, marker=line.text[0])
            )

    runs: list[MoveRun] = []
    run_at = [-1] * len(lines)
    i = 0
    while i < len(lines):
        if (
            layout.kinds[i] != DiffLineKind.HUNK_CHANGE
            or not lines[i].text
            or lines[i].text[0] not in "-+"
        ):
            i += 1
            continue
        marker = lines[i].text[0]
        hunk_id = layout.hunk_id[i]
        start = i
        while (
            i + 1 < len(lines)
            and layout.kinds[i + 1] == DiffLineKind.HUNK_CHANGE
            and lines[i + 1].text
            and lines[i + 1].text[0] == marker
            and layout.hunk_id[i + 1] == hunk_id
        ):
            i += 1
        run_index = len(runs)
        runs.append(MoveRun(start=start, end=i, hunk_id=hunk_id))
        for j in range(start, i + 1):
            run_at[j] = run_index
        i += 1

    anchors: list[MoveAnchor] = []
    for found in occurrences.values():
        if len(found) != 2:
            continue
        anchor = MoveAnchor(removed=-1, added=-1)
        for occurrence in found:
            if occurrence.marker == "-":
                anchor.removed = occurrence.index
            elif occurrence.marker == "+":
                anchor.added = occurrence.index
        if anchor.removed >= 0 and anchor.added >= 0:
            anchors.append(anchor)
    anchors.sort(key=lambda a: (a.removed, a.added))

    candidate_set: dict[tuple[int, int, int, int], DetectedMove] = {}
    last_segment: dict[MoveAlignment, DetectedMove] = {}
    for anchor in anchors:
        removed, added = anchor.removed, anchor.added
        if run_at[removed] < 0 or run_at[added] < 0:
            continue
        removed_run_index = run_at[removed]
        added_run_index = run_at[added]
        removed_run = runs[removed_run_index]
        added_run = runs[added_run_index]
        if removed_run.hunk_id < 0 or removed_run.hunk_id == added_run.hunk_id:
            continue
        alignment = MoveAlignment(
            removed_run=removed_run_index,
            added_run=added_run_index,
            delta=removed - added,
        )
        previous = last_segment.get(alignment)
        if previous is not None and (
            removed + 1 >= previous.removed.start_line
            and removed + 1 <= previous.removed.end_line
            and added + 1 >= previous.added.start_line
            and added + 1 <= previous.added.end_line
        ):
            continue

        indent_offset = infos[added].indent - infos[removed].indent
        removed_start, removed_end = removed, removed
        added_start, added_end = added, added
        while (
            removed_start > removed_run.start
            and added_start > added_run.start
            and move_rows_match(
                infos[removed_start - 1], infos[added_start - 1], indent_offset
            )
        ):
            removed_start -= 1
            added_start -= 1
        while (
            removed_end < removed_run.end
            and added_end < added_run.end
            and move_rows_match(
                infos[removed_end + 1], infos[added_end + 1], indent_offset
            )
        ):
            removed_end += 1
            added_end += 1

        candidate = DetectedMove(
            removed=LineRange(
                start_line=removed_start + 1, end_line=removed_end + 1
            ),
            added=LineRange(start_line=added_start + 1, end_line=added_end + 1),
        )
        last_segment[alignment] = candidate
        if substantial_move(infos, removed_start, removed_end):
            key = (
                candidate.removed.start_line,
                candidate.removed.end_line,
                candidate.added.start_line,
                candidate.added.end_line,
            )
            candidate_set[key] = candidate

    candidates = sorted(
        candidate_set.values(),
        key=lambda m: (
            m.removed.start_line,
            m.added.start_line,
            m.removed.end_line,
        ),
    )
    ambiguous = [False] * len(candidates)
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            if ranges_overlap(candidates[i].removed, candidates[j].removed) or ranges_overlap(
                candidates[i].added, candidates[j].added
            ):
                ambiguous[i] = True
                ambiguous[j] = True
    return [candidate for i, candidate in enumerate(candidates) if not ambiguous[i]]


def apply_mandatory_move_precedence(
    moves: list[DetectedMove], mandatory: list[bool]
) -> None:
    for move in moves:
        rows = move.removed.end_line - move.removed.start_line + 1
        for offset in range(rows):
            removed = move.removed.start_line + offset - 1
            added = move.added.start_line + offset - 1
            if (
                removed < 0
                or removed >= len(mandatory)
                or added < 0
                or added >= len(mandatory)
            ):
                continue
            if mandatory[removed] or mandatory[added]:
                mandatory[removed] = True
                mandatory[added] = True


def _compression_at(
    state: PlanState, mandatory: list[bool], line: int
) -> MoveCompression:
    index = line - 1
    if index >= 0 and index < len(mandatory) and mandatory[index]:
        return MoveCompression.REMOVED
    if not state.hidden[index]:
        return MoveCompression.KEPT
    fold_index = state.folded[index]
    if fold_index < 0:
        return MoveCompression.REMOVED
    fold = state.folds[fold_index]
    if line == fold.fold.start_line:
        return MoveCompression.FOLD_START
    if line == fold.fold.end_line:
        return MoveCompression.FOLD_END
    return MoveCompression.FOLD_MIDDLE


def _compression_kind(compression: MoveCompression) -> MoveCompressionKind:
    if compression == MoveCompression.KEPT:
        return MoveCompressionKind.KEPT
    if compression == MoveCompression.REMOVED:
        return MoveCompressionKind.REMOVED
    return MoveCompressionKind.FOLDED


def _format_line_range(r: LineRange) -> str:
    if r.start_line == r.end_line:
        return f"line {r.start_line}"
    return f"lines {r.start_line}-{r.end_line}"


def _line_range_verb(r: LineRange) -> str:
    return "is" if r.start_line == r.end_line else "are"


def validate_move_symmetry(
    moves: list[DetectedMove],
    state: PlanState,
    mandatory: list[bool],
) -> list[str]:
    problems: list[str] = []
    for move in moves:
        rows = move.removed.end_line - move.removed.start_line + 1
        offset = 0
        while offset < rows:
            removed_compression = _compression_at(
                state, mandatory, move.removed.start_line + offset
            )
            added_compression = _compression_at(
                state, mandatory, move.added.start_line + offset
            )
            if removed_compression == added_compression:
                offset += 1
                continue

            start = offset
            removed_kind = _compression_kind(removed_compression)
            added_kind = _compression_kind(added_compression)
            while offset + 1 < rows:
                next_removed = _compression_at(
                    state, mandatory, move.removed.start_line + offset + 1
                )
                next_added = _compression_at(
                    state, mandatory, move.added.start_line + offset + 1
                )
                if (
                    next_removed == next_added
                    or _compression_kind(next_removed) != removed_kind
                    or _compression_kind(next_added) != added_kind
                ):
                    break
                offset += 1
            end = offset

            removed_mismatch = LineRange(
                start_line=move.removed.start_line + start,
                end_line=move.removed.start_line + end,
            )
            added_mismatch = LineRange(
                start_line=move.added.start_line + start,
                end_line=move.added.start_line + end,
            )
            detail = (
                f"removed {_format_line_range(removed_mismatch)} "
                f"{_line_range_verb(removed_mismatch)} {removed_kind.name.lower()} "
                f"while added {_format_line_range(added_mismatch)} "
                f"{_line_range_verb(added_mismatch)} {added_kind.name.lower()}"
            )
            if (
                removed_kind == MoveCompressionKind.FOLDED
                and added_kind == MoveCompressionKind.FOLDED
            ):
                detail = (
                    f"removed {_format_line_range(removed_mismatch)} and added "
                    f"{_format_line_range(added_mismatch)} are folded with different "
                    "boundaries"
                )
            problems.append(
                "move symmetry: removed lines "
                f"{move.removed.start_line}-{move.removed.end_line} match added lines "
                f"{move.added.start_line}-{move.added.end_line} after indentation "
                f"normalization; {detail}. Keep, remove, or fold corresponding move "
                "rows identically, including fold boundaries"
            )
            offset += 1
    return problems


def apply_planned_replacements(
    body: str, edits: list[PlannedReplacement]
) -> str:
    for edit in reversed(edits):
        body = body[: edit.start] + edit.replacement.new + body[edit.end :]
    return body


def validate_move_replacement_symmetry(
    moves: list[DetectedMove],
    lines: list[SourceLine],
    state: PlanState,
    mandatory: list[bool],
    replacements: dict[int, list[PlannedReplacement]],
) -> list[str]:
    problems: list[str] = []
    for move in moves:
        rows = move.removed.end_line - move.removed.start_line + 1
        for offset in range(rows):
            removed_line = move.removed.start_line + offset
            added_line = move.added.start_line + offset
            if (
                _compression_at(state, mandatory, removed_line) != MoveCompression.KEPT
                or _compression_at(state, mandatory, added_line) != MoveCompression.KEPT
            ):
                continue
            removed_edits = replacements.get(removed_line, [])
            added_edits = replacements.get(added_line, [])
            if not removed_edits and not added_edits:
                continue

            removed_body = lines[removed_line - 1].text[1:]
            added_body = lines[added_line - 1].text[1:]
            if removed_edits:
                removed_body = apply_planned_replacements(removed_body, removed_edits)
            if added_edits:
                added_body = apply_planned_replacements(added_body, added_edits)
            if (
                normalize_move_line(removed_body).normalized
                == normalize_move_line(added_body).normalized
            ):
                continue

            problems.append(
                "move symmetry: removed lines "
                f"{move.removed.start_line}-{move.removed.end_line} match added lines "
                f"{move.added.start_line}-{move.added.end_line} after indentation "
                f"normalization; corresponding kept lines {removed_line} and "
                f"{added_line} have different model-authored local elisions. Apply "
                "equivalent replacements to both sides or keep both lines verbatim"
            )
    return problems


def detected_moves_in_diff(raw: str) -> list[DetectedMove]:
    lines = split_source_lines(raw)
    layout = analyze_diff(lines)
    if layout.problems:
        return []
    return detect_exact_moves(lines, layout)


def format_move_pairs(moves: list[DetectedMove], limit: int) -> str:
    if not moves or limit <= 0:
        return ""
    shown = min(len(moves), limit)
    parts = [
        (
            f"-{move.removed.start_line}..{move.removed.end_line} "
            f"↔ +{move.added.start_line}..{move.added.end_line}"
        )
        for move in moves[:shown]
    ]
    if shown < len(moves):
        parts.append(f"and {len(moves) - shown} more")
    return ", ".join(parts)


def surface_overflow_diff() -> str:
    """Synthetic diff with more than MAX_MOVE_HINTS non-overlapping moves (W8 surface)."""
    header = "diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n"
    parts = [header]

    def block_for(index: int) -> list[str]:
        return [
            f"first_unique_operation_{index}(source)",
            f"second_unique_operation_{index}(result)",
            f"third_unique_operation_{index}(result)",
            f"fourth_unique_operation_{index}(result)",
        ]

    def deleted_hunk(start: int, rows: list[str]) -> str:
        out = f"@@ -{start},4 +{start},0 @@\n"
        return out + "".join(f"-{row}\n" for row in rows)

    def added_hunk(start: int, rows: list[str]) -> str:
        out = f"@@ -{start},0 +{start},4 @@\n"
        return out + "".join(f"+ {row}\n" for row in rows)

    for i in range(MAX_MOVE_HINTS + 3):
        block = block_for(i)
        del_start = 1 + i * 19
        add_start = 100 + i * 19
        parts.append(deleted_hunk(del_start, block))
        parts.append(added_hunk(add_start, block))
    return "".join(parts)
