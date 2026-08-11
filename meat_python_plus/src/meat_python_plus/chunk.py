"""Rich diff chunking with move remapping (Go meat/chunk.go parity)."""

from __future__ import annotations

from dataclasses import dataclass, field

from meat_python_plus.diffutil import (
    DiffLayout,
    DiffLineKind,
    SourceLanguage,
    SourceLine,
    analyze_diff,
    is_hunk_source,
    numbered_diff,
    split_source_lines,
)
from meat_python_plus.editplan import DetectedMove, LineRange, PlannedFold, PlanState, join_errors
from meat_python_plus.imports import (
    PythonTripleState,
    count_code_backticks,
    mandatory_import_removal_plan,
    mandatory_removal_mask,
    scan_python_triple_line,
    trim_python_code,
)
from meat_python_plus.moves import apply_mandatory_move_precedence, detect_exact_moves
from meat_python_plus.python_suites import (
    PythonDelimiters,
    add_mandatory_python_suite_placeholders,
    ends_python_backslash,
    is_python_suite_header_start,
    python_delimiter_balance_with_state,
)

MAX_DIFF_BYTES = 400 << 10
MAX_TOTAL_DIFF_BYTES = 4 << 20
MAX_CHUNKS = 32


@dataclass
class DiffChunk:
    text: str
    meta_prefix: str = ""
    section_id: int = -1
    continuation: bool = False
    passthrough: bool = False
    origins: list[int] = field(default_factory=list)


@dataclass
class _LineSpan:
    start: int
    end: int


@dataclass
class _UnitInfo:
    text_len: int = 0
    raw_len: int = 0
    count: int = 0
    vis_old: int = 0
    vis_new: int = 0
    drop_old: int = 0
    drop_new: int = 0
    has_change: bool = False


@dataclass
class _StringScanState:
    triple: PythonTripleState = PythonTripleState.NONE
    backtick: bool = False
    brackets: PythonDelimiters = field(default_factory=PythonDelimiters)
    backslash: bool = False

    def in_string(self) -> bool:
        return (
            self.triple != PythonTripleState.NONE
            or self.backtick
            or self.backslash
            or self.brackets.round > 0
            or self.brackets.square > 0
            or self.brackets.curly > 0
        )

    def scan(self, text: str, language: SourceLanguage) -> None:
        if language in (SourceLanguage.PYTHON, SourceLanguage.JAVA):
            in_triple = self.triple != PythonTripleState.NONE
            if language == SourceLanguage.PYTHON:
                triple_for_balance = [self.triple]
                self.brackets = self.brackets.add(
                    python_delimiter_balance_with_state(text, triple_for_balance)
                )
                if self.brackets.round < 0:
                    self.brackets = PythonDelimiters(
                        round=0,
                        square=self.brackets.square,
                        curly=self.brackets.curly,
                    )
                if self.brackets.square < 0:
                    self.brackets = PythonDelimiters(
                        round=self.brackets.round,
                        square=0,
                        curly=self.brackets.curly,
                    )
                if self.brackets.curly < 0:
                    self.brackets = PythonDelimiters(
                        round=self.brackets.round,
                        square=self.brackets.square,
                        curly=0,
                    )
            scan_python_triple_line(text, [self.triple])
            if language == SourceLanguage.PYTHON:
                self.backslash = (
                    not in_triple
                    and self.triple == PythonTripleState.NONE
                    and ends_python_backslash(text)
                )
        if language in (SourceLanguage.GO, SourceLanguage.JAVASCRIPT):
            if count_code_backticks(text) % 2 == 1:
                self.backtick = not self.backtick


def numbered_len(text_len: int, count: int) -> int:
    if count == 0:
        return 0
    width = len(str(count))
    return text_len + count * (width + 2)


def fits_single_run(raw: str, budget: int = MAX_DIFF_BYTES) -> bool:
    if len(raw.encode("utf-8")) > budget:
        return False
    lines = split_source_lines(raw)
    text_len = sum(len(line.text) for line in lines)
    return numbered_len(text_len, len(lines)) <= budget


def string_interior_mask(lines: list[SourceLine], layout: DiffLayout) -> list[bool]:
    mask = [False] * len(lines)
    old = _StringScanState()
    new = _StringScanState()
    language = SourceLanguage.UNKNOWN
    for i, kind in enumerate(layout.kinds):
        if kind == DiffLineKind.HUNK_HEADER:
            language = layout.language[i]
            old = _StringScanState()
            new = _StringScanState()
            continue
        if language == SourceLanguage.UNKNOWN or not is_hunk_source(kind) or not lines[i].text:
            continue
        mask[i] = old.in_string() or new.in_string()
        body = lines[i].text[1:]
        prefix = lines[i].text[0]
        if prefix == "-":
            old.scan(body, language)
        elif prefix == "+":
            new.scan(body, language)
        else:
            old.scan(body, language)
            new.scan(body, language)
    return mask


class _ChunkBuilder:
    def __init__(
        self,
        lines: list[SourceLine],
        layout: DiffLayout,
        budget: int,
        hidden: list[bool],
        extra_hidden: list[bool],
        fold_at: list[int],
        folds: list[PlannedFold],
        in_string: list[bool],
    ) -> None:
        self.lines = lines
        self.layout = layout
        self.budget = budget
        self.hidden = hidden
        self.extra_hidden = extra_hidden
        self.fold_at = fold_at
        self.folds = folds
        self.in_string = in_string
        self.prefix_text = [0] * (len(lines) + 1)
        self.prefix_raw = [0] * (len(lines) + 1)
        for i, line in enumerate(lines):
            self.prefix_text[i + 1] = self.prefix_text[i] + len(line.text)
            self.prefix_raw[i + 1] = self.prefix_raw[i] + len(line.text) + len(line.eol)
        self.chunks: list[DiffChunk] = []

    def sections(self) -> list[_LineSpan]:
        spans: list[_LineSpan] = []
        for i in range(len(self.lines)):
            file_id = self.layout.file_id[i]
            if file_id < 0:
                continue
            if not spans:
                spans.append(_LineSpan(start=0, end=len(self.lines)))
            elif self.layout.file_id[i - 1] != file_id:
                spans[-1].end = i
                spans.append(_LineSpan(start=i, end=len(self.lines)))
        return spans

    def range_text(self, start: int, end: int) -> str:
        parts: list[str] = []
        for i in range(start, end):
            parts.append(self.lines[i].text + self.lines[i].eol)
        return "".join(parts)

    def range_origins(self, start: int, end: int) -> list[int]:
        return [i + 1 for i in range(start, end)]

    def span_sizes(self, start: int, end: int) -> tuple[int, int, int]:
        return (
            self.prefix_text[end] - self.prefix_text[start],
            self.prefix_raw[end] - self.prefix_raw[start],
            end - start,
        )

    def fits(self, text_len: int, raw_len: int, count: int) -> bool:
        return raw_len <= self.budget and numbered_len(text_len, count) <= self.budget

    def span_fits(self, start: int, end: int) -> bool:
        text_len, raw_len, count = self.span_sizes(start, end)
        return self.fits(text_len, raw_len, count)

    def add(self, chunk: DiffChunk) -> None:
        if len(self.chunks) >= MAX_CHUNKS:
            raise ValueError(
                f"diff splits into more than {MAX_CHUNKS} chunks — try a narrower range "
                "(a single commit, or per-file with `git diff -- | meat`)"
            )
        self.chunks.append(chunk)

    def span_has_extra_hidden(self, span: _LineSpan) -> bool:
        return any(self.extra_hidden[i] for i in range(span.start, span.end))

    def span_fully_hidden(self, span: _LineSpan) -> bool:
        if span.end <= span.start:
            return False
        return all(self.hidden[i] for i in range(span.start, span.end))

    def placeholder_row(self, i: int) -> tuple[str, str, bool]:
        fi = self.fold_at[i]
        if fi < 0:
            return "", "", False
        fold = self.folds[fi]
        return f"{fold.marker}{fold.indent}...", fold.eol, True

    def unit_stats(self, start: int, end: int) -> _UnitInfo:
        info = _UnitInfo()
        for i in range(start, end):
            uo = un = 0
            if is_hunk_source(self.layout.kinds[i]) and self.lines[i].text:
                prefix = self.lines[i].text[0]
                if prefix == " ":
                    uo = un = 1
                elif prefix == "-":
                    uo = 1
                elif prefix == "+":
                    un = 1
            if self.hidden[i]:
                text, eol, ok = self.placeholder_row(i)
                if ok:
                    info.vis_old += uo
                    info.vis_new += un
                    info.text_len += len(text)
                    info.raw_len += len(text) + len(eol)
                    info.count += 1
                    if self.layout.kinds[i] == DiffLineKind.HUNK_CHANGE:
                        info.has_change = True
                    continue
                info.drop_old += uo
                info.drop_new += un
                continue
            info.vis_old += uo
            info.vis_new += un
            info.text_len += len(self.lines[i].text)
            info.raw_len += len(self.lines[i].text) + len(self.lines[i].eol)
            info.count += 1
            if self.layout.kinds[i] == DiffLineKind.HUNK_CHANGE:
                info.has_change = True
        return info

    def append_unit(
        self, parts: list[str], origins: list[int], start: int, end: int
    ) -> list[int]:
        for i in range(start, end):
            if self.hidden[i]:
                text, eol, ok = self.placeholder_row(i)
                if ok:
                    parts.append(text + eol)
                    origins.append(0)
                continue
            parts.append(self.lines[i].text + self.lines[i].eol)
            origins.append(i + 1)
        return origins

    def python_owner_line(self, i: int) -> bool:
        if (
            not self.layout.python[i]
            or self.hidden[i]
            or not is_hunk_source(self.layout.kinds[i])
            or len(self.lines[i].text) < 2
            or self.lines[i].text[0] == "-"
        ):
            return False
        if self.in_string[i]:
            return False
        trimmed = trim_python_code(self.lines[i].text[1:])
        return trimmed.startswith("@") or is_python_suite_header_start(trimmed)

    def emits_python_body(self, i: int) -> bool:
        if not self.lines[i].text or self.lines[i].text[0] == "-":
            return False
        if self.hidden[i]:
            _, _, ok = self.placeholder_row(i)
            return ok
        return trim_python_code(self.lines[i].text[1:]) != ""

    def split_hunk(
        self,
        h: _LineSpan,
        prefix_sizes: callable,
        emit: callable,
    ) -> None:
        header_text = self.lines[h.start].text
        old_start, old_zero, new_start, new_zero, heading = parse_hunk_header_for_split(
            header_text
        )
        header_eol = self.lines[h.start].eol or "\n"
        body_start = h.start + 1
        body_end = h.end

        def unit_end(i: int) -> int:
            j = i + 1
            while j < body_end and (
                self.layout.kinds[j] == DiffLineKind.NO_NEWLINE or self.in_string[j]
            ):
                j += 1
            last = i
            while self.python_owner_line(last):
                advanced = False
                while (
                    j < body_end
                    and is_hunk_source(self.layout.kinds[j])
                    and self.lines[j].text
                ):
                    row = j
                    j += 1
                    while j < body_end and (
                        self.layout.kinds[j] == DiffLineKind.NO_NEWLINE
                        or self.in_string[j]
                    ):
                        j += 1
                    last = row
                    advanced = True
                    if self.emits_python_body(row):
                        break
                if not advanced:
                    break
            return j

        old_off = new_off = 0
        at_body_start = True
        i = body_start
        while i < body_end:
            seg_started = False
            seg_heading = ""
            seg_old_start = seg_new_start = 0
            seg_vis_old = seg_vis_new = 0
            seg_text_len = seg_raw_len = seg_count = 0
            body_parts: list[str] = []
            body_origins: list[int] = []
            has_change = False
            while i < body_end:
                nxt = unit_end(i)
                unit = self.unit_stats(i, nxt)
                if unit.count == 0:
                    old_off += unit.drop_old
                    new_off += unit.drop_new
                    at_body_start = False
                    i = nxt
                    continue
                if not seg_started:
                    seg_old_start, seg_new_start = old_start + old_off, new_start + new_off
                    if at_body_start:
                        seg_heading = heading
                    seg_started = True
                header = synth_hunk_header(
                    seg_old_start,
                    seg_vis_old + unit.vis_old,
                    old_zero,
                    seg_new_start,
                    seg_vis_new + unit.vis_new,
                    new_zero,
                    seg_heading,
                )
                pt, pr, pc = prefix_sizes()
                if not self.fits(
                    pt + len(header) + seg_text_len + unit.text_len,
                    pr + len(header) + len(header_eol) + seg_raw_len + unit.raw_len,
                    pc + 1 + seg_count + unit.count,
                ):
                    break
                seg_vis_old += unit.vis_old
                seg_vis_new += unit.vis_new
                seg_text_len += unit.text_len
                seg_raw_len += unit.raw_len
                seg_count += unit.count
                old_off += unit.vis_old + unit.drop_old
                new_off += unit.vis_new + unit.drop_new
                has_change = has_change or unit.has_change
                body_origins = self.append_unit(body_parts, body_origins, i, nxt)
                at_body_start = False
                i = nxt
            if not seg_started:
                break
            if seg_count == 0:
                raise ValueError(
                    f"cannot split the diff near line {i + 1} into a chunk under the "
                    "size limit — try a narrower diff (per-file with `git diff -- | meat`)"
                )
            if not has_change:
                continue
            header = synth_hunk_header(
                seg_old_start, seg_vis_old, old_zero, seg_new_start, seg_vis_new, new_zero, seg_heading
            )
            body = header + header_eol + "".join(body_parts)
            emit(body, [h.start + 1] + body_origins)

    def split_section(self, section_id: int, s: _LineSpan) -> None:
        first_hunk = s.end
        for i in range(s.start, s.end):
            if self.layout.kinds[i] == DiffLineKind.HUNK_HEADER:
                first_hunk = i
                break
        if first_hunk == s.end:
            raise ValueError(
                f"file section at line {s.start + 1} is "
                f"{(self.prefix_raw[s.end] - self.prefix_raw[s.start]) >> 10}KB with no hunks "
                "to split — try a narrower diff (per-file with `git diff -- | meat`)"
            )
        meta_start = first_hunk
        for i in range(s.start, first_hunk):
            if self.layout.file_id[i] >= 0:
                meta_start = i
                break
        preamble = _LineSpan(start=s.start, end=meta_start)
        preamble_text = self.range_text(preamble.start, preamble.end)
        meta = _LineSpan(start=meta_start, end=first_hunk)
        meta_text = self.range_text(meta.start, meta.end)

        tail_start = s.end
        while tail_start > first_hunk:
            kind = self.layout.kinds[tail_start - 1]
            if (
                is_hunk_source(kind)
                or kind == DiffLineKind.NO_NEWLINE
                or kind == DiffLineKind.HUNK_HEADER
            ):
                break
            tail_start -= 1

        hunks: list[_LineSpan] = []
        i = first_hunk
        while i < tail_start:
            j = i + 1
            while j < tail_start and self.layout.kinds[j] != DiffLineKind.HUNK_HEADER:
                j += 1
            hunks.append(_LineSpan(start=i, end=j))
            i = j

        piece = 0

        def emit(body: str, body_origins: list[int]) -> None:
            nonlocal piece
            prefix = meta_text
            prefix_origins = self.range_origins(meta.start, meta.end)
            if piece == 0:
                prefix = preamble_text + meta_text
                prefix_origins = self.range_origins(
                    preamble.start, preamble.end
                ) + prefix_origins
            self.add(
                DiffChunk(
                    text=prefix + body,
                    meta_prefix=meta_text,
                    section_id=section_id,
                    continuation=piece > 0,
                    origins=prefix_origins + body_origins,
                )
            )
            piece += 1

        def prefix_sizes() -> tuple[int, int, int]:
            text_len, raw_len, count = self.span_sizes(meta.start, meta.end)
            if piece == 0:
                pt, pr, pc = self.span_sizes(preamble.start, preamble.end)
                text_len += pt
                raw_len += pr
                count += pc
            return text_len, raw_len, count

        def run_fits(start: int, end: int) -> bool:
            pt, pr, pc = prefix_sizes()
            t, r, c = self.span_sizes(start, end)
            return self.fits(pt + t, pr + r, pc + c)

        open_start = -1
        open_end = 0

        def flush() -> None:
            nonlocal open_start
            if open_start >= 0:
                emit(
                    self.range_text(open_start, open_end),
                    self.range_origins(open_start, open_end),
                )
                open_start = -1

        for h in hunks:
            if self.span_fully_hidden(h):
                continue
            if self.span_has_extra_hidden(h):
                flush()
                self.split_hunk(h, prefix_sizes, emit)
                continue
            if open_start >= 0 and run_fits(open_start, h.end):
                open_end = h.end
                continue
            flush()
            if run_fits(h.start, h.end):
                open_start, open_end = h.start, h.end
                continue
            self.split_hunk(h, prefix_sizes, emit)
        flush()

        tail_text = self.range_text(tail_start, s.end)
        if tail_text and piece > 0:
            last = self.chunks[-1]
            candidate = last.text + tail_text
            if fits_single_run(candidate, self.budget):
                last.text = candidate
                last.origins = last.origins + self.range_origins(tail_start, s.end)
                tail_text = ""
        prose = tail_text
        if piece == 0:
            prose = preamble_text + tail_text
        if prose:
            if not fits_single_run(prose, self.budget):
                raise ValueError(
                    f"cannot fit the diff trailer at line {tail_start + 1} into a chunk "
                    "under the size limit — try a narrower diff "
                    "(per-file with `git diff -- | meat`)"
                )
            self.add(
                DiffChunk(text=prose, section_id=-1, passthrough=True, origins=self.range_origins(tail_start, s.end) if tail_text else self.range_origins(preamble.start, preamble.end))
            )


def parse_hunk_start(field: str, sign: str) -> tuple[int, bool, bool]:
    if len(field) < 2 or field[0] != sign:
        return 0, False, False
    s = field[1:]
    zero_count = False
    if "," in s:
        head, tail = s.split(",", 1)
        zero_count = tail == "0"
        s = head
    try:
        value = int(s)
    except ValueError:
        return 0, False, False
    if value < 0:
        return 0, False, False
    return value, zero_count, True


def parse_hunk_header_for_split(text: str) -> tuple[int, bool, int, bool, str]:
    old_start = new_start = 1
    old_zero = new_zero = False
    heading = ""
    if not text.startswith("@@ "):
        return old_start, old_zero, new_start, new_zero, heading
    rest = text[3:]
    closer = rest.find(" @@")
    if closer < 0:
        return old_start, old_zero, new_start, new_zero, heading
    heading = rest[closer + 3 :]
    fields = rest[:closer].split()
    if len(fields) != 2:
        return old_start, old_zero, new_start, new_zero, heading
    parsed, zero, ok = parse_hunk_start(fields[0], "-")
    if ok:
        old_start, old_zero = parsed, zero
    parsed, zero, ok = parse_hunk_start(fields[1], "+")
    if ok:
        new_start, new_zero = parsed, zero
    return old_start, old_zero, new_start, new_zero, heading


def gap_adjusted_start(start: int, count: int, originally_zero: bool) -> int:
    if count == 0 and not originally_zero:
        start -= 1
        if start < 0:
            start = 0
    return start


def synth_hunk_header(
    old_start: int,
    old_count: int,
    old_zero: bool,
    new_start: int,
    new_count: int,
    new_zero: bool,
    heading: str,
) -> str:
    o = gap_adjusted_start(old_start, old_count, old_zero)
    n = gap_adjusted_start(new_start, new_count, new_zero)
    return f"@@ -{o},{old_count} +{n},{new_count} @@{heading}"


def split_diff_for_abridging(raw: str, budget: int = MAX_DIFF_BYTES) -> list[DiffChunk]:
    if fits_single_run(raw, budget):
        lines = split_source_lines(raw)
        return [DiffChunk(text=raw, origins=[i + 1 for i in range(len(lines))])]

    lines = split_source_lines(raw)
    layout = analyze_diff(lines)
    if layout.problems:
        raise ValueError(join_errors(layout.problems))

    in_string = string_interior_mask(lines, layout)
    import_mask = mandatory_removal_mask(
        len(lines), mandatory_import_removal_plan(lines, layout)
    )
    hidden = list(import_mask)
    apply_mandatory_move_precedence(detect_exact_moves(lines, layout), hidden)
    extra_hidden = [hidden[i] and not import_mask[i] for i in range(len(lines))]

    placeholder_state = PlanState(
        hidden=list(hidden),
        folded=[-1] * len(lines),
        fold_at=[-1] * len(lines),
    )
    add_mandatory_python_suite_placeholders(lines, layout, placeholder_state, hidden)

    builder = _ChunkBuilder(
        lines=lines,
        layout=layout,
        budget=budget,
        hidden=hidden,
        extra_hidden=extra_hidden,
        fold_at=list(placeholder_state.fold_at),
        folds=list(placeholder_state.folds),
        in_string=in_string,
    )

    sections = builder.sections()
    if not sections:
        raise ValueError(
            f"diff is {len(raw.encode('utf-8')) >> 10}KB with no file sections to split "
            "into abridgeable chunks — try a narrower range"
        )

    open_start = -1
    open_end = 0

    def flush() -> None:
        nonlocal open_start
        if open_start >= 0:
            builder.add(
                DiffChunk(
                    text=builder.range_text(open_start, open_end),
                    section_id=-1,
                    origins=builder.range_origins(open_start, open_end),
                )
            )
            open_start = -1

    for section_id, section in enumerate(sections):
        if builder.span_fully_hidden(section):
            flush()
            continue
        if builder.span_has_extra_hidden(section):
            flush()
            builder.split_section(section_id, section)
            continue
        if open_start >= 0 and builder.span_fits(open_start, section.end):
            open_end = section.end
            continue
        flush()
        if builder.span_fits(section.start, section.end):
            open_start, open_end = section.start, section.end
            continue
        builder.split_section(section_id, section)
    flush()
    return builder.chunks


def map_moves_to_chunk(moves: list[DetectedMove], chunk: DiffChunk | str) -> list[DetectedMove]:
    if isinstance(chunk, str):
        origins = [i + 1 for i in range(len(split_source_lines(chunk)))]
    else:
        origins = chunk.origins
    if not moves or not origins:
        return []

    chunk_line: dict[int, int] = {}
    for i, orig in enumerate(origins):
        if orig >= 1:
            chunk_line[orig] = i + 1

    def map_range(r: LineRange) -> tuple[LineRange, bool]:
        start = chunk_line.get(r.start_line)
        if start is None:
            return LineRange(0, 0), False
        for orig in range(r.start_line, r.end_line + 1):
            at = chunk_line.get(orig)
            if at is None or at != start + (orig - r.start_line):
                return LineRange(0, 0), False
        return LineRange(
            start_line=start,
            end_line=start + (r.end_line - r.start_line),
        ), True

    mapped: list[DetectedMove] = []
    for move in moves:
        removed, ok_r = map_range(move.removed)
        added, ok_a = map_range(move.added)
        if ok_r and ok_a:
            mapped.append(DetectedMove(removed=removed, added=added))
    return mapped


def first_line_text(text: str) -> str:
    idx = text.find("\n")
    if idx >= 0:
        text = text[:idx]
    return text.removesuffix("\r")


def piece_contains_line(piece: str, line_text: str) -> bool:
    return any(line.text == line_text for line in split_source_lines(piece))


def strip_replicated_meta(smart: str, meta_prefix: str) -> str:
    meta_lines = split_source_lines(meta_prefix)
    smart_lines = split_source_lines(smart)
    drop = 0
    j = 0
    for line in smart_lines:
        k = j
        while k < len(meta_lines) and meta_lines[k].text != line.text:
            k += 1
        if k == len(meta_lines):
            break
        j = k + 1
        drop += 1
    parts: list[str] = []
    for line in smart_lines[drop:]:
        parts.append(line.text + line.eol)
    return "".join(parts)
