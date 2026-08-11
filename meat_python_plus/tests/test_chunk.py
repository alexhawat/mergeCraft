"""W5 contract: rich chunk splitter + move remap (Go chunk.go)."""

from __future__ import annotations

import pytest

from meat_python_plus.abridge import Request, abridge
from meat_python_plus.chunk import fits_single_run, split_diff_for_abridging
from meat_python_plus.diffutil import DiffLineKind, analyze_diff, numbered_diff, split_source_lines
from meat_python_plus.editplan import EditPlan, compile_edit_plan
from meat_python_plus.model import Block, Response
from _parity_helpers import import_or_fail, require_attr
from fixtures.go_parity import EXACT_MOVE_DIFF


def _file_section(name: str, n: int) -> str:
    lines = [
        f"diff --git a/{name} b/{name}",
        f"--- a/{name}",
        f"+++ b/{name}",
        f"@@ -0,0 +1,{n} @@",
    ]
    lines.extend(f"+{name} row {i}" for i in range(n))
    return "\n".join(lines) + "\n"


def _require_valid_chunks(chunks: list[object], budget: int) -> None:
    chunk_mod = import_or_fail("meat_python_plus.chunk")
    for i, chunk in enumerate(chunks):
        if isinstance(chunk, str):
            text = chunk
        else:
            text = require_attr(chunk, "text")
        if len(text.encode("utf-8")) > budget:
            pytest.fail(f"chunk {i} raw size exceeds budget")
        if len(numbered_diff(text).encode("utf-8")) > budget:
            pytest.fail(f"chunk {i} numbered size exceeds budget")
        diffutil = import_or_fail("meat_python_plus.diffutil")
        validate = require_attr(diffutil, "validate_supported_diff")
        validate(text)


def _chunk_body_rows(text: str) -> list[str]:
    lines = split_source_lines(text)
    layout = analyze_diff(lines)
    rows: list[str] = []
    for i, line in enumerate(lines):
        kind = layout.kinds[i]
        if kind in (DiffLineKind.HUNK_CHANGE, DiffLineKind.HUNK_CONTEXT) or kind == DiffLineKind.NO_NEWLINE:
            rows.append(line.text)
    return rows


def test_split_diff_packs_whole_file_sections() -> None:
    diff = _file_section("a", 5) + _file_section("b", 5) + _file_section("c", 5)
    one = _file_section("a", 5)
    budget = len(numbered_diff(one + one).encode("utf-8"))
    chunk_mod = import_or_fail("meat_python_plus.chunk")
    splitter = require_attr(chunk_mod, "split_diff_for_abridging")
    chunks = splitter(diff, budget)
    _require_valid_chunks(chunks, budget)
    assert len(chunks) == 2
    first_text = chunks[0] if isinstance(chunks[0], str) else chunks[0].text
    second_text = chunks[1] if isinstance(chunks[1], str) else chunks[1].text
    assert "diff --git a/a" in first_text and "diff --git a/b" in first_text
    assert "diff --git a/c" in second_text
    assert first_text + second_text == diff


def test_split_diff_splits_oversized_file_at_hunks() -> None:
    parts = ["diff --git a/big.go b/big.go\n--- a/big.go\n+++ b/big.go\n"]
    for h in range(6):
        parts.append(
            f"@@ -{h * 10 + 1},2 +{h * 10 + 1},3 @@ func f{h}()\n"
            f" context {h}\n+added {h}\n context tail {h}\n"
        )
    diff = "".join(parts)
    budget = len(numbered_diff(diff).encode("utf-8")) // 2 + 40
    chunk_mod = import_or_fail("meat_python_plus.chunk")
    chunks = chunk_mod.split_diff_for_abridging(diff, budget)
    _require_valid_chunks(chunks, budget)
    assert len(chunks) >= 2
    rows: list[str] = []
    for chunk in chunks:
        text = chunk if isinstance(chunk, str) else chunk.text
        assert text.startswith("diff --git a/big.go")
        rows.extend(_chunk_body_rows(text))
    assert rows == _chunk_body_rows(diff)


def test_split_diff_preserves_origin_line_maps() -> None:
    diff = _file_section("origin.go", 20)
    budget = len(numbered_diff(_file_section("origin.go", 8)).encode("utf-8"))
    chunk_mod = import_or_fail("meat_python_plus.chunk")
    chunks = chunk_mod.split_diff_for_abridging(diff, budget)
    for chunk in chunks:
        origins = require_attr(chunk, "origins")
        assert origins
        assert all(o >= 1 for o in origins)


def test_map_moves_to_chunk_includes_both_sides() -> None:
    chunk_mod = import_or_fail("meat_python_plus.chunk")
    map_moves = require_attr(chunk_mod, "map_moves_to_chunk")
    pad = _file_section("zzz.go", 12)
    diff = EXACT_MOVE_DIFF + pad
    budget = len(numbered_diff(EXACT_MOVE_DIFF).encode("utf-8")) + 20
    chunks = chunk_mod.split_diff_for_abridging(diff, budget)
    assert len(chunks) >= 2
    first = chunks[0]
    text = first if isinstance(first, str) else first.text
    assert "new_location_ready" in text
    moves_mod = import_or_fail("meat_python_plus.moves")
    detect = require_attr(moves_mod, "detected_moves_in_diff")
    whole_moves = detect(diff)
    chunk_moves = map_moves(whole_moves, first)
    assert chunk_moves
    removed_lines = {m.removed.start_line for m in chunk_moves}
    added_lines = {m.added.start_line for m in chunk_moves}
    assert removed_lines and added_lines


class _IdentitySubmit:
    def generate(self, system: str, messages: list[object], tools: list[object]) -> Response:
        _ = (system, messages, tools)
        return Response(
            content=[
                Block(
                    type="tool_use",
                    id="submit",
                    tool_name="submit",
                    tool_input={
                        "remove": [],
                        "replace": [],
                        "fold": [],
                        "summary": "Adds rows.",
                    },
                )
            ]
        )


def test_abridge_chunked_enforces_whole_diff_moves(monkeypatch: pytest.MonkeyPatch) -> None:
    chunk_mod = import_or_fail("meat_python_plus.chunk")
    budget = len(numbered_diff(EXACT_MOVE_DIFF).encode("utf-8")) + 20
    monkeypatch.setattr(chunk_mod, "MAX_DIFF_BYTES", budget, raising=False)

    pad = _file_section("zzz.go", 12)
    diff = EXACT_MOVE_DIFF + pad
    assert not fits_single_run(diff, budget)

    class TwoTurn:
        def __init__(self) -> None:
            self.calls = 0

        def generate(self, system: str, messages: list[object], tools: list[object]) -> Response:
            _ = (system, messages, tools)
            self.calls += 1
            if self.calls == 1:
                return Response(
                    content=[
                        Block(
                            type="tool_use",
                            id="bad",
                            tool_name="submit",
                            tool_input={
                                "remove": [],
                                "replace": [],
                                "fold": [{"start_line": 6, "end_line": 9}],
                                "summary": "Relocates the pipeline.",
                            },
                        )
                    ]
                )
            return Response(
                content=[
                    Block(
                        type="tool_use",
                        id="good",
                        tool_name="submit",
                        tool_input={
                            "remove": [],
                            "replace": [],
                            "fold": [
                                {"start_line": 6, "end_line": 9},
                                {"start_line": 16, "end_line": 19},
                            ],
                            "summary": "Relocates the pipeline.",
                        },
                    )
                ]
            )

    model = TwoTurn()
    res = abridge(model, Request(unified_diff=diff, repo_root=""))
    assert model.calls >= 2
    assert res.smart_diff.count("...") >= 2


def test_split_diff_mid_hunk_preserves_changed_rows() -> None:
    body = ["diff --git a/big.go b/big.go\n--- a/big.go\n+++ b/big.go\n"]
    body.append("@@ -100,30 +200,45 @@ func big()\n")
    for i in range(30):
        body.append(f" context row {i:02d}\n")
        if i % 2 == 0:
            body.append(f"+added row {i:02d}\n")
    diff = "".join(body)
    budget = len(numbered_diff(diff).encode("utf-8")) // 3 + 60
    chunk_mod = import_or_fail("meat_python_plus.chunk")
    chunks = chunk_mod.split_diff_for_abridging(diff, budget)
    _require_valid_chunks(chunks, budget)
    assert len(chunks) >= 2

    def changed_rows(text: str) -> list[str]:
        return [r for r in _chunk_body_rows(text) if r.startswith(("+", "-"))]

    got: list[str] = []
    for chunk in chunks:
        text = chunk if isinstance(chunk, str) else chunk.text
        got.extend(changed_rows(text))
    assert got == changed_rows(diff)
