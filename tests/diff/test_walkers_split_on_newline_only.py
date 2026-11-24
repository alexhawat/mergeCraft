"""Every diff walker splits on ``\\n`` only, as :func:`mergecraft.diff.diff_lines` does.

``str.splitlines`` also breaks on ``\\r``, form feeds and Unicode separators, so a
walker using it would read content holding one of them as a new ``diff --git``
or hunk line and disagree with :func:`mergecraft.diff.parse_diff`.
"""

from __future__ import annotations

import pytest

from mergecraft.diff import diff_lines, parse_diff

_SEPARATORS = ("\r", "\x0c", "\x85", " ", " ")


def _diff(separator: str) -> str:
    content = f"a{separator}diff --git a/y.py b/y.py{separator}@@ -1,0 +1,9 @@{separator}+b"
    return (
        "diff --git a/x.py b/x.py\n"
        "index 1111111..2222222 100644\n"
        "--- a/x.py\n"
        "+++ b/x.py\n"
        "@@ -1,1 +1,2 @@\n"
        " keep\n"
        f"+{content}\n"
    )


def test_diff_lines_strip_cr_drops_one_trailing_carriage_return() -> None:
    assert diff_lines("+a\r\n+b\rc\n", strip_cr=True) == ["+a", "+b\rc"]
    assert diff_lines("+a\r\n+b", keepends=True, strip_cr=True) == ["+a\r\n", "+b"]


@pytest.mark.parametrize("separator", _SEPARATORS, ids=lambda c: f"U+{ord(c):04X}")
def test_every_walker_sees_the_files_parse_diff_sees(separator: str) -> None:
    from mergecraft.classify.triage import _parse
    from mergecraft.evidence.diff_coverage import parse_diff_toc
    from mergecraft.jev.segment import segment_hunks
    from mergecraft.utils.offline_diff import summarize_diff
    from mergecraft.utils.run_bounds import _diff_file_blocks

    diff = _diff(separator)

    assert [section.path for section in parse_diff(diff).files] == ["x.py"]
    toc = parse_diff_toc(diff)
    assert [(entry.path, entry.diff_start, entry.diff_end) for entry in toc] == [("x.py", 1, 7)]
    assert [(unit.path, unit.start_line) for unit in segment_hunks(diff)] == [("x.py", 1)]
    assert summarize_diff(diff) == "1 file(s) changed:\n- x.py"
    blocks = _diff_file_blocks(diff)
    assert [path for path, _ in blocks] == ["x.py"]
    assert "".join(text for _, text in blocks) == diff
    (parsed,) = _parse(diff)
    assert parsed.path == "x.py"
    assert [len(hunk.lines) for hunk in parsed.hunks] == [2]


@pytest.mark.parametrize("separator", _SEPARATORS, ids=lambda c: f"U+{ord(c):04X}")
def test_diff_line_counters_count_lines_git_wrote(separator: str) -> None:
    from mergecraft.analyzers.baseline_suppression import _changed_line_count
    from mergecraft.cli.describe_cmd import _line_counts
    from mergecraft.evidence.run_packet import _diff_stats

    diff = (
        "diff --git a/x.py b/x.py\n"
        "--- a/x.py\n"
        "+++ b/x.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-old\n"
        f"+a{separator}-b{separator}+c\n"
    )

    assert _changed_line_count(diff) == 2
    assert _line_counts(diff) == (1, 1)
    stats = _diff_stats(diff)
    assert (stats["lines_added"], stats["lines_deleted"]) == (1, 1)
