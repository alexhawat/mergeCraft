"""Unified-diff line splitting, numbering, and layout analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class DiffLineKind(IntEnum):
    OTHER = 0
    HEADER = 1
    INDEX = 2
    RENAME_FROM = 3
    RENAME_TO = 4
    COPY_FROM = 5
    COPY_TO = 6
    MAIL_SIGNATURE = 7
    OLD_FILE = 8
    NEW_FILE = 9
    HUNK_HEADER = 10
    HUNK_CONTEXT = 11
    HUNK_CHANGE = 12
    NO_NEWLINE = 13


class SourceLanguage(IntEnum):
    UNKNOWN = 0
    GO = 1
    PYTHON = 2
    JAVASCRIPT = 3
    RUST = 4
    C = 5
    JAVA = 6


@dataclass
class SourceLine:
    text: str
    eol: str = ""


@dataclass
class DiffLayout:
    kinds: list[DiffLineKind]
    marker_owner: list[int]
    python: list[bool]
    language: list[SourceLanguage]
    file_id: list[int]
    hunk_id: list[int]
    problems: list[str] = field(default_factory=list)


def split_source_lines(text: str) -> list[SourceLine]:
    if not text:
        return []
    lines: list[SourceLine] = []
    remaining = text
    while remaining:
        i = remaining.find("\n")
        if i < 0:
            lines.append(SourceLine(text=remaining))
            break
        line, eol = remaining[:i], "\n"
        if line.endswith("\r"):
            line = line[:-1]
            eol = "\r\n"
        lines.append(SourceLine(text=line, eol=eol))
        remaining = remaining[i + 1 :]
    return lines


def is_git_diff_header(line: str) -> bool:
    return line.startswith("diff --git ")


def is_format_patch_signature(line: str) -> bool:
    return line == "-- "


def is_no_newline_marker(line: str) -> bool:
    return line == r"\ No newline at end of file"


def is_file_marker(line: str, marker: str) -> bool:
    return line.startswith(marker + " ") or line.startswith(marker + "\t")


def is_raw_old_file_header(lines: list[SourceLine], index: int) -> bool:
    return (
        index + 1 < len(lines)
        and is_file_marker(lines[index].text, "---")
        and is_file_marker(lines[index + 1].text, "+++")
    )


def validate_supported_diff(diff: str) -> None:
    lines = split_source_lines(diff)
    validate_supported_diff_lines(lines)
    layout = analyze_diff(lines)
    if layout.problems:
        raise ValueError("; ".join(layout.problems))


def validate_supported_diff_lines(lines: list[SourceLine]) -> None:
    in_patch = False
    for i, line in enumerate(lines):
        text = line.text
        if is_format_patch_signature(text):
            in_patch = False
        elif text.startswith("diff --cc ") or text.startswith("diff --combined "):
            raise ValueError(
                f"combined diff on line {i + 1} is unsupported; "
                "use a normal first-parent or two-tree diff"
            )
        elif is_git_diff_header(text):
            in_patch = True
        elif is_raw_old_file_header(lines, i):
            in_patch = True
        if in_patch and text.startswith("@@@"):
            raise ValueError(
                f"combined diff hunk on line {i + 1} is unsupported; "
                "use a normal first-parent or two-tree diff"
            )


def numbered_diff(diff: str) -> str:
    lines = split_source_lines(diff)
    if not lines:
        return ""
    width = len(str(len(lines)))
    parts: list[str] = []
    for i, line in enumerate(lines):
        parts.append(f"{i + 1:>{width}}|{line.text}\n")
    return "".join(parts)


def is_hunk_source(kind: DiffLineKind) -> bool:
    return kind in (DiffLineKind.HUNK_CONTEXT, DiffLineKind.HUNK_CHANGE)


def hunk_source_kind(text: str) -> DiffLineKind:
    if not text:
        return DiffLineKind.OTHER
    if text[0] == " ":
        return DiffLineKind.HUNK_CONTEXT
    if text[0] in "+-":
        return DiffLineKind.HUNK_CHANGE
    return DiffLineKind.OTHER


def parse_hunk_range(field: str, sign: str) -> tuple[int, bool]:
    if len(field) < 2 or field[0] != sign:
        return 0, False
    range_text = field[1:]
    count = 1
    if "," in range_text:
        start, _, count_s = range_text.partition(",")
        try:
            count = int(count_s)
        except ValueError:
            return 0, False
        if count < 0:
            return 0, False
        range_text = start
    try:
        int(range_text)
    except ValueError:
        return 0, False
    return count, True


def parse_hunk_counts(header: str) -> tuple[int, int, bool]:
    fields = header.split()
    if len(fields) < 4 or fields[0] != "@@" or fields[3] != "@@":
        return 0, 0, False
    old_count, ok = parse_hunk_range(fields[1], "-")
    if not ok:
        return 0, 0, False
    new_count, ok = parse_hunk_range(fields[2], "+")
    return old_count, new_count, ok


def path_language(path: str) -> SourceLanguage:
    path = path.lower().strip('"')
    if path.endswith(".go"):
        return SourceLanguage.GO
    if path.endswith((".py", ".pyi")):
        return SourceLanguage.PYTHON
    if path.endswith((".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts")):
        return SourceLanguage.JAVASCRIPT
    if path.endswith(".rs"):
        return SourceLanguage.RUST
    if path.endswith((".c", ".h", ".cc", ".hh", ".cpp", ".hpp", ".cxx", ".hxx")):
        return SourceLanguage.C
    if path.endswith((".java", ".kt", ".kts")):
        return SourceLanguage.JAVA
    return SourceLanguage.UNKNOWN


def diff_header_language(line: str) -> SourceLanguage:
    fields = line.split()
    if len(fields) < 4:
        return SourceLanguage.UNKNOWN
    language = SourceLanguage.UNKNOWN
    for field in fields[2:]:
        candidate = path_language(field)
        if candidate != SourceLanguage.UNKNOWN:
            language = candidate
    return language


def file_marker_language(line: str) -> SourceLanguage:
    if len(line) < 4:
        return SourceLanguage.UNKNOWN
    path = line[4:].strip()
    if "\t" in path:
        path = path.split("\t", 1)[0]
    return path_language(path)


def analyze_diff(lines: list[SourceLine]) -> DiffLayout:
    n = len(lines)
    layout = DiffLayout(
        kinds=[DiffLineKind.OTHER] * n,
        marker_owner=[-1] * n,
        python=[False] * n,
        language=[SourceLanguage.UNKNOWN] * n,
        file_id=[-1] * n,
        hunk_id=[-1] * n,
    )

    in_hunk = False
    counts_known = False
    hunk_problem_reported = False
    old_remain = 0
    new_remain = 0
    hunk_header_line = 0
    current_language = SourceLanguage.UNKNOWN
    current_file_id = -1
    current_hunk_id = -1
    git_file_section = False
    in_file_section = False

    def report_hunk_problem(at_line: int) -> None:
        nonlocal hunk_problem_reported
        if hunk_problem_reported:
            return
        layout.problems.append(
            f"hunk header on line {hunk_header_line + 1} has counts inconsistent "
            f"with its body near line {at_line + 1}"
        )
        hunk_problem_reported = True

    i = 0
    while i < n:
        text = lines[i].text
        if not in_hunk:
            if is_git_diff_header(text):
                current_file_id += 1
                git_file_section = True
                in_file_section = True
                current_language = diff_header_language(text)
            elif is_raw_old_file_header(lines, i):
                if not git_file_section:
                    current_file_id += 1
                in_file_section = True
                old_lang = file_marker_language(lines[i].text)
                if old_lang != SourceLanguage.UNKNOWN:
                    current_language = old_lang
                new_lang = file_marker_language(lines[i + 1].text)
                if new_lang != SourceLanguage.UNKNOWN:
                    current_language = new_lang

        layout.language[i] = current_language
        layout.python[i] = current_language == SourceLanguage.PYTHON
        layout.file_id[i] = current_file_id

        if in_hunk:
            if not counts_known and is_raw_old_file_header(lines, i):
                in_hunk = False
                continue
            if counts_known and old_remain == 0 and new_remain == 0:
                if is_no_newline_marker(text):
                    layout.kinds[i] = DiffLineKind.NO_NEWLINE
                    layout.hunk_id[i] = current_hunk_id
                    if i > 0 and is_hunk_source(layout.kinds[i - 1]):
                        layout.marker_owner[i] = i - 1
                    i += 1
                    continue
                if (
                    is_raw_old_file_header(lines, i)
                    or is_git_diff_header(text)
                    or text.startswith("@@")
                    or is_format_patch_signature(text)
                ):
                    in_hunk = False
                    continue
                kind = hunk_source_kind(text)
                if kind != DiffLineKind.OTHER:
                    report_hunk_problem(i)
                    layout.kinds[i] = kind
                    layout.hunk_id[i] = current_hunk_id
                    i += 1
                    continue
                in_hunk = False
                continue

            if is_no_newline_marker(text):
                layout.kinds[i] = DiffLineKind.NO_NEWLINE
                layout.hunk_id[i] = current_hunk_id
                if i > 0 and is_hunk_source(layout.kinds[i - 1]):
                    layout.marker_owner[i] = i - 1
                i += 1
                continue

            kind = hunk_source_kind(text)
            if kind != DiffLineKind.OTHER:
                if counts_known:
                    valid = False
                    ch = text[0]
                    if ch == " ":
                        valid = old_remain > 0 and new_remain > 0
                        if valid:
                            old_remain -= 1
                            new_remain -= 1
                    elif ch == "-":
                        valid = old_remain > 0
                        if valid:
                            old_remain -= 1
                    elif ch == "+":
                        valid = new_remain > 0
                        if valid:
                            new_remain -= 1
                    if not valid:
                        report_hunk_problem(i)
                layout.kinds[i] = kind
                layout.hunk_id[i] = current_hunk_id
                i += 1
                continue

            if counts_known and (old_remain != 0 or new_remain != 0):
                report_hunk_problem(i)
            in_hunk = False
            continue

        if is_format_patch_signature(text):
            layout.kinds[i] = DiffLineKind.MAIL_SIGNATURE
            in_file_section = False
            git_file_section = False
            i += 1
        elif is_git_diff_header(text):
            layout.kinds[i] = DiffLineKind.HEADER
            i += 1
        elif in_file_section and (
            text.startswith("index ")
            or text.startswith("similarity index ")
            or text.startswith("dissimilarity index ")
        ):
            layout.kinds[i] = DiffLineKind.INDEX
            i += 1
        elif in_file_section and text.startswith("rename from "):
            layout.kinds[i] = DiffLineKind.RENAME_FROM
            i += 1
        elif in_file_section and text.startswith("rename to "):
            layout.kinds[i] = DiffLineKind.RENAME_TO
            i += 1
        elif in_file_section and text.startswith("copy from "):
            layout.kinds[i] = DiffLineKind.COPY_FROM
            i += 1
        elif in_file_section and text.startswith("copy to "):
            layout.kinds[i] = DiffLineKind.COPY_TO
            i += 1
        elif is_raw_old_file_header(lines, i):
            layout.kinds[i] = DiffLineKind.OLD_FILE
            layout.kinds[i + 1] = DiffLineKind.NEW_FILE
            layout.language[i + 1] = current_language
            layout.python[i + 1] = current_language == SourceLanguage.PYTHON
            layout.file_id[i + 1] = current_file_id
            i += 2
        elif (in_file_section or text == "@@" or text.startswith("@@ ")) and text.startswith(
            "@@"
        ):
            layout.kinds[i] = DiffLineKind.HUNK_HEADER
            current_hunk_id += 1
            layout.hunk_id[i] = current_hunk_id
            old_remain, new_remain, counts_known = parse_hunk_counts(text)
            in_hunk = True
            hunk_header_line = i
            hunk_problem_reported = False
            i += 1
        else:
            i += 1

    if in_hunk and counts_known and (old_remain != 0 or new_remain != 0):
        report_hunk_problem(n - 1)
    return layout


def containing_hunk(layout: DiffLayout, line: int) -> tuple[int, int]:
    """Return (hunk_body_start, hunk_body_end) for the hunk containing line."""
    start = line
    while start > 0 and layout.kinds[start] != DiffLineKind.HUNK_HEADER:
        start -= 1
    if layout.kinds[start] == DiffLineKind.HUNK_HEADER:
        start += 1
    end = line + 1
    while end < len(layout.kinds):
        kind = layout.kinds[end]
        if kind in (
            DiffLineKind.HUNK_HEADER,
            DiffLineKind.HEADER,
            DiffLineKind.OLD_FILE,
            DiffLineKind.MAIL_SIGNATURE,
        ):
            break
        end += 1
    return start, end


def next_layout_line(
    layout: DiffLayout, start: int, stop_kinds: set[DiffLineKind]
) -> int:
    for i in range(start, len(layout.kinds)):
        if layout.kinds[i] in stop_kinds:
            return i
    return len(layout.kinds)


def elision_line(raw: str, abridged: str) -> str:
    """Human-readable kept/elided summary (simplified vs Go meat)."""
    raw_layout = analyze_diff(split_source_lines(raw))
    raw_changed = sum(1 for k in raw_layout.kinds if k == DiffLineKind.HUNK_CHANGE)
    raw_files = sum(1 for k in raw_layout.kinds if k == DiffLineKind.HEADER)
    if raw_changed == 0:
        return ""
    if not abridged.strip():
        return f"elided all {raw_changed} changed lines in {raw_files} files"
    abr_layout = analyze_diff(split_source_lines(abridged))
    kept_changed = sum(1 for k in abr_layout.kinds if k == DiffLineKind.HUNK_CHANGE)
    # Count fold lines as kept changed
    for line in split_source_lines(abridged):
        if line.text and line.text[0] in "+-" and line.text[1:].strip() == "...":
            kept_changed += 1
    kept_files = sum(1 for k in abr_layout.kinds if k == DiffLineKind.HEADER)
    if kept_files > 0 and raw_files > 0:
        return (
            f"kept {kept_changed}/{raw_changed} changed lines "
            f"in {kept_files}/{raw_files} files"
        )
    return f"kept {kept_changed}/{raw_changed} changed lines"
