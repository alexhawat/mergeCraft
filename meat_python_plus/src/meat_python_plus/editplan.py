"""Compile a model-submitted remove/replace/fold plan against an immutable diff."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from meat_python_plus.diffutil import (
    DiffLayout,
    DiffLineKind,
    SourceLine,
    analyze_diff,
    is_hunk_source,
    next_layout_line,
    split_source_lines,
    validate_supported_diff_lines,
)
from meat_python_plus.imports import (
    complete_mandatory_import_framing,
    mandatory_import_removal_plan,
    mandatory_removal_mask,
)

MAX_REPLACEMENT_BYTES = 4 << 10
MAX_SUMMARY_BYTES = 500


@dataclass
class LineRange:
    start_line: int
    end_line: int


@dataclass
class LineReplacement:
    line: int
    old: str
    new: str


@dataclass
class LineFold:
    start_line: int
    end_line: int


@dataclass
class EditPlan:
    remove: list[LineRange] = field(default_factory=list)
    replace: list[LineReplacement] = field(default_factory=list)
    fold: list[LineFold] = field(default_factory=list)


@dataclass
class Submission(EditPlan):
    summary: str = ""


@dataclass
class PlannedReplacement:
    replacement: LineReplacement
    plan_index: int
    start: int
    end: int


@dataclass
class PlannedFold:
    fold: LineFold
    plan_index: int
    marker: str
    indent: str
    eol: str


@dataclass
class PlanState:
    hidden: list[bool]
    folded: list[int]
    fold_at: list[int]
    folds: list[PlannedFold] = field(default_factory=list)

    def represented(self, line: int) -> bool:
        return (not self.hidden[line]) or self.folded[line] >= 0


@dataclass
class PlanStats:
    raw_changed: int = 0
    visible_changed: int = 0
    removed_changed: int = 0
    folded_changed: int = 0
    fold_count: int = 0
    raw_files: int = 0
    visible_files: int = 0


@dataclass
class CompiledPlan:
    smart_diff: str
    stats: PlanStats
    moves: list[Any] = field(default_factory=list)


@dataclass
class DetectedMove:
    removed: LineRange
    added: LineRange


def parse_edit_plan(data: dict[str, Any]) -> EditPlan:
    return EditPlan(
        remove=[LineRange(**r) for r in (data.get("remove") or [])],
        replace=[LineReplacement(**r) for r in (data.get("replace") or [])],
        fold=[LineFold(**r) for r in (data.get("fold") or [])],
    )


def parse_submission(data: dict[str, Any]) -> Submission:
    plan = parse_edit_plan(data)
    return Submission(
        remove=plan.remove,
        replace=plan.replace,
        fold=plan.fold,
        summary=str(data.get("summary") or ""),
    )


def join_errors(problems: list[str]) -> str:
    if len(problems) == 1:
        return problems[0]
    return "edit plan has %d errors:\n- %s" % (len(problems), "\n- ".join(problems))


def leading_whitespace(s: str) -> str:
    i = 0
    while i < len(s) and s[i] in " \t":
        i += 1
    return s[:i]


def common_prefix(a: str, b: str) -> str:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return a[:i]


def unique_substring_index(text: str, sub: str) -> tuple[int, bool]:
    first = text.find(sub)
    if first < 0:
        return 0, False
    if text.find(sub, first + 1) >= 0:
        return 0, False
    return first, True


def compile_elision_projection(new: str, strict: bool = True) -> re.Pattern[str] | None:
    pattern_parts: list[str] = ["^"]
    literal: list[str] = []
    wildcards = 0
    last_was_wildcard = False
    runes = list(new)
    i = 0

    def flush_literal() -> None:
        if literal:
            pattern_parts.append(re.escape("".join(literal)))
            literal.clear()

    while i < len(runes):
        wildcard = False
        if runes[i] == "…":
            wildcard = True
            i += 1
        elif runes[i] == ".":
            j = i
            while j < len(runes) and runes[j] == ".":
                j += 1
            run = j - i
            if run >= 3:
                if strict and run != 3:
                    return None
                wildcard = True
                i = j
        if wildcard:
            if last_was_wildcard:
                if strict:
                    return None
                continue
            flush_literal()
            pattern_parts.append(".+")
            wildcards += 1
            last_was_wildcard = True
            continue
        literal.append(runes[i])
        last_was_wildcard = False
        i += 1
    flush_literal()
    pattern_parts.append("$")
    if wildcards == 0:
        return None
    try:
        return re.compile("".join(pattern_parts))
    except re.error:
        return None


def is_elision_projection(old: str, new: str) -> bool:
    compiled = compile_elision_projection(new, strict=True)
    return compiled is not None and compiled.match(old) is not None


def validate_single_line_text(name: str, text: str, max_bytes: int) -> str | None:
    encoded = text.encode("utf-8")
    if len(encoded) > max_bytes:
        return f"{name} is {len(encoded)} bytes, over the {max_bytes}-byte limit"
    for ch in text:
        if ch in "\n\r\x00\x1b\u2028\u2029":
            return f"{name} must be a single printable line"
        if ord(ch) < 32 and ch != "\t":
            return f"{name} contains a control character"
    return None


def validate_summary(summary: str) -> str | None:
    if not summary.strip():
        return "summary must not be empty"
    return validate_single_line_text("summary", summary, MAX_SUMMARY_BYTES)


def prepare_fold(
    lines: list[SourceLine],
    layout: DiffLayout,
    fold: LineFold,
    plan_index: int,
) -> PlannedFold:
    if fold.start_line < 1 or fold.end_line < 1 or fold.start_line >= fold.end_line:
        raise ValueError(
            f"fold[{plan_index}]: want at least two lines in an inclusive range, "
            f"got {fold.start_line}-{fold.end_line}"
        )
    if fold.end_line > len(lines):
        raise ValueError(
            f"fold[{plan_index}]: line {fold.end_line} is past end of diff "
            f"({len(lines)} lines)"
        )

    marker = ""
    indent = ""
    have_indent = False
    for n in range(fold.start_line, fold.end_line + 1):
        index = n - 1
        if not is_hunk_source(layout.kinds[index]) or not lines[index].text:
            raise ValueError(
                f"fold[{plan_index}]: line {n} is not source inside one diff hunk"
            )
        line_marker = lines[index].text[0]
        if not marker:
            marker = line_marker
        elif marker != line_marker:
            raise ValueError(
                f"fold[{plan_index}]: mixed diff markers {marker!r} and "
                f"{line_marker!r} in range {fold.start_line}-{fold.end_line}"
            )
        body = lines[index].text[1:]
        trimmed_body = body.strip()
        if (
            layout.python[index]
            and python_triple_state_before_line(lines, layout, index)
            == PythonTripleState.NONE
            and marker != "-"
            and (
                trimmed_body.startswith("@")
                or is_python_suite_header_start(trimmed_body)
            )
        ):
            raise ValueError(
                f"fold[{plan_index}]: line {n} is a Python decorator or suite owner; "
                "keep the anchor and fold only its indented interior"
            )
        if not body.strip():
            continue
        line_indent = leading_whitespace(body)
        if not have_indent:
            indent = line_indent
            have_indent = True
        else:
            indent = common_prefix(indent, line_indent)
    if not have_indent:
        raise ValueError(
            f"fold[{plan_index}]: range {fold.start_line}-{fold.end_line} "
            "contains only blank source lines"
        )
    return PlannedFold(
        fold=fold,
        plan_index=plan_index,
        marker=marker,
        indent=indent,
        eol=lines[fold.end_line - 1].eol,
    )


def compute_plan_stats(layout: DiffLayout, state: PlanState) -> PlanStats:
    stats = PlanStats()
    for i, kind in enumerate(layout.kinds):
        if kind == DiffLineKind.HEADER:
            stats.raw_files += 1
            if state.represented(i):
                stats.visible_files += 1
        elif kind == DiffLineKind.HUNK_CHANGE:
            stats.raw_changed += 1
            if state.folded[i] >= 0:
                stats.folded_changed += 1
            elif state.hidden[i]:
                stats.removed_changed += 1
            else:
                stats.visible_changed += 1
    stats.fold_count = len(state.folds)
    for fold in state.folds:
        if fold.marker in "+-":
            stats.visible_changed += 1
    return stats


def validate_retained_structure(layout: DiffLayout, state: PlanState) -> list[str]:
    problems: list[str] = []
    stop_file = {
        DiffLineKind.HEADER,
        DiffLineKind.MAIL_SIGNATURE,
    }
    stop_old = {
        DiffLineKind.HEADER,
        DiffLineKind.OLD_FILE,
        DiffLineKind.MAIL_SIGNATURE,
    }
    stop_hunk = {
        DiffLineKind.HEADER,
        DiffLineKind.OLD_FILE,
        DiffLineKind.HUNK_HEADER,
        DiffLineKind.MAIL_SIGNATURE,
    }

    def any_retained(start: int, end: int) -> bool:
        return any(state.represented(i) for i in range(start, end))

    def any_retained_meaningful(start: int, end: int) -> bool:
        for i in range(start, end):
            if state.represented(i) and layout.kinds[i] not in (
                DiffLineKind.NO_NEWLINE,
                DiffLineKind.INDEX,
            ):
                return True
        return False

    def any_retained_hunk_source(start: int, end: int) -> bool:
        return any(
            state.represented(i) and is_hunk_source(layout.kinds[i])
            for i in range(start, end)
        )

    def any_retained_hunk_change(start: int, end: int) -> bool:
        return any(
            state.represented(i) and layout.kinds[i] == DiffLineKind.HUNK_CHANGE
            for i in range(start, end)
        )

    for i, kind in enumerate(layout.kinds):
        if kind == DiffLineKind.NO_NEWLINE and state.represented(i):
            owner = layout.marker_owner[i]
            if owner < 0 or not state.represented(owner):
                problems.append(
                    f"remove: no-newline marker on line {i + 1} requires its source line"
                )

        if kind == DiffLineKind.HEADER:
            end = next_layout_line(layout, i + 1, stop_file)
            body_retained = any_retained_meaningful(i + 1, end)
            header_retained = state.represented(i)
            if not body_retained and any_retained(i + 1, end):
                problems.append(
                    f"remove: file beginning on line {i + 1} retains only metadata; "
                    "remove the complete file section"
                )
            if header_retained != body_retained:
                problems.append(
                    f"remove: diff header on line {i + 1} must be retained exactly "
                    "when its file body is retained"
                )
        elif kind == DiffLineKind.OLD_FILE:
            end = next_layout_line(layout, i + 2, stop_old)
            if state.represented(i) != state.represented(i + 1):
                problems.append(
                    f"remove: ---/+++ headers on lines {i + 1}-{i + 2} must be "
                    "removed or retained together"
                )
            body_retained = any_retained_meaningful(i + 2, end)
            headers_retained = state.represented(i)
            if headers_retained != body_retained:
                problems.append(
                    f"remove: ---/+++ headers on lines {i + 1}-{i + 2} must be "
                    "retained exactly when their file body is retained"
                )
        elif kind == DiffLineKind.RENAME_FROM:
            if i + 1 >= len(layout.kinds) or layout.kinds[i + 1] != DiffLineKind.RENAME_TO:
                problems.append(
                    f"rename from metadata on line {i + 1} has no matching rename to line"
                )
            elif state.represented(i) != state.represented(i + 1):
                problems.append(
                    f"remove: rename metadata on lines {i + 1}-{i + 2} must be "
                    "removed or retained together"
                )
        elif kind == DiffLineKind.COPY_FROM:
            if i + 1 >= len(layout.kinds) or layout.kinds[i + 1] != DiffLineKind.COPY_TO:
                problems.append(
                    f"copy from metadata on line {i + 1} has no matching copy to line"
                )
            elif state.represented(i) != state.represented(i + 1):
                problems.append(
                    f"remove: copy metadata on lines {i + 1}-{i + 2} must be "
                    "removed or retained together"
                )
        elif kind == DiffLineKind.HUNK_HEADER:
            end = next_layout_line(layout, i + 1, stop_hunk)
            header_retained = state.represented(i)
            if any_retained_hunk_source(i + 1, end) and not header_retained:
                problems.append(
                    f"remove: retained context/change lines require hunk header "
                    f"on line {i + 1}"
                )
            change_retained = any_retained_hunk_change(i + 1, end)
            if header_retained != change_retained:
                problems.append(
                    f"remove: hunk header on line {i + 1} must be retained exactly "
                    "when its hunk has a retained change"
                )
    return problems


def compile_edit_plan(
    raw: str,
    plan: EditPlan,
    *,
    provided_moves: list[DetectedMove] | None = None,
    detect_moves: bool = True,
) -> CompiledPlan:
    problems: list[str] = []
    lines = split_source_lines(raw)
    validate_supported_diff_lines(lines)
    layout = analyze_diff(lines)
    if layout.problems:
        raise ValueError(join_errors(layout.problems))

    if detect_moves:
        moves = detect_exact_moves(lines, layout)
    else:
        moves = list(provided_moves or [])
    mandatory_ranges = mandatory_import_removal_plan(lines, layout)
    mandatory_hidden = mandatory_removal_mask(len(lines), mandatory_ranges)
    apply_mandatory_move_precedence(moves, mandatory_hidden)
    state = PlanState(
        hidden=list(mandatory_hidden),
        folded=[-1] * len(lines),
        fold_at=[-1] * len(lines),
    )
    model_removed = [False] * len(lines)
    removals_valid = True

    for i, r in enumerate(plan.remove):
        if r.start_line < 1 or r.end_line < 1 or r.start_line > r.end_line:
            problems.append(
                f"remove[{i}]: invalid inclusive range {r.start_line}-{r.end_line}"
            )
            removals_valid = False
            continue
        if r.end_line > len(lines):
            problems.append(
                f"remove[{i}]: line {r.end_line} is past end of diff ({len(lines)} lines)"
            )
            removals_valid = False
            continue
        first_overlap = 0
        for n in range(r.start_line, r.end_line + 1):
            if model_removed[n - 1]:
                if first_overlap == 0:
                    first_overlap = n
                removals_valid = False
                continue
            model_removed[n - 1] = True
            state.hidden[n - 1] = True
        if first_overlap:
            problems.append(f"remove[{i}]: overlaps an earlier range at line {first_overlap}")

    folds_valid = True
    for i, f in enumerate(plan.fold):
        try:
            prepared = prepare_fold(lines, layout, f, i)
        except ValueError as e:
            problems.append(str(e))
            folds_valid = False
            continue
        mandatory_lines = sum(
            1 for n in range(f.start_line, f.end_line + 1) if mandatory_hidden[n - 1]
        )
        if mandatory_lines > 0:
            if mandatory_lines != f.end_line - f.start_line + 1:
                problems.append(
                    f"fold[{i}]: crosses automatically removed import rows and "
                    f"behavioral rows in range {f.start_line}-{f.end_line}; "
                    "fold only the behavioral rows"
                )
                folds_valid = False
            continue
        conflict_line = 0
        for n in range(f.start_line, f.end_line + 1):
            if state.hidden[n - 1]:
                conflict_line = n
                break
        if conflict_line:
            kind = "fold" if state.folded[conflict_line - 1] >= 0 else "remove"
            problems.append(f"fold[{i}]: overlaps {kind} at line {conflict_line}")
            folds_valid = False
            continue
        fold_index = len(state.folds)
        state.folds.append(prepared)
        state.fold_at[f.start_line - 1] = fold_index
        for n in range(f.start_line, f.end_line + 1):
            state.hidden[n - 1] = True
            state.folded[n - 1] = fold_index

    if removals_valid and folds_valid:
        add_mandatory_python_suite_placeholders(lines, layout, state, mandatory_hidden)
        problems.extend(validate_move_symmetry(moves, state, mandatory_hidden))

    python_validation_state = state
    if removals_valid and folds_valid:
        python_validation_state = state_with_mandatory_imports_represented(
            state, mandatory_hidden, layout
        )
        problems.extend(
            validate_hidden_python_owners(lines, layout, python_validation_state)
        )
        problems.extend(
            validate_hidden_python_boundaries(lines, layout, python_validation_state)
        )
        problems.extend(
            validate_hidden_references(lines, layout, python_validation_state)
        )
        problems.extend(
            validate_python_suite_skeleton(lines, layout, python_validation_state)
        )

    replacements: dict[int, list[PlannedReplacement]] = {}
    replacements_valid = True
    for i, r in enumerate(plan.replace):
        if r.line < 1 or r.line > len(lines):
            problems.append(
                f"replace[{i}]: line {r.line} is outside the diff (1-{len(lines)})"
            )
            continue
        if mandatory_hidden[r.line - 1]:
            continue
        if state.hidden[r.line - 1]:
            state_name = "folded" if state.folded[r.line - 1] >= 0 else "removed"
            problems.append(f"replace[{i}]: line {r.line} is also {state_name}")
            continue
        if r.old == "":
            problems.append(f"replace[{i}]: old must not be empty")
            continue
        err = validate_single_line_text("old", r.old, MAX_REPLACEMENT_BYTES)
        if err:
            problems.append(f"replace[{i}]: {err}")
            continue
        err = validate_single_line_text("new", r.new, MAX_REPLACEMENT_BYTES)
        if err:
            problems.append(f"replace[{i}]: {err}")
            continue
        if r.new == r.old:
            problems.append(f"replace[{i}]: new must elide some part of old")
            continue
        if not is_elision_projection(r.old, r.new):
            problems.append(
                f"replace[{i}]: new must match all of old, with every omitted "
                "span represented by ... or …"
            )
            continue
        if not is_hunk_source(layout.kinds[r.line - 1]):
            problems.append(
                f"replace[{i}]: line {r.line} is not a source line inside a diff hunk"
            )
            continue
        body = lines[r.line - 1].text[1:]
        if (
            layout.python[r.line - 1]
            and python_triple_state_before_line(lines, layout, r.line - 1)
            == PythonTripleState.NONE
        ):
            code = trim_python_code(body)
            if code.startswith("@") or is_python_suite_header_start(code):
                problems.append(
                    f"replace[{i}]: line {r.line} is a Python decorator or suite "
                    "header; keep structural anchors intact"
                )
                continue
        if layout.python[r.line - 1] and changes_python_boundary_tokens(r.old, r.new):
            problems.append(
                f"replace[{i}]: must preserve Python string and expression boundary tokens"
            )
            continue
        start, unique = unique_substring_index(body, r.old)
        if not unique:
            problems.append(
                f"replace[{i}]: old must occur exactly once after the diff marker "
                f"on line {r.line}"
            )
            continue
        replacements.setdefault(r.line, []).append(
            PlannedReplacement(
                replacement=r, plan_index=i, start=start, end=start + len(r.old)
            )
        )

    for line_no, edits in replacements.items():
        edits.sort(key=lambda e: e.start)
        for j in range(1, len(edits)):
            if edits[j].start < edits[j - 1].end:
                problems.append(
                    f"replace[{edits[j].plan_index}]: span overlaps "
                    f"replace[{edits[j - 1].plan_index}] on line {line_no}"
                )
                replacements_valid = False

    if removals_valid and folds_valid and replacements_valid and not problems:
        problems.extend(
            validate_move_replacement_symmetry(
                moves, lines, state, mandatory_hidden, replacements
            )
        )

    if removals_valid and folds_valid and replacements_valid:
        problems.extend(
            validate_triple_quote_parity(
                lines, layout, python_validation_state, replacements
            )
        )
        problems.extend(
            validate_python_delimiter_balance(
                lines, layout, python_validation_state, replacements
            )
        )
        problems.extend(
            validate_python_backslash_continuations(
                lines, layout, python_validation_state, replacements
            )
        )
        complete_mandatory_import_framing(layout, state, mandatory_hidden)
        problems.extend(validate_retained_structure(layout, state))

    if problems:
        raise ValueError(join_errors(problems))

    out: list[str] = []
    for i, line in enumerate(lines):
        line_no = i + 1
        fold_index = state.fold_at[i]
        if fold_index >= 0:
            fold = state.folds[fold_index]
            out.append(f"{fold.marker}{fold.indent}...{fold.eol}")
            continue
        if state.hidden[i]:
            continue
        text = line.text
        edits = replacements.get(line_no)
        if edits:
            body = text[1:]
            for e in reversed(edits):
                body = body[: e.start] + e.replacement.new + body[e.end :]
            text = text[0] + body
        out.append(text + line.eol)

    stats = compute_plan_stats(layout, state)
    return CompiledPlan(smart_diff="".join(out), stats=stats, moves=moves)


def compile_submission(
    raw: str,
    submission: Submission,
    *,
    provided_moves: list[DetectedMove] | None = None,
    detect_moves: bool = True,
) -> CompiledPlan:
    problems: list[str] = []
    err = validate_summary(submission.summary)
    if err:
        problems.append(err)
    try:
        compiled = compile_edit_plan(
            raw,
            submission,
            provided_moves=provided_moves,
            detect_moves=detect_moves,
        )
    except ValueError as e:
        problems.append(str(e))
        compiled = None  # type: ignore[assignment]
    if problems:
        raise ValueError(join_errors(problems))
    assert compiled is not None
    return compiled


def retention_pressure(stats: PlanStats) -> bool:
    if stats.raw_changed < 40 or stats.visible_changed < 20:
        return False
    return stats.visible_changed >= 80 or stats.visible_changed * 100 >= stats.raw_changed * 45


FEEDBACK_PRESSURE_HIGH = (
    "Pressure: high retention. Reconsider repeated rename/call-site hunks "
    "after one representative anchor, default git context, mechanical prose, "
    "duplicate setup/cases, and assertion batches or suites that can become "
    "fixed ... folds. Imports are already removed mechanically. For Python, "
    "keep each suite owner, required setup, and decisive stimulus/outcome: "
    "never hide a table assignment used by a retained loop, or an entire "
    "pytester.makeini/makeconftest configuration that defines the scenario. "
    "Move folds inside those boundaries. This is advisory: preserve every "
    "distinct contract, security or compatibility caveat, condition, "
    "lifecycle edge, transformation, effect, stimulus, and outcome.\n"
)


def plan_feedback(compiled: CompiledPlan) -> str:
    stats = compiled.stats
    percent = 0
    if stats.raw_changed > 0:
        percent = stats.visible_changed * 100 // stats.raw_changed
    parts = [
        f"Valid source-derived plan.\nRetention: {stats.visible_changed}/{stats.raw_changed} "
        f"visible changed rows ({percent}%); {stats.removed_changed} removed, "
        f"{stats.folded_changed} hidden by {stats.fold_count} folds"
    ]
    if stats.raw_files > 0:
        parts[0] += f"; files {stats.visible_files}/{stats.raw_files}"
    parts[0] += ".\n"
    if compiled.moves:
        parts.append(
            f"Moves: {len(compiled.moves)} exact cross-hunk/cross-file span(s) "
            f"treated symmetrically ({format_move_pairs(compiled.moves, MAX_MOVE_HINTS)}).\n"
        )
    if retention_pressure(stats):
        parts.append(FEEDBACK_PRESSURE_HIGH)
    else:
        parts.append("Pressure: acceptable. Preserve uncertain behavior.\n")
    parts.append("Preview (revised plans still use ORIGINAL line coordinates):\n")
    parts.append(compiled.smart_diff)
    return "".join(parts)


from meat_python_plus.moves import (  # noqa: E402
    MAX_MOVE_HINTS,
    apply_mandatory_move_precedence,
    detect_exact_moves,
    format_move_pairs,
    validate_move_replacement_symmetry,
    validate_move_symmetry,
)
from meat_python_plus.python_suites import (  # noqa: E402
    PythonTripleState,
    add_mandatory_python_suite_placeholders,
    changes_python_boundary_tokens,
    is_python_suite_header_start,
    python_triple_state_before_line,
    state_with_mandatory_imports_represented,
    validate_hidden_python_boundaries,
    validate_hidden_python_owners,
    validate_hidden_references,
    validate_python_backslash_continuations,
    validate_python_delimiter_balance,
    validate_python_suite_skeleton,
    validate_triple_quote_parity,
)
from meat_python_plus.imports import trim_python_code  # noqa: E402
