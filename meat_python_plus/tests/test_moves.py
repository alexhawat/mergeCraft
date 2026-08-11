"""W3 contract: move detection + symmetry enforcement (Go moves.go)."""

from __future__ import annotations

import pytest

from meat_python_plus.abridge import Request, abridge
from meat_python_plus.editplan import (
    DetectedMove,
    EditPlan,
    LineFold,
    LineRange,
    LineReplacement,
    Submission,
    compile_edit_plan,
    detect_exact_moves,
    plan_feedback,
)
from meat_python_plus.diffutil import analyze_diff, split_source_lines
from meat_python_plus.model import Block, Message, Response
from _parity_helpers import import_or_fail, require_attr
from fixtures.go_parity import (
    EXACT_MOVE_ADDED,
    EXACT_MOVE_DIFF,
    EXACT_MOVE_REMOVED,
)


def _detect_moves_in_diff(raw: str) -> list[DetectedMove]:
    moves_mod = import_or_fail("meat_python_plus.moves")
    if hasattr(moves_mod, "detected_moves_in_diff"):
        return moves_mod.detected_moves_in_diff(raw)
    lines = split_source_lines(raw)
    layout = analyze_diff(lines)
    return detect_exact_moves(lines, layout)


def test_detect_exact_move_cross_file() -> None:
    moves = _detect_moves_in_diff(EXACT_MOVE_DIFF)
    assert len(moves) == 1
    move = moves[0]
    assert (move.removed.start_line, move.removed.end_line) == EXACT_MOVE_REMOVED
    assert (move.added.start_line, move.added.end_line) == EXACT_MOVE_ADDED


def test_detect_exact_move_same_file_cross_hunk() -> None:
    raw = (
        "diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n"
        "@@ -1,4 +1,0 @@\n-first_unique_operation(source)\n"
        "-second_unique_operation(result)\n-third_unique_operation(result)\n"
        "-fourth_unique_operation(result)\n@@ -20,0 +17,4 @@\n"
        "+ first_unique_operation(source)\n+ second_unique_operation(result)\n"
        "+ third_unique_operation(result)\n+ fourth_unique_operation(result)\n"
    )
    moves = _detect_moves_in_diff(raw)
    assert len(moves) == 1
    assert (moves[0].removed.start_line, moves[0].removed.end_line) == (5, 8)
    assert (moves[0].added.start_line, moves[0].added.end_line) == (10, 13)


@pytest.mark.parametrize(
    "name",
    [
        "ambiguous repeated block",
        "tiny coincidence",
        "same hunk replacement",
        "nonconstant indentation shift",
    ],
)
def test_detect_exact_moves_ignores_ambiguous(name: str) -> None:
    _ = name
    block = [
        "first_unique_operation(source)",
        "second_unique_operation(result)",
        "third_unique_operation(result)",
    ]

    def deleted_hunk(start: int, rows: list[str]) -> str:
        out = f"@@ -{start},{len(rows)} +{start},0 @@\n"
        return out + "".join(f"-{row}\n" for row in rows)

    def added_hunk(start: int, rows: list[str]) -> str:
        out = f"@@ -{start},0 +{start},{len(rows)} @@\n"
        return out + "".join(f"+ {row}\n" for row in rows)

    header = "diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n"
    cases = {
        "ambiguous repeated block": header + deleted_hunk(1, block) + deleted_hunk(20, block) + added_hunk(40, block),
        "tiny coincidence": header
        + deleted_hunk(1, ["return first", "return second"])
        + added_hunk(20, ["return first", "return second"]),
        "same hunk replacement": (
            header
            + "@@ -1,3 +1,3 @@\n-first_unique_operation(source)\n"
            "-second_unique_operation(result)\n-third_unique_operation(result)\n"
            "+first_unique_operation(source)\n+second_unique_operation(result)\n"
            "+third_unique_operation(result)\n"
        ),
        "nonconstant indentation shift": header
        + deleted_hunk(1, block)
        + "@@ -20,0 +17,3 @@\n+    first_unique_operation(source)\n"
        "+        second_unique_operation(result)\n+    third_unique_operation(result)\n",
    }
    assert _detect_moves_in_diff(cases[name]) == []


@pytest.mark.parametrize(
    "plan",
    [
        EditPlan(),
        EditPlan(remove=[LineRange(6, 9), LineRange(16, 19)]),
        EditPlan(fold=[LineFold(6, 9), LineFold(16, 19)]),
        EditPlan(remove=[LineRange(1, 20)]),
    ],
)
def test_move_symmetry_passing_plans(plan: EditPlan) -> None:
    compile_edit_plan(EXACT_MOVE_DIFF, plan)


@pytest.mark.parametrize(
    ("plan", "needle"),
    [
        (EditPlan(remove=[LineRange(6, 9)]), "removed while added lines 16-19 are kept"),
        (
            EditPlan(remove=[LineRange(16, 19)], fold=[LineFold(6, 9)]),
            "removed lines 6-9 are folded while added lines 16-19 are removed",
        ),
        (EditPlan(fold=[LineFold(16, 19)]), "removed lines 6-9 are kept while added lines 16-19 are folded"),
    ],
)
def test_move_symmetry_failing_plans(plan: EditPlan, needle: str) -> None:
    with pytest.raises(ValueError) as exc:
        compile_edit_plan(EXACT_MOVE_DIFF, plan)
    msg = str(exc.value)
    assert "removed lines 6-9 match added lines 16-19" in msg
    assert needle in msg


def test_move_replacement_symmetry_equivalent_elisions() -> None:
    plan = EditPlan(
        replace=[
            LineReplacement(line=8, old="beta", new="..."),
            LineReplacement(line=18, old="beta", new="..."),
        ]
    )
    compiled = compile_edit_plan(EXACT_MOVE_DIFF, plan)
    assert compiled.smart_diff.count("publish(...)") == 2


def test_move_replacement_symmetry_one_sided_elision() -> None:
    plan = EditPlan(replace=[LineReplacement(line=8, old="beta", new="...")])
    with pytest.raises(ValueError) as exc:
        compile_edit_plan(EXACT_MOVE_DIFF, plan)
    msg = str(exc.value)
    assert "move symmetry" in msg
    assert "corresponding kept lines 8 and 18 have different model-authored local elisions" in msg


def test_plan_feedback_reports_symmetric_moves() -> None:
    compiled = compile_edit_plan(
        EXACT_MOVE_DIFF,
        EditPlan(fold=[LineFold(6, 9), LineFold(16, 19)]),
    )
    feedback = plan_feedback(compiled)
    for want in (
        "Moves: 1 exact cross-hunk/cross-file",
        "treated symmetrically",
        "-6..9 ↔ +16..19",
    ):
        assert want in feedback


class _ScriptedModel:
    def __init__(self, turns: list[Response]) -> None:
        self.turns = turns
        self.seen = 0
        self.messages: list[list[Message]] = []

    def generate(self, system: str, messages: list[Message], tools: list[object]) -> Response:
        _ = (system, tools)
        self.messages.append(list(messages))
        if self.seen >= len(self.turns):
            raise AssertionError("unexpected extra model call")
        resp = self.turns[self.seen]
        self.seen += 1
        return resp


def _tool_submit(name: str, payload: dict[str, object]) -> Response:
    return Response(
        content=[
            Block(
                type="tool_use",
                id=name,
                tool_name="submit",
                tool_input=payload,
            )
        ]
    )


def test_abridge_rejects_asymmetric_move_then_accepts_correction() -> None:
    model = _ScriptedModel(
        [
            _tool_submit(
                "asymmetric",
                {
                    "remove": [],
                    "replace": [],
                    "fold": [{"start_line": 16, "end_line": 19}],
                    "summary": "Moves processing to the new location.",
                },
            ),
            _tool_submit(
                "symmetric",
                {
                    "remove": [],
                    "replace": [],
                    "fold": [
                        {"start_line": 6, "end_line": 9},
                        {"start_line": 16, "end_line": 19},
                    ],
                    "summary": "Moves processing to the new location.",
                },
            ),
        ]
    )
    res = abridge(model, Request(unified_diff=EXACT_MOVE_DIFF, repo_root=""))
    assert model.seen == 2
    assert res.smart_diff.count("...") == 2

    initial = model.messages[0][0].content[0].text
    assert "-6..9 ↔ +16..19" in initial
    assert "identical keep/remove/fold/replace treatment" in initial

    saw_error = any(
        block.type == "tool_result" and block.tool_error and "removed lines 6-9 match added lines 16-19" in block.tool_result
        for msg in model.messages[1]
        for block in msg.content
    )
    assert saw_error
