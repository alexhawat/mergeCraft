"""W4 contract: Python suite validators (Go python.go / editplan_test.go)."""

from __future__ import annotations

import pytest

from meat_python_plus.editplan import EditPlan, LineFold, LineRange, LineReplacement, compile_edit_plan


def test_requires_body_for_retained_python_suite() -> None:
    raw = (
        "diff --git a/a.py b/a.py\n@@ -0,0 +1,5 @@\n+def test_one():\n+ setup()\n"
        "+ assert result\n+def test_two():\n+ assert other\n"
    )
    with pytest.raises(ValueError, match="suite owner on line 3 has no indented body"):
        compile_edit_plan(raw, EditPlan(remove=[LineRange(4, 5)]))

    compiled = compile_edit_plan(raw, EditPlan(fold=[LineFold(4, 5)]))
    assert "+def test_one():\n+ ...\n" in compiled.smart_diff


def test_rejects_detached_decorator() -> None:
    decorated = (
        "diff --git a/a.py b/a.py\n@@ -0,0 +1,3 @@\n+@pytest.mark.slow\n"
        "+def test_it():\n+ assert result\n"
    )
    with pytest.raises(ValueError, match="decorator or suite owner"):
        compile_edit_plan(decorated, EditPlan(fold=[LineFold(3, 4)]))

    with pytest.raises(ValueError, match="decorator on line 3 has no attached definition"):
        compile_edit_plan(decorated, EditPlan(remove=[LineRange(4, 5)]))


def test_preserves_triple_quote_balance() -> None:
    quoted = (
        "diff --git a/a.py b/a.py\n@@ -0,0 +1,5 @@\n+def test_it():\n+ \"\"\"scenario\n"
        "+ stimulus\n+ \"\"\"\n+ assert result\n"
    )
    with pytest.raises(ValueError, match="balanced Python"):
        compile_edit_plan(quoted, EditPlan(remove=[LineRange(6, 6)]))

    with pytest.raises(ValueError, match="boundary tokens"):
        compile_edit_plan(
            quoted,
            EditPlan(replace=[LineReplacement(line=4, old='"""scenario', new="...")]),
        )


def test_rejects_fold_that_hides_suite_owner() -> None:
    raw = (
        "diff --git a/a.py b/a.py\n@@ -1,2 +1,2 @@\n def f():\n- old()\n+ new()\n"
    )
    with pytest.raises(ValueError, match="hides Python suite owner on line 3"):
        compile_edit_plan(raw, EditPlan(remove=[LineRange(3, 3)]))


def test_rejects_deleted_table_still_referenced() -> None:
    raw = (
        "diff --git a/a.py b/a.py\n@@ -0,0 +1,7 @@\n+CASES = [\n+ (\"a\", 1),\n+ (\"b\", 2),\n+]\n"
        "+@pytest.mark.parametrize(\"name, value\", CASES)\n+def test_cases(name, value):\n"
        "+ assert value\n"
    )
    with pytest.raises(ValueError, match="CASES"):
        compile_edit_plan(
            raw,
            EditPlan(remove=[LineRange(3, 5)]),
        )


def test_allows_multiline_decorator_argument_fold() -> None:
    decorator = (
        "diff --git a/a.py b/a.py\n@@ -0,0 +1,6 @@\n+@mark(\n+ first,\n+ second,\n+)\n"
        "+def f():\n+ work()\n"
    )
    compile_edit_plan(decorator, EditPlan(fold=[LineFold(4, 5)]))

    with pytest.raises(ValueError, match="decorator on line 3 has no attached definition"):
        compile_edit_plan(decorator, EditPlan(remove=[LineRange(7, 8)]))


def test_rejects_python_structural_replacements() -> None:
    raw = (
        "diff --git a/a.py b/a.py\n@@ -0,0 +1,3 @@\n+@decorator\n+def f():\n+ work()\n"
    )
    for replacement in (
        LineReplacement(line=3, old="@decorator", new="..."),
        LineReplacement(line=4, old="def f():", new="..."),
    ):
        with pytest.raises(ValueError, match="structural anchors intact"):
            compile_edit_plan(raw, EditPlan(replace=[replacement]))
