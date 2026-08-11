"""W10 contract: golden Python corpus + parity suites (Go python_golden_test.go)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from meat_python_plus.editplan import EditPlan, LineRange, compile_edit_plan, parse_edit_plan
from _parity_helpers import import_or_fail, require_attr
from fixtures.go_parity import GOLDEN_PYTHON_BASES

FIXTURE_DIR = Path(__file__).resolve().parent / "testdata" / "python"


def _fixture_paths(base: str) -> tuple[Path, Path, Path]:
    return (
        FIXTURE_DIR / f"{base}.diff",
        FIXTURE_DIR / f"{base}.plan.json",
        FIXTURE_DIR / f"{base}.golden.diff",
    )


def _require_golden_fixtures(base: str) -> tuple[str, dict[str, object], str]:
    diff_path, plan_path, golden_path = _fixture_paths(base)
    if not diff_path.exists():
        pytest.skip(f"upstream golden fixtures not copied yet (W10): missing {diff_path.name}")
    raw = diff_path.read_text(encoding="utf-8")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    golden = golden_path.read_text(encoding="utf-8")
    return raw, plan, golden


@pytest.mark.parametrize("base", GOLDEN_PYTHON_BASES)
def test_python_golden_plan_matches_snapshot(base: str) -> None:
    raw, plan_data, golden = _require_golden_fixtures(base)
    plan = parse_edit_plan(plan_data)
    assert plan.remove is not None and plan.replace is not None and plan.fold is not None
    _assert_golden_plan_leaves_imports_automatic(raw, plan)
    compiled = compile_edit_plan(raw, plan)
    assert compiled.smart_diff == golden


def test_python_golden_pytest_move_and_anchors() -> None:
    raw, plan_data, _golden = _require_golden_fixtures("pytest-b4e846616cbb")
    moves_mod = import_or_fail("meat_python_plus.moves")
    detect = require_attr(moves_mod, "detected_moves_in_diff")
    moves = detect(raw)
    assert any(
        m.removed.start_line == 72 and m.removed.end_line == 81 and m.added.start_line == 23 and m.added.end_line == 32
        for m in moves
    )
    compiled = compile_edit_plan(raw, parse_edit_plan(plan_data))
    for want in (
        "+    @contextlib.contextmanager",
        "+            apply_warning_filters(config_filters, cmdline_filters)",
        "+    result.assert_outcomes(passed=1)",
    ):
        assert want in compiled.smart_diff
    for unwanted in (" import warnings", " import pytest", "from contextlib import ExitStack"):
        assert unwanted not in compiled.smart_diff


def _assert_golden_plan_leaves_imports_automatic(raw: str, plan: EditPlan) -> None:
    imports = import_or_fail("meat_python_plus.imports")
    mandatory_plan = require_attr(imports, "mandatory_import_removal_plan")
    diffutil = import_or_fail("meat_python_plus.diffutil")
    lines = diffutil.split_source_lines(raw)
    layout = diffutil.analyze_diff(lines)
    mandatory = [False] * len(lines)
    for r in mandatory_plan(lines, layout):
        for line_no in range(r.start_line, r.end_line + 1):
            mandatory[line_no - 1] = True

    def check(kind: str, index: int, start: int, end: int) -> None:
        for line_no in range(start, end + 1):
            if mandatory[line_no - 1]:
                pytest.fail(f"{kind}[{index}] targets compiler-owned import line {line_no}")

    for i, r in enumerate(plan.remove):
        check("remove", i, r.start_line, r.end_line)
    for i, f in enumerate(plan.fold):
        check("fold", i, f.start_line, f.end_line)
    for i, r in enumerate(plan.replace):
        check("replace", i, r.line, r.line)


def test_python_golden_rejects_asymmetric_move_mutation() -> None:
    raw, plan_data, _ = _require_golden_fixtures("pytest-b4e846616cbb")
    plan = parse_edit_plan(plan_data)
    mutated = EditPlan(
        remove=[*plan.remove, LineRange(start_line=72, end_line=72)],
        replace=list(plan.replace),
        fold=list(plan.fold),
    )
    with pytest.raises(ValueError, match="move symmetry"):
        compile_edit_plan(raw, mutated)


def test_python_golden_complete_removal_is_empty() -> None:
    raw, _, _ = _require_golden_fixtures("django-526b1b414d8e")
    diffutil = import_or_fail("meat_python_plus.diffutil")
    line_count = len(diffutil.split_source_lines(raw))
    compiled = compile_edit_plan(raw, EditPlan(remove=[LineRange(1, line_count)]))
    assert compiled.smart_diff == ""
