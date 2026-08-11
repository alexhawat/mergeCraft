"""Import classification and mandatory auto-removal (Go meat/imports.go parity)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum

from meat_python_plus.diffutil import (
    DiffLayout,
    DiffLineKind,
    SourceLanguage,
    SourceLine,
    is_hunk_source,
    next_layout_line,
)


@dataclass
class LineRange:
    start_line: int
    end_line: int


@dataclass
class ImportSideLine:
    index: int
    text: str


@dataclass
class ImportFileSection:
    start: int
    end: int


class PythonTripleState(IntEnum):
    NONE = 0
    SINGLE = 1
    DOUBLE = 2


_GO_IMPORT_BLOCK_START_RE = re.compile(r"^import\s*\(\s*(?://.*)?$")
_GO_IMPORT_BLOCK_END_RE = re.compile(r"^\)\s*(?://.*)?$")
_GO_IMPORT_MEMBER_RE = re.compile(
    r"^(?:(?:[._]|[A-Za-z_][A-Za-z0-9_]*)\s+)?"
    r'(?:"(?:[^"\\]|\\.)*"|`[^`]*`)\s*(?://.*)?$'
)
_GO_IMPORT_SINGLE_RE = re.compile(
    r'^import\s+(?:(?:[._]|[A-Za-z_][A-Za-z0-9_]*)\s+)?'
    r'(?:"(?:[^"\\]|\\.)*"|`[^`]*`)\s*(?://.*)?$'
)

_PYTHON_IMPORT_LIST_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*"
    r"(?:\s+as\s+[A-Za-z_][A-Za-z0-9_]*)?"
    r"(?:\s*,\s*[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*"
    r"(?:\s+as\s+[A-Za-z_][A-Za-z0-9_]*)?)*$"
)
_PYTHON_FROM_START_RE = re.compile(
    r"^from\s+(?:\.*(?:[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)?)"
    r"\s+import\s+(.+)$"
)
_PYTHON_FROM_LIST_RE = re.compile(
    r"^(?:\*|[A-Za-z_][A-Za-z0-9_]*(?:\s+as\s+[A-Za-z_][A-Za-z0-9_]*)?"
    r"(?:\s*,\s*[A-Za-z_][A-Za-z0-9_]*(?:\s+as\s+[A-Za-z_][A-Za-z0-9_]*)?)*)$"
)

_JAVASCRIPT_SIDE_EFFECT_IMPORT_RE = re.compile(
    r'(?s)^import\s+["\'`][^"\'`]+["\'`]\s*;?\s*(?://.*)?$'
)
_JAVASCRIPT_FROM_IMPORT_RE = re.compile(
    r'(?s)^import\s+.+\s+from\s+["\'`][^"\'`]+["\'`]'
    r"(?:\s+(?:with|assert)\s*\{.*\})?\s*;?\s*(?://.*)?$"
)
_JAVASCRIPT_TS_REQUIRE_IMPORT_RE = re.compile(
    r'(?s)^import\s+[A-Za-z_$][A-Za-z0-9_$]*\s*=\s*require\s*\(\s*["\'`][^"\'`]+["\'`]\s*\)\s*;?\s*(?://.*)?$'
)
_JAVASCRIPT_REQUIRE_RE = re.compile(
    r'(?s)^(?:require\s*\(\s*["\'`][^"\'`]+["\'`]\s*\)|'
    r"(?:const|let|var)\s+(?:[A-Za-z_$][A-Za-z0-9_$]*|\{[^;]*\}|\[[^;]*\])"
    r'\s*=\s*require\s*\(\s*["\'`][^"\'`]+["\'`]\s*\)(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*)\s*;?\s*(?://.*)?$'
)
_JAVASCRIPT_REQUIRE_START_RE = re.compile(
    r"^(?:const|let|var)\s+(?:[A-Za-z_$][A-Za-z0-9_$]*|\{[^;]*|\[[^;]*)\s*=\s*require\s*\("
)
_JAVASCRIPT_IMPORT_CONTINUATION_MEMBER_RE = re.compile(
    r"^[A-Za-z0-9_$,*{}\s]+(?:\s+as\s+[A-Za-z_$][A-Za-z0-9_$]*)?[,]?$"
)
_JAVASCRIPT_IMPORT_CONTINUATION_END_RE = re.compile(
    r'^}\s+from\s+["\'`][^"\'`]+["\'`]\s*;?$'
)

_RUST_USE_START_RE = re.compile(r"^(?:pub(?:\s*\([^)]*\))?\s+)?use\s+")
_RUST_USE_CONTINUATION_MEMBER_RE = re.compile(
    r"^[A-Za-z0-9_:,*{}\s]+(?:\s+as\s+[A-Za-z_][A-Za-z0-9_]*)?[,;]?$"
)
_C_INCLUDE_START_RE = re.compile(r'^#\s*include(?:_next)?(?:\s|[<"])')
_JAVA_IMPORT_RE = re.compile(
    r"^import\s+(?:static\s+)?[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$*][A-Za-z0-9_$*]*)*"
    r"(?:\s+as\s+[A-Za-z_$][A-Za-z0-9_$]*)?\s*;?\s*(?://.*)?$"
)

_HUNK_STOP = {
    DiffLineKind.HEADER,
    DiffLineKind.OLD_FILE,
    DiffLineKind.HUNK_HEADER,
    DiffLineKind.MAIL_SIGNATURE,
}


def leading_whitespace(s: str) -> str:
    i = 0
    while i < len(s) and s[i] in " \t":
        i += 1
    return s[:i]


def mandatory_import_removal_plan(
    lines: list[SourceLine], layout: DiffLayout
) -> list[LineRange]:
    """Compiler-owned import removal ranges derived from the immutable diff."""
    hidden = [False] * len(lines)

    for hunk, kind in enumerate(layout.kinds):
        if kind != DiffLineKind.HUNK_HEADER:
            continue
        end = next_layout_line(layout, hunk + 1, _HUNK_STOP)
        language = layout.language[hunk]
        continuation = hunk_starts_import_continuation(lines[hunk].text, language)
        side_masks: dict[str, dict[int, bool]] = {}
        for side in ("-", "+"):
            side_lines = import_lines_for_side(lines, layout, hunk + 1, end, side)
            side_hidden = classify_side_imports(side_lines, language, continuation)
            expand_python_import_only_suites(side_lines, side_hidden)
            fill_import_group_gaps(
                side_lines, side_hidden, embedded_source_lines(side_lines, language)
            )
            mask: dict[int, bool] = {}
            for i, line in enumerate(side_lines):
                if side_hidden[i]:
                    mask[line.index] = True
            side_masks[side] = mask

        for i in range(hunk + 1, end):
            if not is_hunk_source(layout.kinds[i]) or not lines[i].text:
                continue
            marker = lines[i].text[0]
            if marker == "-":
                hidden[i] = side_masks["-"].get(i, False)
            elif marker == "+":
                hidden[i] = side_masks["+"].get(i, False)
            elif marker == " ":
                hidden[i] = side_masks["-"].get(i, False) and side_masks["+"].get(
                    i, False
                )

        have_import_change = False
        import_only = True
        one_sided_change = hunk_changes_only_one_side(lines, layout, hunk + 1, end)
        for i in range(hunk + 1, end):
            if layout.kinds[i] != DiffLineKind.HUNK_CHANGE:
                continue
            if hidden[i]:
                have_import_change = True
                continue
            body = lines[i].text[1:]
            if is_import_only_framing_row(body, language, one_sided_change):
                continue
            import_only = False
        if have_import_change and import_only:
            for i in range(hunk, end):
                hidden[i] = True

    for i, kind in enumerate(layout.kinds):
        if (
            kind == DiffLineKind.NO_NEWLINE
            and layout.marker_owner[i] >= 0
            and hidden[layout.marker_owner[i]]
        ):
            hidden[i] = True

    for section in import_file_sections(layout):
        saw_hunk = False
        all_hunks_hidden = True
        for i in range(section.start, section.end):
            if layout.kinds[i] != DiffLineKind.HUNK_HEADER:
                continue
            saw_hunk = True
            if not hidden[i]:
                all_hunks_hidden = False
        if saw_hunk and all_hunks_hidden:
            for i in range(section.start, section.end):
                hidden[i] = True

    return hidden_line_ranges(hidden)


def mandatory_removal_mask(lines: int, ranges: list[LineRange]) -> list[bool]:
    hidden = [False] * lines
    for r in ranges:
        for line in range(r.start_line, r.end_line + 1):
            hidden[line - 1] = True
    return hidden


@dataclass
class _PlanStateView:
    hidden: list[bool]
    folded: list[int]
    fold_at: list[int]

    def represented(self, line: int) -> bool:
        return (not self.hidden[line]) or self.folded[line] >= 0


def complete_mandatory_import_framing(
    layout: DiffLayout,
    state: _PlanStateView,
    mandatory: list[bool],
) -> None:
    """Close hunk/file shells after mandatory import removal."""
    for hunk, kind in enumerate(layout.kinds):
        if kind != DiffLineKind.HUNK_HEADER:
            continue
        end = next_layout_line(layout, hunk + 1, _HUNK_STOP)
        has_mandatory_import = any(
            mandatory[i] and is_hunk_source(layout.kinds[i])
            for i in range(hunk + 1, end)
        )
        if not has_mandatory_import or any_retained_hunk_change(
            layout, state, hunk + 1, end
        ):
            continue
        for i in range(hunk, end):
            state.hidden[i] = True

    for section in import_file_sections(layout):
        has_mandatory_import = any(
            mandatory[i] and is_hunk_source(layout.kinds[i])
            for i in range(section.start, section.end)
        )
        if not has_mandatory_import:
            continue
        saw_hunk = False
        all_hunks_hidden = True
        for i in range(section.start, section.end):
            if layout.kinds[i] != DiffLineKind.HUNK_HEADER:
                continue
            saw_hunk = True
            if state.represented(i):
                all_hunks_hidden = False
        if saw_hunk and all_hunks_hidden:
            for i in range(section.start, section.end):
                state.hidden[i] = True


def any_retained_hunk_change(
    layout: DiffLayout, state: _PlanStateView, start: int, end: int
) -> bool:
    for i in range(start, end):
        if layout.kinds[i] == DiffLineKind.HUNK_CHANGE and state.represented(i):
            return True
    return False


def hidden_line_ranges(hidden: list[bool]) -> list[LineRange]:
    ranges: list[LineRange] = []
    i = 0
    while i < len(hidden):
        if not hidden[i]:
            i += 1
            continue
        start = i
        while i + 1 < len(hidden) and hidden[i + 1]:
            i += 1
        ranges.append(LineRange(start_line=start + 1, end_line=i + 1))
        i += 1
    return ranges


def hunk_changes_only_one_side(
    lines: list[SourceLine], layout: DiffLayout, start: int, end: int
) -> bool:
    have_old = False
    have_new = False
    for i in range(start, end):
        if layout.kinds[i] != DiffLineKind.HUNK_CHANGE or not lines[i].text:
            continue
        marker = lines[i].text[0]
        if marker == "-":
            have_old = True
        elif marker == "+":
            have_new = True
    return have_old != have_new


def is_identifier_start(ch: str) -> bool:
    return ch == "_" or ch.isalpha()


def is_identifier_continue(ch: str) -> bool:
    return is_identifier_start(ch) or ch.isdigit()


def is_import_only_framing_row(
    body: str, language: SourceLanguage, one_sided_change: bool
) -> bool:
    trimmed = body.strip()
    if trimmed == "":
        return True
    if not one_sided_change or language not in (
        SourceLanguage.GO,
        SourceLanguage.JAVA,
    ):
        return False
    if not trimmed.startswith("package "):
        return False
    name = trimmed.removeprefix("package ").removesuffix(";").strip()
    if name == "":
        return False
    for segment in name.split("."):
        if segment == "" or not is_identifier_start(segment[0]):
            return False
        for ch in segment[1:]:
            if not is_identifier_continue(ch):
                return False
    return True


def import_file_sections(layout: DiffLayout) -> list[ImportFileSection]:
    sections: list[ImportFileSection] = []
    for i, kind in enumerate(layout.kinds):
        if kind not in (DiffLineKind.HEADER, DiffLineKind.OLD_FILE):
            continue
        if (
            kind == DiffLineKind.OLD_FILE
            and i > 0
            and layout.file_id[i - 1] == layout.file_id[i]
            and layout.kinds[i - 1] != DiffLineKind.MAIL_SIGNATURE
        ):
            continue
        end = len(layout.kinds)
        for j in range(i + 1, len(layout.kinds)):
            if (
                layout.kinds[j] == DiffLineKind.MAIL_SIGNATURE
                or layout.file_id[j] != layout.file_id[i]
            ):
                end = j
                break
        sections.append(ImportFileSection(start=i, end=end))
    return sections


def import_lines_for_side(
    lines: list[SourceLine],
    layout: DiffLayout,
    start: int,
    end: int,
    side: str,
) -> list[ImportSideLine]:
    result: list[ImportSideLine] = []
    for i in range(start, end):
        if not is_hunk_source(layout.kinds[i]) or not lines[i].text:
            continue
        marker = lines[i].text[0]
        if marker == " " or marker == side:
            result.append(ImportSideLine(index=i, text=lines[i].text[1:]))
    return result


def hunk_section_text(header: str) -> str:
    if not header.startswith("@@"):
        return ""
    rest = header[2:]
    end = rest.find("@@")
    if end >= 0:
        return rest[end + 2 :].strip()
    return ""


def hunk_starts_import_continuation(
    header: str, language: SourceLanguage
) -> bool:
    section = hunk_section_text(header)
    if section == "":
        return False
    if language == SourceLanguage.GO:
        return _GO_IMPORT_BLOCK_START_RE.match(section) is not None
    if language == SourceLanguage.PYTHON:
        match = _PYTHON_FROM_START_RE.match(strip_python_import_comment(section))
        if match is None:
            return False
        return match.group(1).strip().startswith("(")
    if language == SourceLanguage.JAVASCRIPT:
        if not section.startswith("import "):
            return False
        if (
            _JAVASCRIPT_SIDE_EFFECT_IMPORT_RE.match(section)
            or _JAVASCRIPT_FROM_IMPORT_RE.match(section)
            or _JAVASCRIPT_TS_REQUIRE_IMPORT_RE.match(section)
        ):
            return False
        return (
            section.count("{") > section.count("}")
            or section.count("[") > section.count("]")
            or section.count("(") > section.count(")")
        )
    if language == SourceLanguage.RUST:
        return (
            _RUST_USE_START_RE.match(section) is not None
            and "{" in section
            and not section.strip().endswith(";")
        )
    return False


def import_continuation_end(
    lines: list[ImportSideLine], language: SourceLanguage
) -> int:
    if not lines:
        return 0
    if language == SourceLanguage.GO:
        for i, line in enumerate(lines):
            trimmed = line.text.strip()
            if trimmed == "" or trimmed.startswith("//"):
                continue
            if _GO_IMPORT_BLOCK_END_RE.match(trimmed):
                return i + 1
            if not _GO_IMPORT_MEMBER_RE.match(trimmed):
                return 0
        return len(lines)
    if language == SourceLanguage.PYTHON:
        balance = 1
        for i, line in enumerate(lines):
            part = strip_python_import_comment(line.text.strip())
            if part == "":
                continue
            balance += part.count("(") - part.count(")")
            member = part.replace("(", "").replace(")", "").strip().removesuffix(",")
            if member != "" and not _PYTHON_FROM_LIST_RE.match(member):
                return 0
            if balance <= 0:
                return i + 1
        return len(lines)
    if language == SourceLanguage.JAVASCRIPT:
        balance = 1
        for i, line in enumerate(lines):
            trimmed = line.text.strip()
            if trimmed == "" or trimmed.startswith("//"):
                continue
            balance += trimmed.count("{") - trimmed.count("}")
            if balance <= 0 and _JAVASCRIPT_IMPORT_CONTINUATION_END_RE.match(trimmed):
                return i + 1
            if not _JAVASCRIPT_IMPORT_CONTINUATION_MEMBER_RE.match(trimmed):
                return 0
        return len(lines)
    if language == SourceLanguage.RUST:
        for i, line in enumerate(lines):
            trimmed = line.text.strip()
            if trimmed == "" or trimmed.startswith("//"):
                continue
            if not _RUST_USE_CONTINUATION_MEMBER_RE.match(trimmed):
                return 0
            if trimmed.endswith(";"):
                return i + 1
        return len(lines)
    return 0


def classify_side_imports(
    lines: list[ImportSideLine],
    language: SourceLanguage,
    continuation: bool,
) -> list[bool]:
    hidden = [False] * len(lines)
    if continuation:
        end = import_continuation_end(lines, language)
        for i in range(end):
            hidden[i] = True
    embedded = embedded_source_lines(lines, language)
    i = 0
    while i < len(lines):
        scan_lines = lines
        if embedded[i]:
            limit = embedded_source_end(embedded, i)
            if limit <= i:
                i += 1
                continue
            scan_lines = lines[: limit + 1]
        end = import_statement_end(scan_lines, i, language, embedded[i])
        if end <= i:
            i += 1
            continue
        for j in range(i, end):
            hidden[j] = True
        i = end
    return hidden


def trim_python_code(text: str) -> str:
    quote = ""
    escaped = False
    for i, b in enumerate(text):
        if quote:
            if escaped:
                escaped = False
                continue
            if b == "\\":
                escaped = True
                continue
            if b == quote:
                quote = ""
            continue
        if b in ("'", '"'):
            quote = b
            continue
        if b == "#":
            return text[:i].strip()
    return text.strip()


def is_python_import_guard(trimmed: str) -> bool:
    if not trimmed.endswith(":"):
        return False
    return (
        trimmed == "try:"
        or trimmed.startswith("if ")
        or trimmed.startswith("with ")
        or trimmed.startswith("async with ")
        or trimmed.startswith("except")
    )


def is_python_import_guard_clause(trimmed: str) -> bool:
    if not trimmed.endswith(":"):
        return False
    return (
        trimmed == "else:"
        or trimmed == "finally:"
        or trimmed.startswith("elif ")
        or trimmed.startswith("except")
    )


def expand_python_import_only_suites(
    lines: list[ImportSideLine], hidden: list[bool]
) -> None:
    i = 0
    while i < len(lines):
        if hidden[i]:
            i += 1
            continue
        body = lines[i].text
        trimmed = trim_python_code(body)
        if not is_python_import_guard(trimmed):
            i += 1
            continue
        owner_indent = len(leading_whitespace(body))
        end = i + 1
        have_import = False
        import_only = True
        while end < len(lines):
            candidate = lines[end].text
            candidate_trimmed = trim_python_code(candidate)
            if candidate_trimmed == "":
                end += 1
                continue
            indent = len(leading_whitespace(candidate))
            if indent < owner_indent or (
                indent == owner_indent
                and not is_python_import_guard_clause(candidate_trimmed)
            ):
                break
            if indent == owner_indent:
                end += 1
                continue
            if hidden[end]:
                have_import = True
                end += 1
                continue
            import_only = False
            break
        if have_import and import_only:
            for j in range(i, end):
                hidden[j] = True
            i = end
            continue
        i += 1


def fill_import_group_gaps(
    lines: list[ImportSideLine], hidden: list[bool], embedded: list[bool]
) -> None:
    previous = -1
    for i in range(len(lines)):
        if not hidden[i]:
            continue
        if previous >= 0:
            blank_gap = True
            for j in range(previous + 1, i):
                if lines[j].text.strip() != "":
                    blank_gap = False
                    break
            if blank_gap:
                for j in range(previous + 1, i):
                    hidden[j] = True
        previous = i

    i = 0
    while i < len(lines):
        if not hidden[i]:
            i += 1
            continue
        while i < len(lines) and hidden[i]:
            i += 1
        while (
            i < len(lines)
            and embedded[i]
            and lines[i].text.strip() == ""
        ):
            hidden[i] = True
            i += 1


def embedded_source_end(embedded: list[bool], start: int) -> int:
    for i in range(start, len(embedded) - 1):
        if embedded[i] and not embedded[i + 1]:
            return i
    return len(embedded) - 1


def scan_python_triple_line(text: str, state: list[PythonTripleState]) -> int:
    transitions = 0
    i = 0
    while i < len(text):
        if state[0] != PythonTripleState.NONE:
            delim = '"""' if state[0] == PythonTripleState.DOUBLE else "'''"
            at = text.find(delim, i)
            if at < 0:
                return transitions
            i = at + len(delim)
            state[0] = PythonTripleState.NONE
            transitions += 1
            continue
        if text[i] == "#":
            return transitions
        if text.startswith("'''", i):
            state[0] = PythonTripleState.SINGLE
            transitions += 1
            i += 3
            continue
        if text.startswith('"""', i):
            state[0] = PythonTripleState.DOUBLE
            transitions += 1
            i += 3
            continue
        if text[i] in ("'", '"'):
            quote = text[i]
            i += 1
            while i < len(text):
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        i += 1
    return transitions


def count_code_backticks(text: str) -> int:
    count = 0
    quote = ""
    escaped = False
    i = 0
    while i < len(text):
        b = text[i]
        if quote:
            if escaped:
                escaped = False
                i += 1
                continue
            if b == "\\":
                escaped = True
                i += 1
                continue
            if b == quote:
                quote = ""
            i += 1
            continue
        if b == "/" and i + 1 < len(text) and text[i + 1] == "/":
            break
        if b in ("'", '"'):
            quote = b
            i += 1
            continue
        if b == "`":
            backslashes = 0
            j = i - 1
            while j >= 0 and text[j] == "\\":
                backslashes += 1
                j -= 1
            if backslashes % 2 == 0:
                count += 1
        i += 1
    return count


def embedded_source_lines(
    lines: list[ImportSideLine], language: SourceLanguage
) -> list[bool]:
    flags = [False] * len(lines)
    triple = [PythonTripleState.NONE]
    backtick = False
    for i, line in enumerate(lines):
        flags[i] = triple[0] != PythonTripleState.NONE or backtick
        if language in (SourceLanguage.PYTHON, SourceLanguage.JAVA):
            scan_python_triple_line(line.text, triple)
        if language in (SourceLanguage.GO, SourceLanguage.JAVASCRIPT):
            if count_code_backticks(line.text) % 2 == 1:
                backtick = not backtick
    return flags


def strong_embedded_import_candidate(
    text: str, language: SourceLanguage
) -> bool:
    trimmed = text.strip()
    if language == SourceLanguage.RUST:
        return (
            "::" in trimmed
            or "{" in trimmed
            or trimmed.startswith("pub use ")
        )
    if language == SourceLanguage.C:
        return "<" in trimmed or '"' in trimmed
    return True


def import_statement_end(
    lines: list[ImportSideLine],
    start: int,
    language: SourceLanguage,
    embedded: bool,
) -> int:
    def try_language(lang: SourceLanguage) -> int:
        if lang == SourceLanguage.GO:
            return go_import_end(lines, start)
        if lang == SourceLanguage.PYTHON:
            return python_import_end(lines, start)
        if lang == SourceLanguage.JAVASCRIPT:
            end = javascript_import_end(lines, start)
            if end > start:
                return end
            return javascript_require_end(lines, start)
        if lang == SourceLanguage.RUST:
            return rust_use_end(lines, start)
        if lang == SourceLanguage.C:
            return c_include_end(lines, start)
        if lang == SourceLanguage.JAVA:
            return java_import_end(lines, start)
        return start

    end = try_language(language)
    if end > start:
        return end
    if not embedded:
        return start
    for candidate in (
        SourceLanguage.GO,
        SourceLanguage.PYTHON,
        SourceLanguage.JAVASCRIPT,
        SourceLanguage.RUST,
        SourceLanguage.C,
        SourceLanguage.JAVA,
    ):
        if candidate == language:
            continue
        if not strong_embedded_import_candidate(lines[start].text, candidate):
            continue
        end = try_language(candidate)
        if end > start:
            return end
    return start


def go_import_end(lines: list[ImportSideLine], start: int) -> int:
    trimmed = lines[start].text.strip()
    if _GO_IMPORT_SINGLE_RE.match(trimmed):
        return start + 1
    if not _GO_IMPORT_BLOCK_START_RE.match(trimmed):
        return start
    for i in range(start + 1, min(len(lines), start + 201)):
        trimmed = lines[i].text.strip()
        if _GO_IMPORT_BLOCK_END_RE.match(trimmed):
            return i + 1
        if (
            trimmed == ""
            or trimmed.startswith("//")
            or _GO_IMPORT_MEMBER_RE.match(trimmed)
        ):
            continue
        return i
    return len(lines)


def strip_python_import_comment(text: str) -> str:
    if "#" in text:
        text = text[: text.index("#")]
    return text.strip()


def python_continued_import_end(
    lines: list[ImportSideLine],
    start: int,
    rest: str,
    final: re.Pattern[str],
) -> int:
    if rest.startswith("("):
        balance = rest.count("(") - rest.count(")")
        if balance <= 0:
            inside = rest.removeprefix("(").removesuffix(")").strip()
            if final.match(inside.removesuffix(",").strip()):
                return start + 1
            return start
        contents: list[str] = []
        for i in range(start + 1, min(len(lines), start + 201)):
            part = strip_python_import_comment(lines[i].text.strip())
            member = (
                part.replace("(", "").replace(")", "").strip().removesuffix(",")
            )
            if member != "" and not final.match(member):
                return i
            balance += part.count("(") - part.count(")")
            contents.append(part.replace("(", "").replace(")", ""))
            if balance == 0:
                inside = " ".join(contents).strip().removesuffix(",")
                if final.match(inside):
                    return i + 1
                return i
        return len(lines)
    if rest.endswith("\\"):
        joined: list[str] = [rest.removesuffix("\\").strip()]
        for i in range(start + 1, min(len(lines), start + 51)):
            part = strip_python_import_comment(lines[i].text.strip())
            continued = part.endswith("\\")
            part = part.removesuffix("\\").strip()
            joined.append(part)
            if not continued:
                if final.match(" ".join(joined).strip()):
                    return i + 1
                return start
        return len(lines)
    if final.match(rest):
        return start + 1
    return start


def python_import_end(lines: list[ImportSideLine], start: int) -> int:
    code = strip_python_import_comment(lines[start].text.strip())
    if code.startswith("import "):
        rest = code.removeprefix("import ").strip()
        return python_continued_import_end(lines, start, rest, _PYTHON_IMPORT_LIST_RE)
    match = _PYTHON_FROM_START_RE.match(code)
    if match is None:
        return start
    return python_continued_import_end(
        lines, start, match.group(1).strip(), _PYTHON_FROM_LIST_RE
    )


def javascript_import_end(lines: list[ImportSideLine], start: int) -> int:
    trimmed = lines[start].text.strip()
    if not trimmed.startswith("import "):
        return start
    after = trimmed.removeprefix("import ").strip()
    if after.startswith("("):
        return start
    joined: list[str] = []
    for i in range(start, min(len(lines), start + 81)):
        trimmed_line = lines[i].text.strip()
        if joined:
            joined.append(" ")
        joined.append(trimmed_line)
        statement = "".join(joined)
        if (
            _JAVASCRIPT_SIDE_EFFECT_IMPORT_RE.match(statement)
            or _JAVASCRIPT_FROM_IMPORT_RE.match(statement)
            or _JAVASCRIPT_TS_REQUIRE_IMPORT_RE.match(statement)
        ):
            return i + 1
        if i == start:
            if (
                "{" in trimmed
                or "[" in trimmed
                or trimmed.endswith(",")
            ):
                continue
            return start
        if (
            trimmed_line == ""
            or trimmed_line.startswith("//")
            or _JAVASCRIPT_IMPORT_CONTINUATION_MEMBER_RE.match(trimmed_line)
        ):
            continue
        return i
    return len(lines)


def javascript_require_end(lines: list[ImportSideLine], start: int) -> int:
    trimmed = lines[start].text.strip()
    bare_require = trimmed.startswith("require(") or trimmed.startswith("require (")
    direct_require = bare_require or _JAVASCRIPT_REQUIRE_START_RE.match(trimmed) is not None
    candidate = direct_require
    for keyword in ("const ", "let ", "var "):
        if not trimmed.startswith(keyword):
            continue
        unclosed = (
            trimmed.count("{") > trimmed.count("}")
            or trimmed.count("[") > trimmed.count("]")
        )
        if unclosed:
            candidate = True
    if not candidate:
        return start
    joined: list[str] = []
    for i in range(start, min(len(lines), start + 81)):
        if joined:
            joined.append(" ")
        joined.append(lines[i].text.strip())
        if _JAVASCRIPT_REQUIRE_RE.match("".join(joined)):
            return i + 1
    return start


def rust_use_end(lines: list[ImportSideLine], start: int) -> int:
    trimmed = lines[start].text.strip()
    if not _RUST_USE_START_RE.match(trimmed):
        return start
    if trimmed.endswith(";"):
        return start + 1
    if "{" not in trimmed and not trimmed.endswith("::"):
        return start
    for i in range(start + 1, min(len(lines), start + 201)):
        candidate = lines[i].text.strip()
        if candidate == "" or candidate.startswith("//"):
            continue
        if not _RUST_USE_CONTINUATION_MEMBER_RE.match(candidate):
            return i
        if candidate.endswith(";"):
            return i + 1
    return len(lines)


def c_include_end(lines: list[ImportSideLine], start: int) -> int:
    trimmed = lines[start].text.strip()
    if not _C_INCLUDE_START_RE.match(trimmed):
        return start
    for i in range(start, min(len(lines), start + 51)):
        if not lines[i].text.strip().endswith("\\"):
            return i + 1
    return len(lines)


def java_import_end(lines: list[ImportSideLine], start: int) -> int:
    if _JAVA_IMPORT_RE.match(lines[start].text.strip()):
        return start + 1
    return start
