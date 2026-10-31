"""Diff line-range coverage — which changed lines a run actually read.

The trajectory auditor used to answer a file-level question: *was this changed
file read at all?* That is too coarse for a large PR — a run that read one line
of a 900-line file satisfied it — and it cannot say *what* is left. This module
is the line-range layer the auditor and the pre-submit nudge share.

The unit of scope is the diff, not the working tree. Added lines (the RIGHT
side of a hunk) are what a review must account for; deletions are context for
them. Coverage is therefore reported in post-image coordinates, so a nudge
reads `path:start-end` the same way a review comment does.

Two inputs are deliberately separate:

* :func:`parse_diff_toc` — a pure parse of a unified diff into per-file added
  line ranges. Each added line keeps its diff-file line number, so a read of
  the diff path itself can be mapped back exactly.
* :func:`compute_diff_coverage` — the ranges a run's observed reads covered.
  Reads may name the diff file itself (a `cat`/`sed`/`head` call) or a source
  path in the checkout (a native/read-tool record). A read with no line range
  covers that file's added lines; that is the honest reading of "the file was
  read" and matches the old file-level semantics at their best case.

Absent evidence stays absent: with no observed reads, coverage is *unknown*,
not zero, and callers must not nudge. :attr:`DiffCoverageBreakdown.observed`
carries that distinction, mirroring ``TrajectoryRecord.read_coverage``.

Module: mergecraft.evidence.diff_coverage
Depends: mergecraft.evidence.trajectory (ToolCallRecord)

Exports:
    DiffTocEntry — One changed file and its added-line ranges.
    LineRange — Inclusive 1-based line range.
    FileDiffCoverage — Covered/unread ranges for one file.
    DiffCoverageBreakdown — Whole-diff coverage with unread ranges.
    parse_diff_toc — Parse a unified diff into TOC entries.
    compute_diff_coverage — Map observed reads onto the TOC.
    coverage_nudge — One-time actionable nudge text naming unread ranges.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from mergecraft.analyzers.scope import (
    DIFF_HEADER_FILE,
    DIFF_HEADER_RENAME,
    classify_diff_header_line,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from mergecraft.evidence.trajectory import ToolCallRecord

_HUNK_RE: Final[re.Pattern[str]] = re.compile(
    r"^@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,(?P<count>\d+))? @@"
)
_SED_RANGE_RE: Final[re.Pattern[str]] = re.compile(r"^(?P<start>\d+),(?P<end>\d+)p$")
_SED_SINGLE_RE: Final[re.Pattern[str]] = re.compile(r"^(?P<line>\d+)p$")
_HEAD_N_RE: Final[re.Pattern[str]] = re.compile(r"^(?P<count>\d+)$")
# Generated artifacts are in the diff but not worth a human read. The nudge
# names them, as pullfrog does, so the agent can decide to skip deliberately
# rather than silently.
_GENERATED_MARKERS: Final[tuple[str, ...]] = (
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "Cargo.lock",
    "poetry.lock",
    "uv.lock",
    "go.sum",
    "composer.lock",
)
_GENERATED_SUFFIXES: Final[tuple[str, ...]] = (
    ".pb.go",
    ".generated.ts",
    ".generated.py",
    ".min.js",
    ".min.css",
)
_GENERATED_DIRS: Final[tuple[str, ...]] = ("__snapshots__/", "drizzle/meta/", "migrations/")


@dataclass(frozen=True, slots=True)
class LineRange:
    """An inclusive 1-based line range."""

    start: int
    end: int

    def __post_init__(self) -> None:
        """Reject an inverted or non-positive range at construction."""
        if self.start < 1 or self.end < self.start:
            msg = f"invalid line range {self.start}-{self.end}"
            raise ValueError(msg)

    @property
    def line_count(self) -> int:
        """Return the number of lines the range covers."""
        return self.end - self.start + 1

    def overlaps(self, other: LineRange) -> bool:
        """Return whether the two inclusive ranges share at least one line."""
        return self.start <= other.end and other.start <= self.end

    def intersect(self, other: LineRange) -> LineRange | None:
        """Return the shared sub-range, or ``None`` when they do not overlap."""
        start = max(self.start, other.start)
        end = min(self.end, other.end)
        return LineRange(start, end) if start <= end else None

    def __str__(self) -> str:
        """Render the canonical ``start-end`` form used in nudges."""
        return f"{self.start}-{self.end}"


@dataclass(frozen=True, slots=True)
class DiffTocEntry:
    """One file in a unified diff and the added lines a review must account for.

    ``diff_start`` / ``diff_end`` are 1-based line numbers *in the diff file*
    for this file's section. ``line_map`` pairs each added post-image line with
    the diff-file line that carries it, which is what makes a read of the diff
    path itself mappable without approximating.
    """

    path: str
    ranges: tuple[LineRange, ...]
    line_map: tuple[tuple[int, int], ...]
    """``(diff_line, post_image_line)`` for every added line, in diff order."""
    diff_start: int
    diff_end: int
    deletion_only: bool = False
    """True for a deletion-only / binary / mode-only section (no added lines)."""

    @property
    def line_count(self) -> int:
        """Return the number of added lines across every range."""
        return sum(item.line_count for item in self.ranges)


@dataclass(frozen=True, slots=True)
class FileDiffCoverage:
    """Covered and unread added-line ranges for one changed file."""

    path: str
    ranges: tuple[LineRange, ...]
    covered: tuple[LineRange, ...]
    unread: tuple[LineRange, ...]
    deletion_only: bool = False
    read: bool = False

    @property
    def line_count(self) -> int:
        """Return the file's added-line count."""
        return sum(item.line_count for item in self.ranges)

    @property
    def covered_count(self) -> int:
        """Return how many added lines were read."""
        return sum(item.line_count for item in self.covered)

    @property
    def unread_count(self) -> int:
        """Return how many added lines were not read."""
        return sum(item.line_count for item in self.unread)


@dataclass(frozen=True, slots=True)
class DiffCoverageBreakdown:
    """Whole-diff line-range coverage for one run."""

    files: tuple[FileDiffCoverage, ...]
    observed: bool
    """True when at least one read in scope was observed.

    ``False`` means coverage is *unknown*; callers must not nudge or report an
    unread finding from it.
    """

    @property
    def total_lines(self) -> int:
        """Return the number of added lines in scope."""
        return sum(item.line_count for item in self.files)

    @property
    def covered_lines(self) -> int:
        """Return the number of added lines covered by an observed read."""
        return sum(item.covered_count for item in self.files)

    @property
    def unread_lines(self) -> int:
        """Return the number of added lines not covered by an observed read."""
        return sum(item.unread_count for item in self.files)

    @property
    def coverage_percent(self) -> float:
        """Return covered / total as a percentage (100.0 for an empty scope)."""
        total = self.total_lines
        if total == 0:
            return 100.0
        return round(self.covered_lines / total * 100, 2)

    def unread_files(self) -> tuple[FileDiffCoverage, ...]:
        """Return files with unread added lines or an unread deletion."""
        return tuple(
            item for item in self.files if item.unread or (item.deletion_only and not item.read)
        )


def _merge_ranges(ranges: Iterable[LineRange]) -> tuple[LineRange, ...]:
    """Sort and collapse overlapping or adjacent ranges."""
    ordered = sorted(ranges, key=lambda item: (item.start, item.end))
    merged: list[LineRange] = []
    for item in ordered:
        if not merged:
            merged.append(item)
            continue
        last = merged[-1]
        if item.start <= last.end + 1:
            merged[-1] = LineRange(last.start, max(last.end, item.end))
        else:
            merged.append(item)
    return tuple(merged)


def _subtract(ranges: Sequence[LineRange], covered: Sequence[LineRange]) -> tuple[LineRange, ...]:
    """Return the parts of ``ranges`` not covered by ``covered``."""
    remaining = list(ranges)
    for cover in covered:
        next_remaining: list[LineRange] = []
        for item in remaining:
            if not item.overlaps(cover):
                next_remaining.append(item)
                continue
            if item.start < cover.start:
                next_remaining.append(LineRange(item.start, cover.start - 1))
            if item.end > cover.end:
                next_remaining.append(LineRange(cover.end + 1, item.end))
        remaining = next_remaining
    return tuple(remaining)


def _parse_file_section(
    lines: Sequence[str], *, start_line: int, end_line: int
) -> tuple[tuple[LineRange, ...], tuple[tuple[int, int], ...]]:
    """Collect added ranges and their diff-file lines from one file section."""
    added_lines: list[tuple[int, int]] = []
    new_line = 0
    in_hunk = False
    for offset, raw in enumerate(lines[start_line - 1 : end_line], start=start_line):
        hunk = _HUNK_RE.match(raw)
        if hunk is not None:
            in_hunk = True
            new_line = int(hunk.group("start"))
            continue
        if not in_hunk and raw.startswith(("+++", "---")):
            continue
        if raw.startswith("\\"):
            # "\ No newline at end of file" is metadata, not a content line.
            continue
        if raw.startswith("+"):
            added_lines.append((offset, new_line))
            new_line += 1
        elif raw.startswith("-"):
            continue
        else:
            new_line += 1
    ranges: list[LineRange] = []
    for _diff_line, source_line in added_lines:
        if ranges and source_line == ranges[-1].end + 1:
            ranges[-1] = LineRange(ranges[-1].start, source_line)
        else:
            ranges.append(LineRange(source_line, source_line))
    return tuple(ranges), tuple(added_lines)


def parse_diff_toc(diff_text: str) -> tuple[DiffTocEntry, ...]:
    """Parse a unified diff into per-file added-line ranges.

    A file with no added lines (deletion-only, binary, mode change) is omitted:
    there is nothing on the RIGHT side for a review to account for.
    """
    lines = diff_text.splitlines()
    # A ``None`` path is a section whose ``diff --git`` header could not be
    # decoded: it still bounds the previous file's section, but its hunks are
    # dropped rather than attributed to a neighbour.
    section_starts: list[tuple[str | None, int]] = []
    current_path: str | None = None
    current_start = 0
    in_section = False
    seen_hunk = False
    for index, raw in enumerate(lines, start=1):
        if raw.startswith("@@"):
            seen_hunk = True
            continue
        # Header paths decode exactly as the analyzer scope does, including
        # Git's C-quoted form for a space or non-ASCII byte in the path.
        header = classify_diff_header_line(raw, in_hunk=seen_hunk)
        if header is None:
            continue
        kind, path = header
        if kind == DIFF_HEADER_FILE:
            if in_section:
                section_starts.append((current_path, current_start))
            current_path = path
            current_start = index
            in_section = True
            seen_hunk = False
            continue
        if path is None:
            # A ``+++ /dev/null`` deletion-only file (or an undecodable path):
            # keep the section boundary so the previous file's section does
            # not swallow its hunks. It produces no added ranges.
            continue
        if kind == DIFF_HEADER_RENAME and in_section:
            current_path = path
            continue
        if not in_section:
            current_path = path
            current_start = index
            in_section = True
            seen_hunk = False
        elif path != current_path:
            section_starts.append((current_path, current_start))
            current_path = path
            current_start = index
            seen_hunk = False
    if in_section:
        section_starts.append((current_path, current_start))

    entries: list[DiffTocEntry] = []
    for position, (section_path, start) in enumerate(section_starts):
        if section_path is None:
            continue
        path = section_path
        end = (
            section_starts[position + 1][1] - 1
            if position + 1 < len(section_starts)
            else len(lines)
        )
        ranges, line_map = _parse_file_section(lines, start_line=start, end_line=end)
        entries.append(
            DiffTocEntry(
                path=path,
                ranges=ranges,
                line_map=line_map,
                diff_start=start,
                diff_end=end,
                deletion_only=not ranges,
            )
        )
    return tuple(entries)


def command_line_span(command: str | None) -> tuple[int, int] | None:
    """Read a line span from the simple read commands a reviewer uses.

    Supports ``sed -n 'A,Bp'``, ``sed -n 'Ap'``, ``head -n N`` and
    ``head -N``. Returns ``None`` when no explicit span was named (whole-file
    semantics), and ``(0, 0)`` when a span was named but is invalid (an
    inverted ``sed`` range). The sentinel is distinct from ``None`` so callers
    do not credit an invalid range as a whole-file read.
    """
    if not command:
        return None
    try:
        argv = shlex.split(command)
    except ValueError:
        return None
    if not argv:
        return None
    tool = argv[0].rsplit("/", maxsplit=1)[-1]
    if tool == "sed":
        for index, token in enumerate(argv):
            if token in {"-n", "--quiet", "--silent"}:
                continue
            if token in {"-e", "--expression"} and index + 1 < len(argv):
                expression = argv[index + 1]
            elif index > 0 and argv[index - 1] == "-n":
                expression = token
            else:
                continue
            match = _SED_RANGE_RE.match(expression) or _SED_SINGLE_RE.match(expression)
            if match is not None:
                start = int(match.group("start"))
                end = int(match.groupdict().get("end") or start)
                return (start, end) if end >= start else (0, 0)
        return None
    if tool == "head":
        for index, token in enumerate(argv[1:], start=1):
            if token in {"-n", "--lines"} and index + 1 < len(argv):
                match = _HEAD_N_RE.match(argv[index + 1])
                if match is None:
                    return None
                count = int(match.group("count"))
                return (1, count) if count > 0 else (0, 0)
            if token.startswith("-n") and len(token) > 2:
                match = _HEAD_N_RE.match(token[2:])
                if match is None:
                    return None
                count = int(match.group("count"))
                return (1, count) if count > 0 else (0, 0)
            if token.startswith("-") and token[1:].isdigit():
                count = int(token[1:])
                return (1, count) if count > 0 else (0, 0)
        return None
    return None


def _read_paths(command: str | None) -> list[str]:
    """Return the path operands of one simple read command."""
    if not command:
        return []
    try:
        argv = shlex.split(command)
    except ValueError:
        return []
    if not argv:
        return []
    tool = argv[0].rsplit("/", maxsplit=1)[-1]
    if tool not in {"cat", "bat", "less", "more", "head", "tail", "sed", "awk", "diff"}:
        return []
    operands: list[str] = []
    skip_next = False
    consumed_pattern = False
    value_options = (
        {"-e", "--expression", "-f", "--file"}
        if tool in {"sed", "awk"}
        else {"-n", "--lines", "-c", "--bytes"}
    )
    for token in argv[1:]:
        if skip_next:
            skip_next = False
            continue
        if token in value_options:
            skip_next = True
            consumed_pattern = consumed_pattern or tool in {"sed", "awk"}
            continue
        if token.startswith("-"):
            continue
        operands.append(token)
    if tool in {"sed", "awk"} and operands and not consumed_pattern:
        operands = operands[1:]
    return operands


def _normalize_path(value: str) -> str:
    """Normalize a path for comparison without requiring it to exist."""
    return value.replace("\\", "/").rstrip("/")


def _diff_read_range(
    call: ToolCallRecord,
    *,
    diff_path: str | None,
    total_diff_lines: int,
) -> LineRange | None:
    """Return the diff-file line range a call read, when it named the diff."""
    if call.diff_read_path is not None:
        # A read of *another* diff file (the full diff while review scope is
        # incremental) cannot be mapped onto this diff's line numbers. Ignore
        # it rather than treating the whole scope as read: the reviewer was
        # told to read the incremental scope, and over-crediting here would
        # silence the nudge on exactly the re-review this feature targets.
        if diff_path is None or _normalize_path(call.diff_read_path) != _normalize_path(diff_path):
            return None
        start, end = call.diff_read or (0, 0)
        if start <= 0:
            return None if end < 0 else LineRange(1, max(total_diff_lines, 1))
        if start > total_diff_lines:
            return None
        if end < start:
            return None
        return LineRange(start, min(end, max(total_diff_lines, 1)))
    if not diff_path:
        return None
    target = _normalize_path(diff_path)
    candidates = [*call.paths]
    if call.command:
        candidates.extend(_read_paths(call.command))
    named = any(_normalize_path(item) == target for item in candidates)
    if not named and (not call.command or target not in call.command):
        return None
    span = command_line_span(call.command)
    if span is None:
        return LineRange(1, max(total_diff_lines, 1))
    start, end = span
    if start <= 0 or start > total_diff_lines:
        return None
    return LineRange(start, min(end, max(total_diff_lines, 1)))


def _source_ranges(
    path: str,
    command: str | None,
    entries: Sequence[DiffTocEntry],
) -> tuple[LineRange, ...]:
    """Return the added-line ranges of ``path`` a read covered."""
    entry = next((item for item in entries if item.path == path), None)
    if entry is None:
        return ()
    span = command_line_span(command)
    if span is None:
        return entry.ranges
    start, end = span
    if start <= 0 or end < start:
        return ()
    line_range = LineRange(start, end)
    covered: list[LineRange] = []
    for item in entry.ranges:
        overlap = item.intersect(line_range)
        if overlap is not None:
            covered.append(overlap)
    return tuple(covered)


def _diff_covered_ranges(entry: DiffTocEntry, *, diff_range: LineRange) -> tuple[LineRange, ...]:
    """Return post-image ranges whose diff-file lines fall in ``diff_range``."""
    selected = [
        source_line
        for diff_line, source_line in entry.line_map
        if diff_range.start <= diff_line <= diff_range.end
    ]
    covered: list[LineRange] = []
    for source_line in selected:
        if covered and source_line == covered[-1].end + 1:
            covered[-1] = LineRange(covered[-1].start, source_line)
        else:
            covered.append(LineRange(source_line, source_line))
    return tuple(covered)


def _mentions_diff(command: str | None, diff_path: str | None) -> bool:
    """Return whether a command text names the diff path."""
    if not command or not diff_path:
        return False
    return _normalize_path(diff_path) in _normalize_path(command)


def compute_diff_coverage(
    diff_text: str,
    calls: Sequence[ToolCallRecord],
    *,
    diff_path: str | None = None,
) -> DiffCoverageBreakdown:
    """Compute added-line coverage for ``diff_text`` from observed reads.

    Args:
        diff_text: The unified diff that defines review scope.
        calls: Mediated and external tool-call rows, in sequence order.
        diff_path: Absolute path of ``diff_text`` on disk, when a caller knows
            it. Reads of that path are mapped onto the added lines the read
            span showed; without it only source-file reads count.

    Returns:
        A :class:`DiffCoverageBreakdown`. ``observed`` is ``False`` when no
        read touched either the diff path or a source file in scope, which
        means *unknown* — not zero coverage.
    """
    entries = parse_diff_toc(diff_text)
    if not entries:
        return DiffCoverageBreakdown(files=(), observed=False)
    total_diff_lines = max(len(diff_text.splitlines()), 1)
    covered_by_file: dict[str, list[LineRange]] = {entry.path: [] for entry in entries}
    read_files: set[str] = set()
    observed = False
    entry_by_path = {entry.path: entry for entry in entries}
    for call in calls:
        if not call.ok or call.intent != "read":
            continue
        if call.diff_read_path is not None or call.paths or _mentions_diff(call.command, diff_path):
            observed = True
        diff_range = _diff_read_range(call, diff_path=diff_path, total_diff_lines=total_diff_lines)
        if diff_range is not None:
            for entry in entries:
                section = LineRange(entry.diff_start, entry.diff_end)
                if diff_range.intersect(section) is not None:
                    read_files.add(entry.path)
                covered_by_file[entry.path].extend(
                    _diff_covered_ranges(entry, diff_range=diff_range)
                )
        if not call.paths:
            continue
        for path in call.paths:
            matched_entry = entry_by_path.get(path)
            if matched_entry is None:
                continue
            read_files.add(path)
            covered_by_file[path].extend(_source_ranges(path, call.command, entries))

    files: list[FileDiffCoverage] = []
    for entry in entries:
        covered = _merge_ranges(covered_by_file[entry.path])
        files.append(
            FileDiffCoverage(
                path=entry.path,
                ranges=entry.ranges,
                covered=covered,
                unread=_subtract(entry.ranges, covered),
                deletion_only=entry.deletion_only,
                read=entry.path in read_files,
            )
        )
    return DiffCoverageBreakdown(files=tuple(files), observed=observed)


def _is_generated(path: str) -> bool:
    """Return whether ``path`` is a generated artifact the nudge may exempt."""
    lowered = path.casefold()
    if lowered.rsplit("/", maxsplit=1)[-1] in _GENERATED_MARKERS:
        return True
    if lowered.endswith(_GENERATED_SUFFIXES):
        return True
    return any(marker in lowered for marker in _GENERATED_DIRS)


def coverage_nudge(breakdown: DiffCoverageBreakdown, *, diff_path: str) -> str | None:
    """Return a one-time nudge naming every unread range, or ``None``.

    A run with nothing unread gets ``None``. Unread ranges in generated
    artifacts are named but marked skippable, so the agent can choose to skip
    them explicitly rather than have the reviewer silently ignore them.
    """
    if not breakdown.observed or not breakdown.unread_files():
        return None
    rows: list[str] = []
    generated_only = True
    for file in breakdown.unread_files():
        generated = (
            " (generated — skip if not reviewing generated output)"
            if _is_generated(file.path)
            else ""
        )
        if not generated:
            generated_only = False
        if file.deletion_only:
            rows.append(f"- `{file.path}` (deleted file — read the deletion){generated}")
            continue
        ranges = ", ".join(str(item) for item in file.unread)
        rows.append(f"- `{file.path}:{ranges}`{generated}")
    if generated_only:
        return None
    body = "\n".join(rows)
    return (
        "diff coverage pre-flight: some changed lines were not read before the verdict. "
        "This is a one-time nudge — read the ranges below from "
        f"`{diff_path}` (or the source files), then submit again. "
        "You are not obligated to read generated artifacts (lockfiles, codegen output, "
        "snapshots, migration metadata); if every unread range is generated, submit again "
        "immediately. This pre-flight will not fire again in this review session.\n\n"
        f"unread ranges:\n{body}"
    )


__all__ = [
    "DiffCoverageBreakdown",
    "DiffTocEntry",
    "FileDiffCoverage",
    "LineRange",
    "command_line_span",
    "compute_diff_coverage",
    "coverage_nudge",
    "parse_diff_toc",
]
