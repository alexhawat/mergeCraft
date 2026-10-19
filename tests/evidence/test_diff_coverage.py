"""Line-range diff coverage — TOC parse, covered reads, and the one-time nudge."""

from __future__ import annotations

from mergecraft.evidence.diff_coverage import (
    LineRange,
    compute_diff_coverage,
    coverage_nudge,
    parse_diff_toc,
    unread_ranges_for_findings,
)
from mergecraft.evidence.trajectory import ToolCallRecord

_DIFF = """\
diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,3 +1,5 @@
 import os
-WEAK = True
+WEAK = False
+assert not WEAK
 def main():
     return 0
@@ -20,2 +22,4 @@ def later():
     pass
+def added():
+    return "x"
diff --git a/src/gone.py b/src/gone.py
deleted file mode 100644
--- a/src/gone.py
+++ /dev/null
@@ -1,2 +0,0 @@
-x = 1
-y = 2
diff --git a/src/other.py b/src/other.py
--- a/src/other.py
+++ b/src/other.py
@@ -5,2 +5,3 @@
 def value():
+    return 42
     return None
"""


def _call(
    sequence: int,
    *,
    command: str | None = None,
    paths: list[str] | None = None,
    intent: str = "read",
    ok: bool = True,
) -> ToolCallRecord:
    return ToolCallRecord(
        sequence=sequence,
        tool="shell" if command is not None else "Read",
        signature=f"call:{sequence}",
        intent=intent,  # type: ignore[arg-type]  # — test helper narrows to the documented Intent set
        ok=ok,
        command=command,
        paths=paths or [],
    )


def test_parse_diff_toc_keeps_added_ranges_and_skips_deletion_only_files() -> None:
    entries = parse_diff_toc(_DIFF)

    assert [entry.path for entry in entries] == ["src/app.py", "src/other.py"]
    assert entries[0].ranges == (LineRange(2, 3), LineRange(23, 24))
    assert entries[1].ranges == (LineRange(6, 6),)


def test_full_diff_read_covers_every_added_line() -> None:
    diff_path = "/tmp/mergecraft/pr-7.diff"
    breakdown = compute_diff_coverage(
        _DIFF,
        [_call(1, command=f"cat {diff_path}")],
        diff_path=diff_path,
    )

    assert breakdown.observed is True
    assert breakdown.total_lines == 5
    assert breakdown.unread_lines == 0
    assert breakdown.coverage_percent == 100.0
    assert coverage_nudge(breakdown, diff_path=diff_path) is None


def test_partial_diff_read_names_the_unread_ranges() -> None:
    diff_path = "/tmp/mergecraft/pr-7.diff"
    # Lines 1-12 of the diff cover src/app.py's first hunk; src/other.py is not read.
    breakdown = compute_diff_coverage(
        _DIFF,
        [_call(1, command=f"sed -n '1,12p' {diff_path}")],
        diff_path=diff_path,
    )

    assert breakdown.observed is True
    assert breakdown.unread_lines > 0
    assert ("src/other.py", (LineRange(6, 6),)) in unread_ranges_for_findings(breakdown)

    nudge = coverage_nudge(breakdown, diff_path=diff_path)
    assert nudge is not None
    assert "`src/other.py:6-6`" in nudge
    assert "one-time nudge" in nudge


def test_source_file_read_covers_that_files_added_ranges_only() -> None:
    breakdown = compute_diff_coverage(
        _DIFF,
        [_call(1, paths=["src/app.py"])],
    )

    assert breakdown.observed is True
    app, other = breakdown.files
    assert app.unread == ()
    assert other.unread == (LineRange(6, 6),)


def test_ranged_source_read_covers_only_the_intersection() -> None:
    breakdown = compute_diff_coverage(
        _DIFF,
        [_call(1, command="sed -n '1,10p' src/app.py", paths=["src/app.py"])],
    )

    app = breakdown.files[0]
    assert app.covered == (LineRange(2, 3),)
    assert app.unread == (LineRange(23, 24),)


def test_no_observed_read_is_unknown_not_unread() -> None:
    breakdown = compute_diff_coverage(_DIFF, [])

    assert breakdown.observed is False
    assert breakdown.unread_lines == 5
    assert coverage_nudge(breakdown, diff_path="/tmp/pr.diff") is None


def test_generated_only_unread_ranges_do_not_nudge() -> None:
    diff = """\
diff --git a/uv.lock b/uv.lock
--- a/uv.lock
+++ b/uv.lock
@@ -1,1 +1,2 @@
 lock
+more lock
"""
    breakdown = compute_diff_coverage(
        diff,
        [_call(1, command="cat src/read.py", paths=["src/read.py"])],
    )

    assert breakdown.observed is True
    assert breakdown.unread_lines == 1
    assert coverage_nudge(breakdown, diff_path="/tmp/pr.diff") is None
