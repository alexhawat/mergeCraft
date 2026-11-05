"""Whitespace triage must preserve literal values, not just stripped lines."""

from __future__ import annotations

import difflib

import pytest

from mergecraft.classify.triage import recognize_whitespace_only, triage_diff
from mergecraft.config.settings import FastPathSettings


def patch(path: str, before: str, after: str, *, context: int = 3) -> str:
    return f"diff --git a/{path} b/{path}\n" + "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            n=context,
        )
    )


@pytest.mark.parametrize(
    ("path", "before", "after"),
    [
        ("a.py", 'value = """hello   \nworld"""\n', 'value = """hello\nworld"""\n'),
        ("a.py", 'value = """hello\n\nworld"""\n', 'value = """hello\nworld"""\n'),
        ("a.ts", "const value = `hello\n  world`;\n", "const value = `hello\nworld`;\n"),
        ("a.go", "var value = `hello\n  world`\n", "var value = `hello\nworld`\n"),
        ("a.cpp", 'auto value = R"(hello\n  world)";\n', 'auto value = R"(hello\nworld)";\n'),
        ("a.sh", "cat <<EOF\n  world\nEOF\n", "cat <<EOF\nworld\nEOF\n"),
        ("a.js", 'const value = "hello\\\n  world";\n', 'const value = "hello\\\nworld";\n'),
        ("a.js", "const value = <p>\n  world\n</p>;\n", "const value = <p>\nworld\n</p>;\n"),
    ],
)
@pytest.mark.parametrize("context", [0, 3])
def test_literal_or_unmodeled_syntax_gets_full_review(
    path: str, before: str, after: str, context: int
) -> None:
    if path.endswith(".py"):
        old: dict[str, object] = {}
        new: dict[str, object] = {}
        exec(before, old)  # controlled constant fixture
        exec(after, new)  # verifies the changed runtime value
        assert old["value"] != new["value"]
    decision = triage_diff(
        patch(path, before, after, context=context),
        config=FastPathSettings(enabled=True, skip_llm=["whitespace"]),
        head_files={path: after},
    )
    assert decision.tier == "full"


@pytest.mark.parametrize(
    ("path", "before", "after"),
    [
        ("a.py", 'value = """hello\nworld"""   \n\nx = 1\n', 'value = """hello\nworld"""\nx = 1\n'),
        ("a.py", "x = 1   \n", "x = 1\n"),
        ("a.js", "  call();   \n", "    call();\n"),
        ("a.go", "a()\nb()\n\nc()\n", "a()\n\nb()\nc()\n"),
    ],
)
@pytest.mark.parametrize("context", [0, 3])
def test_proven_harmless_changes_still_skip_in_both_directions(
    path: str, before: str, after: str, context: int
) -> None:
    for old, new in ((before, after), (after, before)):
        assert recognize_whitespace_only(
            patch(path, old, new, context=context), head_files={path: new}
        )


def test_missing_or_inconsistent_full_file_cannot_prove_whitespace() -> None:
    diff = patch("a.py", "x = 1   \n", "x = 1\n")
    assert not recognize_whitespace_only(diff)
    assert not recognize_whitespace_only(diff, head_files={"a.py": "x = 2\n"})
    assert not recognize_whitespace_only(
        diff.replace("-1 +1", "-2 +1"), head_files={"a.py": "x = 1\n"}
    )


@pytest.mark.parametrize(
    "metadata",
    ["old mode 100755\nnew mode 100644\n", "new file mode 100644\n", "deleted file mode 100755\n"],
)
def test_mode_changes_are_never_whitespace(metadata: str) -> None:
    diff = patch("a.py", "x = 1   \n", "x = 1\n")
    header, rest = diff.split("\n", 1)
    assert not recognize_whitespace_only(
        f"{header}\n{metadata}{rest}", head_files={"a.py": "x = 1\n"}
    )


@pytest.mark.parametrize(
    ("path", "before", "after"),
    [
        ("run.py", "#!/usr/bin/python3\nx = 1\n", "\n#!/usr/bin/python3\nx = 1\n"),
        ("a.go", "// +build linux\npackage main\n", "// +build linux\n\npackage main\n"),
    ],
)
def test_whitespace_cannot_move_executable_or_build_directives(
    path: str, before: str, after: str
) -> None:
    assert not recognize_whitespace_only(patch(path, before, after), head_files={path: after})
