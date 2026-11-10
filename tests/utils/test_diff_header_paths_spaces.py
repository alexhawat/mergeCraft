"""``diff --git`` headers with spaces or quoting keep their real path (#1253)."""

from __future__ import annotations

import pytest

from mergecraft.utils.diff_paths import post_image_path_from_header
from mergecraft.utils.offline_diff import summarize_diff
from mergecraft.utils.run_bounds import _diff_file_blocks, apply_diff_line_budget

_SPACE = "diff --git a/my file.txt b/my file.txt\n--- a/my file.txt\n+++ b/my file.txt\n@@ -1 +1 @@\n-a\n+b\n"
_QUOTED = 'diff --git "a/caf\\303\\251 x.txt" "b/caf\\303\\251 x.txt"\n@@ -1 +1 @@\n-a\n+b\n'
_PLAIN = "diff --git a/plain.py b/plain.py\n@@ -1 +1 @@\n-a\n+b\n"


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("diff --git a/my file.txt b/my file.txt", "my file.txt"),
        ('diff --git "a/tab\\there" "b/tab\\there"', "tab\there"),
        ("diff --git a/x.py b/x.py", "x.py"),
        ("--- a/x.py", None),
    ],
)
def test_post_image_path_from_header(line: str, expected: str | None) -> None:
    assert post_image_path_from_header(line) == expected


def test_diff_file_blocks_keep_paths_with_spaces() -> None:
    blocks = _diff_file_blocks(_SPACE + _QUOTED + _PLAIN)
    assert [path for path, _ in blocks] == ["my file.txt", "café x.txt", "plain.py"]


def test_summarize_diff_lists_paths_with_spaces_and_quotes() -> None:
    summary = summarize_diff(_SPACE + _QUOTED + _PLAIN)
    assert "3 file(s) changed" in summary
    assert "- my file.txt" in summary
    assert "- café x.txt" in summary
    assert "- plain.py" in summary


def test_line_budget_omits_whole_file_blocks_for_spaced_paths() -> None:
    body = "".join(f"+line{i}\n" for i in range(50))
    diff = (
        "diff --git a/my file.txt b/my file.txt\n@@ -0,0 +1,50 @@\n"
        + body
        + "diff --git a/other file.txt b/other file.txt\n@@ -0,0 +1,50 @@\n"
        + body
    )
    reduced, reduction = apply_diff_line_budget(diff, max_lines=60)
    assert reduction is not None
    assert "my file.txt" in reduced
