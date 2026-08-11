import pytest

from meat_python_plus.editplan import (
    EditPlan,
    LineFold,
    LineRange,
    LineReplacement,
    Submission,
    compile_edit_plan,
    compile_submission,
    is_elision_projection,
)

DIFF = """diff --git a/x.py b/x.py
--- a/x.py
+++ b/x.py
@@ -1,4 +1,4 @@
 import os
-old_a = 1
-old_b = 2
+new_a = 1
+new_b = 2
 context
"""


def test_elision_projection():
    assert is_elision_projection("hello world", "hello ...")
    assert is_elision_projection("sshKeyID", "...")
    assert not is_elision_projection("hello", "hello")
    assert not is_elision_projection("hello world", "hello")


def test_remove_lines():
    # 1 header 2 --- 3 +++ 4 @@ 5 import 6 -old_a 7 -old_b 8 +new_a 9 +new_b 10 context
    plan = EditPlan(remove=[LineRange(6, 7)], replace=[], fold=[])
    compiled = compile_edit_plan(DIFF, plan)
    assert "-old_a" not in compiled.smart_diff
    assert "-old_b" not in compiled.smart_diff
    assert "+new_a" in compiled.smart_diff
    assert "import os" not in compiled.smart_diff


def test_fold_same_marker():
    plan = EditPlan(remove=[], replace=[], fold=[LineFold(8, 9)])
    compiled = compile_edit_plan(DIFF, plan)
    assert "+new_a" not in compiled.smart_diff
    assert "..." in compiled.smart_diff


def test_replace_elision():
    plan = EditPlan(
        remove=[],
        replace=[LineReplacement(line=8, old="new_a = 1", new="new_a = ...")],
        fold=[],
    )
    compiled = compile_edit_plan(DIFF, plan)
    assert "new_a = ..." in compiled.smart_diff


def test_invalid_overlap_remove():
    plan = EditPlan(
        remove=[LineRange(6, 7), LineRange(7, 8)],
        replace=[],
        fold=[],
    )
    with pytest.raises(ValueError, match="overlaps"):
        compile_edit_plan(DIFF, plan)


def test_submission_requires_summary():
    with pytest.raises(ValueError, match="summary"):
        compile_submission(
            DIFF,
            Submission(remove=[], replace=[], fold=[], summary=""),
        )


def test_structure_retention_hunk_header():
    # Remove every change; only context remains → hunk header must not survive alone.
    plan = EditPlan(remove=[LineRange(6, 9)], replace=[], fold=[])
    with pytest.raises(ValueError, match="hunk header"):
        compile_edit_plan(DIFF, plan)
