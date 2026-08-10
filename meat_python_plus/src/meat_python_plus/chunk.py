"""Simplified large-diff chunking at file / hunk boundaries."""

from __future__ import annotations

from meat_python_plus.diffutil import (
    DiffLineKind,
    analyze_diff,
    numbered_diff,
    split_source_lines,
)

MAX_DIFF_BYTES = 400 << 10  # ~400 KB
MAX_TOTAL_DIFF_BYTES = 4 << 20  # 4 MB
MAX_CHUNKS = 32


def fits_single_run(raw: str, budget: int = MAX_DIFF_BYTES) -> bool:
    if len(raw.encode("utf-8")) > budget:
        return False
    numbered = numbered_diff(raw)
    return len(numbered.encode("utf-8")) <= budget


def split_diff_for_abridging(raw: str, budget: int = MAX_DIFF_BYTES) -> list[str]:
    """Split at file section boundaries; fall back to hunk boundaries.

    This is a simplified splitter vs Go meat's chunk.go (no move remapping,
    no mandatory-import pre-hide, no mid-hunk synthesis).
    """
    if fits_single_run(raw, budget):
        return [raw]

    lines = split_source_lines(raw)
    layout = analyze_diff(lines)

    # File section starts: HEADER or (when no git header) OLD_FILE.
    section_starts: list[int] = []
    for i, kind in enumerate(layout.kinds):
        if kind == DiffLineKind.HEADER:
            section_starts.append(i)
        elif kind == DiffLineKind.OLD_FILE and (
            i == 0 or layout.kinds[i - 1] != DiffLineKind.HEADER
        ):
            # Bare ---/+++ file without preceding diff --git already counted via
            # analyze_diff file_id; still treat OLD_FILE after non-header as start
            # when no HEADER exists in the whole diff.
            if not any(k == DiffLineKind.HEADER for k in layout.kinds):
                section_starts.append(i)

    if not section_starts:
        section_starts = [0]
    section_starts = sorted(set(section_starts))

    sections: list[str] = []
    for idx, start in enumerate(section_starts):
        end = section_starts[idx + 1] if idx + 1 < len(section_starts) else len(lines)
        chunk = "".join(line.text + line.eol for line in lines[start:end])
        if fits_single_run(chunk, budget):
            sections.append(chunk)
        else:
            # Split oversized file at hunk headers.
            hunk_starts = [
                i
                for i in range(start, end)
                if layout.kinds[i] == DiffLineKind.HUNK_HEADER
            ]
            # Metadata prefix before first hunk.
            meta_end = hunk_starts[0] if hunk_starts else end
            meta = "".join(line.text + line.eol for line in lines[start:meta_end])
            if not hunk_starts:
                # Can't split further; hard-fail if over budget.
                if not fits_single_run(chunk, budget):
                    raise ValueError(
                        f"unable to split file section starting at line {start + 1} "
                        f"under {budget} bytes"
                    )
                sections.append(chunk)
                continue
            for hi, hstart in enumerate(hunk_starts):
                hend = hunk_starts[hi + 1] if hi + 1 < len(hunk_starts) else end
                body = "".join(line.text + line.eol for line in lines[hstart:hend])
                piece = meta + body
                if not fits_single_run(piece, budget):
                    raise ValueError(
                        f"hunk starting at line {hstart + 1} exceeds single-run budget; "
                        "narrow the diff"
                    )
                sections.append(piece)

    if len(sections) > MAX_CHUNKS:
        raise ValueError(
            f"diff would split into {len(sections)} chunks (max {MAX_CHUNKS}); "
            "try a narrower range"
        )
    return sections
