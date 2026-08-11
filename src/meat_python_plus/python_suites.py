"""Python-aware edit-plan validators (Go meat/python.go parity)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from meat_python_plus.diffutil import (
    DiffLayout,
    DiffLineKind,
    SourceLine,
    containing_hunk,
    is_hunk_source,
    next_layout_line,
)
from meat_python_plus.imports import (
    PythonTripleState,
    is_identifier_continue,
    is_identifier_start,
    scan_python_triple_line,
    trim_python_code,
)

if TYPE_CHECKING:
    from meat_python_plus.editplan import LineFold, PlannedFold, PlannedReplacement, PlanState

_HUNK_STOP = {
    DiffLineKind.HEADER,
    DiffLineKind.OLD_FILE,
    DiffLineKind.HUNK_HEADER,
    DiffLineKind.MAIL_SIGNATURE,
}


@dataclass(frozen=True)
class PythonDelimiters:
    round: int = 0
    square: int = 0
    curly: int = 0

    def add(self, other: PythonDelimiters) -> PythonDelimiters:
        return PythonDelimiters(
            round=self.round + other.round,
            square=self.square + other.square,
            curly=self.curly + other.curly,
        )


def leading_whitespace(s: str) -> str:
    i = 0
    while i < len(s) and s[i] in " \t":
        i += 1
    return s[:i]


def changes_python_boundary_tokens(old: str, new: str) -> bool:
    for token in ("(", ")", "[", "]", "{", "}", "'''", '"""'):
        if old.count(token) != new.count(token):
            return True
    return False


def is_python_definition(trimmed: str) -> bool:
    trimmed = trim_python_code(trimmed)
    return (
        trimmed.startswith("def ")
        or trimmed.startswith("async def ")
        or trimmed.startswith("class ")
    )


def has_python_keyword(text: str, keyword: str) -> bool:
    if not text.startswith(keyword) or len(text) == len(keyword):
        return False
    nxt = text[len(keyword)]
    return nxt in " \t("


def is_python_suite_header_start(trimmed: str) -> bool:
    trimmed = trim_python_code(trimmed)
    if is_python_definition(trimmed):
        return True
    for keyword in (
        "if",
        "elif",
        "for",
        "while",
        "with",
        "except",
        "except*",
        "match",
        "case",
    ):
        if has_python_keyword(trimmed, keyword):
            return True
    for keyword in ("async for", "async with"):
        if trimmed.startswith(keyword + " ") or trimmed.startswith(keyword + "("):
            return True
    return trimmed in ("else:", "try:", "except:", "finally:")


def python_delimiter_balance_with_state(
    text: str, state: list[PythonTripleState]
) -> PythonDelimiters:
    balance = PythonDelimiters()
    i = 0
    while i < len(text):
        if state[0] != PythonTripleState.NONE:
            delim = '"""' if state[0] == PythonTripleState.DOUBLE else "'''"
            at = text.find(delim, i)
            if at < 0:
                return balance
            i = at + len(delim)
            state[0] = PythonTripleState.NONE
            continue
        b = text[i]
        if b == "#":
            break
        if text.startswith("'''", i):
            state[0] = PythonTripleState.SINGLE
            i += 3
            continue
        if text.startswith('"""', i):
            state[0] = PythonTripleState.DOUBLE
            i += 3
            continue
        if b in ("'", '"'):
            quote = b
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
        if b == "(":
            balance = PythonDelimiters(round=balance.round + 1, square=balance.square, curly=balance.curly)
        elif b == ")":
            balance = PythonDelimiters(round=balance.round - 1, square=balance.square, curly=balance.curly)
        elif b == "[":
            balance = PythonDelimiters(round=balance.round, square=balance.square + 1, curly=balance.curly)
        elif b == "]":
            balance = PythonDelimiters(round=balance.round, square=balance.square - 1, curly=balance.curly)
        elif b == "{":
            balance = PythonDelimiters(round=balance.round, square=balance.square, curly=balance.curly + 1)
        elif b == "}":
            balance = PythonDelimiters(round=balance.round, square=balance.square, curly=balance.curly - 1)
        i += 1
    return balance


def python_delimiter_balance(text: str) -> PythonDelimiters:
    state = [PythonTripleState.NONE]
    return python_delimiter_balance_with_state(text, state)


def python_delimiter_depth(text: str) -> int:
    d = python_delimiter_balance(text)
    return d.round + d.square + d.curly


def python_triple_state_before_line(
    lines: list[SourceLine], layout: DiffLayout, line: int
) -> PythonTripleState:
    hunk_start, _ = containing_hunk(layout, line)
    state = [PythonTripleState.NONE]
    for i in range(hunk_start, line):
        if not is_hunk_source(layout.kinds[i]) or len(lines[i].text) < 2 or lines[i].text[0] == "-":
            continue
        scan_python_triple_line(lines[i].text[1:], state)
    return state[0]


def python_line_on_side(
    lines: list[SourceLine], layout: DiffLayout, line: int, side: str
) -> bool:
    if not is_hunk_source(layout.kinds[line]) or len(lines[line].text) < 2:
        return False
    return lines[line].text[0] == " " or lines[line].text[0] == side


def python_code_without_strings(text: str) -> str:
    parts: list[str] = []
    i = 0
    while i < len(text):
        if text[i] == "#":
            break
        if text.startswith("'''", i) or text.startswith('"""', i):
            break
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
        parts.append(text[i])
        i += 1
    return "".join(parts)


def simple_assigned_reference(body: str) -> tuple[str, bool]:
    trimmed = body.strip()
    eq = trimmed.find("=")
    if eq <= 0 or (eq + 1 < len(trimmed) and trimmed[eq + 1] == "="):
        return "", False
    lhs = trimmed[:eq].strip()
    colon = lhs.find(":")
    if colon >= 0:
        lhs = lhs[:colon].strip()
    if not lhs:
        return "", False
    for segment in lhs.split("."):
        if not segment or not is_identifier_start(segment[0]):
            return "", False
        for j in range(1, len(segment)):
            if not is_identifier_continue(segment[j]):
                return "", False
    return lhs, True


def contains_identifier(text: str, name: str) -> bool:
    offset = 0
    while offset <= len(text) - len(name):
        at = text.find(name, offset)
        if at < 0:
            return False
        before_ok = at == 0 or not is_identifier_continue(text[at - 1])
        after = at + len(name)
        after_ok = after == len(text) or not is_identifier_continue(text[after])
        if before_ok and after_ok:
            return True
        offset = at + 1
    return False


def hunk_has_visible_change(
    layout: DiffLayout, state: PlanState, start: int, end: int
) -> bool:
    for i in range(start, end):
        if layout.kinds[i] == DiffLineKind.HUNK_CHANGE and state.represented(i):
            return True
    return False


def python_suite_header_end(
    lines: list[SourceLine],
    layout: DiffLayout,
    state: PlanState | None,
    start: int,
) -> tuple[int, bool]:
    _, hunk_end = containing_hunk(layout, start)
    depth = 0
    for i in range(start, hunk_end):
        if state is not None:
            if state.fold_at[i] >= 0:
                continue
            if state.hidden[i]:
                continue
        if not is_hunk_source(layout.kinds[i]) or len(lines[i].text) < 2 or lines[i].text[0] == "-":
            continue
        body = lines[i].text[1:]
        trimmed = trim_python_code(body)
        if trimmed == "":
            continue
        depth += python_delimiter_depth(body)
        if depth < 0:
            return 0, False
        if depth == 0 and trimmed.endswith(":"):
            return i, True
    return 0, False


def has_python_body_after(
    lines: list[SourceLine],
    layout: DiffLayout,
    state: PlanState | None,
    owner_line: int,
    indent: int,
) -> bool:
    _, hunk_end = containing_hunk(layout, owner_line)
    for i in range(owner_line + 1, hunk_end):
        if state is not None:
            fold_index = state.fold_at[i]
            if fold_index >= 0:
                fold = state.folds[fold_index]
                if fold.marker == "-":
                    continue
                return (fold.marker in ("+", " ")) and len(fold.indent) > indent
            if state.hidden[i]:
                continue
        if not is_hunk_source(layout.kinds[i]) or len(lines[i].text) < 2 or lines[i].text[0] == "-":
            continue
        body = lines[i].text[1:]
        if trim_python_code(body) == "":
            continue
        return len(leading_whitespace(body)) > indent
    return False


def has_python_definition_after(
    lines: list[SourceLine],
    layout: DiffLayout,
    state: PlanState | None,
    decorator_line: int,
    indent: int,
) -> bool:
    _, hunk_end = containing_hunk(layout, decorator_line)
    depth = python_delimiter_depth(lines[decorator_line].text[1:])
    for i in range(decorator_line + 1, hunk_end):
        if state is not None:
            if state.fold_at[i] >= 0:
                continue
            if state.hidden[i]:
                continue
        if not is_hunk_source(layout.kinds[i]) or len(lines[i].text) < 2 or lines[i].text[0] == "-":
            continue
        body = lines[i].text[1:]
        trimmed = trim_python_code(body)
        if trimmed == "":
            continue
        if depth > 0:
            depth += python_delimiter_depth(body)
            if depth < 0:
                return False
            continue
        if len(leading_whitespace(body)) != indent:
            return False
        if trimmed.startswith("@"):
            depth = python_delimiter_depth(body)
            continue
        return is_python_definition(trimmed)
    return False


def apply_planned_replacements(
    body: str, edits: list[PlannedReplacement]
) -> str:
    for e in reversed(edits):
        body = body[: e.start] + e.replacement.new + body[e.end :]
    return body


def validate_hidden_python_owners(
    lines: list[SourceLine], layout: DiffLayout, state: PlanState
) -> list[str]:
    problems: list[str] = []
    for i, line in enumerate(lines):
        if (
            not state.hidden[i]
            or not layout.python[i]
            or not is_hunk_source(layout.kinds[i])
            or len(line.text) < 2
            or line.text[0] == "-"
        ):
            continue
        if python_triple_state_before_line(lines, layout, i) != PythonTripleState.NONE:
            continue
        body = line.text[1:]
        trimmed = trim_python_code(body)
        indent = len(leading_whitespace(body))
        if trimmed.startswith("@"):
            if (
                has_python_definition_after(lines, layout, None, i, indent)
                and has_python_definition_after(lines, layout, state, i, indent)
            ):
                problems.append(
                    f"remove/fold: hides Python decorator on line {i + 1} while its "
                    "definition remains visible"
                )
        elif is_python_suite_header_start(trimmed):
            raw_end, ok = python_suite_header_end(lines, layout, None, i)
            if (
                ok
                and has_python_body_after(lines, layout, None, raw_end, indent)
                and has_python_body_after(lines, layout, state, raw_end, indent)
            ):
                problems.append(
                    f"remove/fold: hides Python suite owner on line {i + 1} while its "
                    "body remains visible"
                )
    return problems


def hidden_python_region_balanced(
    lines: list[SourceLine],
    layout: DiffLayout,
    hunk_start: int,
    start: int,
    end: int,
    side: str,
) -> bool:
    before_triple = [PythonTripleState.NONE]
    for i in range(hunk_start, start):
        if python_line_on_side(lines, layout, i, side):
            scan_python_triple_line(lines[i].text[1:], before_triple)
    entered_triple = before_triple[0] != PythonTripleState.NONE
    actual_triple = [before_triple[0]]
    local_triple = [PythonTripleState.NONE]
    triple_transitions = 0
    bodies: list[str] = []
    for i in range(start, end):
        if not python_line_on_side(lines, layout, i, side):
            continue
        body = lines[i].text[1:]
        bodies.append(body)
        scan_python_triple_line(body, local_triple)
        if entered_triple:
            triple_transitions += scan_python_triple_line(body, actual_triple)
    if not bodies:
        return True
    trimmed_first = bodies[0].strip()
    starts_with_bare_triple = trimmed_first in ('"""', "'''")
    if entered_triple and triple_transitions > 0 and (
        local_triple[0] != PythonTripleState.NONE or starts_with_bare_triple
    ):
        return False
    if not entered_triple and local_triple[0] != PythonTripleState.NONE:
        return False

    delimiter_triple = [PythonTripleState.NONE]
    if entered_triple and triple_transitions == 0:
        delimiter_triple[0] = before_triple[0]
    balance = PythonDelimiters()
    for body in bodies:
        balance = balance.add(python_delimiter_balance_with_state(body, delimiter_triple))
        if balance.round < 0 or balance.square < 0 or balance.curly < 0:
            return False
    return balance == PythonDelimiters()


def validate_hidden_python_boundaries(
    lines: list[SourceLine], layout: DiffLayout, state: PlanState
) -> list[str]:
    problems: list[str] = []
    for hunk, kind in enumerate(layout.kinds):
        if kind != DiffLineKind.HUNK_HEADER or not layout.python[hunk]:
            continue
        end = next_layout_line(layout, hunk + 1, _HUNK_STOP)
        if not hunk_has_visible_change(layout, state, hunk + 1, end):
            continue
        i = hunk + 1
        while i < end:
            if not state.hidden[i] or not is_hunk_source(layout.kinds[i]):
                i += 1
                continue
            start = i
            while i < end and state.hidden[i] and is_hunk_source(layout.kinds[i]):
                i += 1
            for side in ("-", "+"):
                if not hidden_python_region_balanced(
                    lines, layout, hunk + 1, start, i, side
                ):
                    side_name = "old" if side == "-" else "new"
                    problems.append(
                        f"remove/fold: hidden Python region {start + 1}-{i} crosses "
                        f"{side_name}-side expression or string boundaries; keep the "
                        "boundaries and compress only their interior"
                    )
    return problems


def python_new_side_states(
    lines: list[SourceLine], layout: DiffLayout
) -> tuple[list[bool], list[int]]:
    inside_triple = [False] * len(lines)
    depth_before = [0] * len(lines)
    for hunk, kind in enumerate(layout.kinds):
        if kind != DiffLineKind.HUNK_HEADER or not layout.python[hunk]:
            continue
        end = next_layout_line(layout, hunk + 1, _HUNK_STOP)
        triple = [PythonTripleState.NONE]
        delimiters = PythonDelimiters()
        for i in range(hunk + 1, end):
            if (
                not is_hunk_source(layout.kinds[i])
                or len(lines[i].text) < 2
                or lines[i].text[0] == "-"
            ):
                continue
            inside_triple[i] = triple[0] != PythonTripleState.NONE
            depth_before[i] = delimiters.round + delimiters.square + delimiters.curly
            delimiters = delimiters.add(
                python_delimiter_balance_with_state(lines[i].text[1:], triple)
            )
            if delimiters.round < 0:
                delimiters = PythonDelimiters(
                    round=0, square=delimiters.square, curly=delimiters.curly
                )
            if delimiters.square < 0:
                delimiters = PythonDelimiters(
                    round=delimiters.round, square=0, curly=delimiters.curly
                )
            if delimiters.curly < 0:
                delimiters = PythonDelimiters(
                    round=delimiters.round, square=delimiters.square, curly=0
                )
    return inside_triple, depth_before


def validate_hidden_references(
    lines: list[SourceLine], layout: DiffLayout, state: PlanState
) -> list[str]:
    inside_triple, depth_before = python_new_side_states(lines, layout)
    problems: list[str] = []
    for i, line in enumerate(lines):
        if (
            not state.hidden[i]
            or not layout.python[i]
            or not is_hunk_source(layout.kinds[i])
            or len(line.text) < 2
            or line.text[0] == "-"
        ):
            continue
        if inside_triple[i] or depth_before[i] != 0:
            continue
        name, ok = simple_assigned_reference(python_code_without_strings(line.text[1:]))
        if not ok:
            continue
        file_id = layout.file_id[i]
        for j in range(len(lines)):
            if (
                layout.file_id[j] != file_id
                or state.hidden[j]
                or not is_hunk_source(layout.kinds[j])
                or len(lines[j].text) < 2
            ):
                continue
            if line.text[0] == "+" and lines[j].text[0] == "-":
                continue
            if inside_triple[j]:
                continue
            body = python_code_without_strings(lines[j].text[1:])
            if not contains_identifier(body, name):
                continue
            fold_index = state.folded[i]
            if fold_index >= 0:
                problems.append(
                    f"fold[{fold_index}]: hides definition {name!r} on line {i + 1} "
                    f"while retained line {j + 1} still references it; keep the "
                    "definition and fold only its interior"
                )
            else:
                problems.append(
                    f"remove: hides definition {name!r} on line {i + 1} while retained "
                    f"line {j + 1} still references it; keep the definition and "
                    "compress only its interior"
                )
            break
    return problems


def validate_python_suite_skeleton(
    lines: list[SourceLine], layout: DiffLayout, state: PlanState
) -> list[str]:
    problems: list[str] = []
    for i, line in enumerate(lines):
        if (
            not layout.python[i]
            or state.hidden[i]
            or not is_hunk_source(layout.kinds[i])
            or len(line.text) < 2
            or line.text[0] == "-"
        ):
            continue
        if python_triple_state_before_line(lines, layout, i) != PythonTripleState.NONE:
            continue
        body = line.text[1:]
        trimmed = trim_python_code(body)
        if trimmed.startswith("@"):
            indent = len(leading_whitespace(body))
            if (
                has_python_definition_after(lines, layout, None, i, indent)
                and not has_python_definition_after(lines, layout, state, i, indent)
            ):
                problems.append(
                    f"remove/fold: retained Python decorator on line {i + 1} has no "
                    "attached definition"
                )
            continue
        if not is_python_suite_header_start(trimmed):
            continue
        raw_end, raw_ok = python_suite_header_end(lines, layout, None, i)
        if not raw_ok:
            continue
        owner_indent = len(leading_whitespace(body))
        if has_python_body_after(lines, layout, None, raw_end, owner_indent):
            retained_end, retained_ok = python_suite_header_end(lines, layout, state, i)
            if not retained_ok or not has_python_body_after(
                lines, layout, state, retained_end, owner_indent
            ):
                problems.append(
                    f"remove/fold: retained Python suite owner on line {i + 1} has no "
                    "indented body; keep a semantic body line or an interior fold"
                )
    return problems


def validate_triple_quote_parity(
    lines: list[SourceLine],
    layout: DiffLayout,
    state: PlanState,
    replacements: dict[int, list[PlannedReplacement]],
) -> list[str]:
    problems: list[str] = []
    for i, kind in enumerate(layout.kinds):
        if kind != DiffLineKind.HUNK_HEADER or not layout.python[i]:
            continue
        end = next_layout_line(layout, i + 1, _HUNK_STOP)
        if not hunk_has_visible_change(layout, state, i + 1, end):
            continue
        raw_old = [PythonTripleState.NONE]
        raw_new = [PythonTripleState.NONE]
        kept_old = [PythonTripleState.NONE]
        kept_new = [PythonTripleState.NONE]
        for j in range(i + 1, end):
            if not is_hunk_source(layout.kinds[j]) or len(lines[j].text) < 1:
                continue
            body = lines[j].text[1:]
            kept_body = body
            edits = replacements.get(j + 1)
            if edits:
                kept_body = apply_planned_replacements(body, edits)
            marker = lines[j].text[0]
            if marker == " ":
                scan_python_triple_line(body, raw_old)
                scan_python_triple_line(body, raw_new)
                if not state.hidden[j]:
                    scan_python_triple_line(kept_body, kept_old)
                    scan_python_triple_line(kept_body, kept_new)
            elif marker == "-":
                scan_python_triple_line(body, raw_old)
                if not state.hidden[j]:
                    scan_python_triple_line(kept_body, kept_old)
            elif marker == "+":
                scan_python_triple_line(body, raw_new)
                if not state.hidden[j]:
                    scan_python_triple_line(kept_body, kept_new)
        if raw_old[0] != kept_old[0] or raw_new[0] != kept_new[0]:
            problems.append(
                f"remove/fold: hunk on line {i + 1} must preserve balanced Python "
                "triple-quote boundaries; fold or remove the complete string, or "
                "keep both boundaries"
            )
    return problems


def validate_python_delimiter_balance(
    lines: list[SourceLine],
    layout: DiffLayout,
    state: PlanState,
    replacements: dict[int, list[PlannedReplacement]],
) -> list[str]:
    problems: list[str] = []
    for i, kind in enumerate(layout.kinds):
        if kind != DiffLineKind.HUNK_HEADER or not layout.python[i]:
            continue
        end = next_layout_line(layout, i + 1, _HUNK_STOP)
        if not hunk_has_visible_change(layout, state, i + 1, end):
            continue
        raw_old = PythonDelimiters()
        raw_new = PythonDelimiters()
        kept_old = PythonDelimiters()
        kept_new = PythonDelimiters()
        raw_old_triple = [PythonTripleState.NONE]
        raw_new_triple = [PythonTripleState.NONE]
        kept_old_triple = [PythonTripleState.NONE]
        kept_new_triple = [PythonTripleState.NONE]
        for j in range(i + 1, end):
            if not is_hunk_source(layout.kinds[j]) or len(lines[j].text) < 1:
                continue
            body = lines[j].text[1:]
            kept_body = body
            edits = replacements.get(j + 1)
            if edits:
                kept_body = apply_planned_replacements(body, edits)
            marker = lines[j].text[0]
            if marker == " ":
                raw_old = raw_old.add(
                    python_delimiter_balance_with_state(body, raw_old_triple)
                )
                raw_new = raw_new.add(
                    python_delimiter_balance_with_state(body, raw_new_triple)
                )
                if not state.hidden[j]:
                    kept_old = kept_old.add(
                        python_delimiter_balance_with_state(kept_body, kept_old_triple)
                    )
                    kept_new = kept_new.add(
                        python_delimiter_balance_with_state(kept_body, kept_new_triple)
                    )
            elif marker == "-":
                raw_old = raw_old.add(
                    python_delimiter_balance_with_state(body, raw_old_triple)
                )
                if not state.hidden[j]:
                    kept_old = kept_old.add(
                        python_delimiter_balance_with_state(kept_body, kept_old_triple)
                    )
            elif marker == "+":
                raw_new = raw_new.add(
                    python_delimiter_balance_with_state(body, raw_new_triple)
                )
                if not state.hidden[j]:
                    kept_new = kept_new.add(
                        python_delimiter_balance_with_state(kept_body, kept_new_triple)
                    )
        if raw_old != kept_old or raw_new != kept_new:
            problems.append(
                f"remove/fold: hunk on line {i + 1} must preserve Python (), [], "
                "and {} delimiter balance; keep both boundaries or fold/remove "
                "the complete balanced expression"
            )
    return problems


def ends_python_backslash(body: str) -> bool:
    code = trim_python_code(body)
    count = 0
    for ch in reversed(code):
        if ch != "\\":
            break
        count += 1
    return count % 2 == 1


def validate_python_backslash_continuations(
    lines: list[SourceLine],
    layout: DiffLayout,
    state: PlanState,
    replacements: dict[int, list[PlannedReplacement]],
) -> list[str]:
    problems: list[str] = []
    for hunk, kind in enumerate(layout.kinds):
        if kind != DiffLineKind.HUNK_HEADER or not layout.python[hunk]:
            continue
        end = next_layout_line(layout, hunk + 1, _HUNK_STOP)
        if not hunk_has_visible_change(layout, state, hunk + 1, end):
            continue
        for side in ("-", "+"):
            side_lines = [
                i
                for i in range(hunk + 1, end)
                if python_line_on_side(lines, layout, i, side)
            ]
            triple = [PythonTripleState.NONE]
            idx = 0
            while idx + 1 < len(side_lines):
                line = side_lines[idx]
                nxt = side_lines[idx + 1]
                body = lines[line].text[1:]
                inside_triple = triple[0] != PythonTripleState.NONE
                scan_python_triple_line(body, triple)
                if inside_triple or not ends_python_backslash(body):
                    idx += 1
                    continue
                line_hidden = state.hidden[line]
                next_hidden = state.hidden[nxt]
                if not line_hidden:
                    kept_body = body
                    edits = replacements.get(line + 1)
                    if edits:
                        kept_body = apply_planned_replacements(body, edits)
                    if not ends_python_backslash(kept_body):
                        idx += 1
                        continue
                if line_hidden != next_hidden:
                    problems.append(
                        f"remove/fold: Python backslash continuation on lines "
                        f"{line + 1}-{nxt + 1} must be retained or hidden together"
                    )
                idx += 1
    return problems


def state_with_mandatory_imports_represented(
    state: PlanState, mandatory: list[bool], layout: DiffLayout
) -> PlanState:
    from meat_python_plus.editplan import PlanState as EditPlanState

    validation = EditPlanState(
        hidden=list(state.hidden),
        folded=list(state.folded),
        fold_at=list(state.fold_at),
        folds=list(state.folds),
    )
    for hunk, kind in enumerate(layout.kinds):
        if kind != DiffLineKind.HUNK_HEADER:
            continue
        end = next_layout_line(layout, hunk + 1, _HUNK_STOP)
        have_visible_non_import = any(
            is_hunk_source(layout.kinds[i])
            and not mandatory[i]
            and state.represented(i)
            for i in range(hunk + 1, end)
        )
        if not have_visible_non_import:
            continue
        for i in range(hunk + 1, end):
            if not mandatory[i]:
                continue
            validation.hidden[i] = False
            validation.folded[i] = -1
            validation.fold_at[i] = -1
    return validation


def add_mandatory_python_suite_placeholders(
    lines: list[SourceLine],
    layout: DiffLayout,
    state: PlanState,
    mandatory: list[bool],
) -> None:
    from meat_python_plus.editplan import LineFold, PlannedFold

    for owner, line in enumerate(lines):
        if (
            not layout.python[owner]
            or state.hidden[owner]
            or not is_hunk_source(layout.kinds[owner])
            or len(line.text) < 2
            or line.text[0] == "-"
        ):
            continue
        if python_triple_state_before_line(lines, layout, owner) != PythonTripleState.NONE:
            continue
        body = line.text[1:]
        trimmed = trim_python_code(body)
        if not is_python_suite_header_start(trimmed):
            continue
        header_end, ok = python_suite_header_end(lines, layout, None, owner)
        if not ok:
            continue
        owner_indent = len(leading_whitespace(body))
        if not has_python_body_after(
            lines, layout, None, header_end, owner_indent
        ) or has_python_body_after(lines, layout, state, header_end, owner_indent):
            continue
        _, hunk_end = containing_hunk(layout, owner)
        for i in range(header_end + 1, hunk_end):
            if (
                not mandatory[i]
                or not state.hidden[i]
                or not is_hunk_source(layout.kinds[i])
                or len(lines[i].text) < 2
                or lines[i].text[0] == "-"
            ):
                continue
            candidate_body = lines[i].text[1:]
            if (
                trim_python_code(candidate_body) == ""
                or len(leading_whitespace(candidate_body)) <= owner_indent
            ):
                continue
            fold_index = len(state.folds)
            state.folds.append(
                PlannedFold(
                    fold=LineFold(start_line=i + 1, end_line=i + 1),
                    plan_index=-1,
                    marker=lines[i].text[0],
                    indent=leading_whitespace(candidate_body),
                    eol=lines[i].eol,
                )
            )
            state.fold_at[i] = fold_index
            state.folded[i] = fold_index
            break
