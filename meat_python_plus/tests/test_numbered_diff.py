from meat_python_plus.diffutil import numbered_diff, split_source_lines


SAMPLE = """diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1 +1 @@
-old
+new
"""


def test_numbered_diff_gutter():
    out = numbered_diff(SAMPLE)
    lines = out.splitlines()
    assert lines[0].startswith("1|")
    assert "|diff --git" in lines[0]
    assert lines[-1].endswith("|+new")
    # gutter is display-only width-padded
    assert all("|" in line for line in lines)


def test_split_source_lines_preserves_eol():
    lines = split_source_lines("a\r\nb\n")
    assert lines[0].text == "a"
    assert lines[0].eol == "\r\n"
    assert lines[1].text == "b"
    assert lines[1].eol == "\n"
