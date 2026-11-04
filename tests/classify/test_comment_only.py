"""The ``commentOnly`` recognizer: a ``//`` comment edit in a closed list of languages.

"Only comment lines changed" needs each language's string rules, so the recognizer is
deliberately narrow. It only considers ``//``-comment languages, chosen by suffix; a
changed line counts only when, after leading whitespace, it starts with ``//`` **and** a
small lexer over the head-side file confirms the line is reached outside a string
literal or a ``/* */`` block. A file that contains a backtick or a raw-string marker
(``r#"``, ``R"``, ``@"``) is refused outright, because those strings can span lines the
lexer does not model. ``#``-comment languages (Python, YAML, shell, Makefile, TOML, INI)
and Markdown are never recognised: a line that starts with ``#`` there can be content.
A diff mixing a recognised file with anything else is not recognised. Every doubt is
"not recognised", which means a review.
"""

from __future__ import annotations

from typing import Any

import pytest

_RECOGNISED_SUFFIXES = (
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".c",
    ".h",
    ".cc",
    ".cpp",
    ".hpp",
    ".cs",
    ".swift",
)


def _recognize(diff_text: str, head_files: dict[str, str]) -> Any:
    from mergecraft.classify import triage

    return triage.recognize_comment_only(diff_text, head_files=head_files)


def _file(path: str, *lines: str, start: int = 1) -> str:
    old = sum(1 for line in lines if line[:1] in {" ", "-"})
    new = sum(1 for line in lines if line[:1] in {" ", "+"})
    body = "".join(f"{line}\n" for line in lines)
    return (
        f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
        f"@@ -{start},{old} +{start},{new} @@\n{body}"
    )


def _comment_edit(path: str) -> tuple[str, dict[str, str]]:
    """Line 2 of a three-line file goes from one ``//`` comment to another."""
    diff = _file(path, " int a = 1;", "-// old note", "+// new note", " int b = 2;")
    return diff, {path: "int a = 1;\n// new note\nint b = 2;\n"}


# ── recognised ────────────────────────────────────────────────────────────────


def test_a_javascript_comment_edit_is_recognised() -> None:
    diff, heads = _comment_edit("src/app.js")

    assert _recognize(diff, heads) is True


@pytest.mark.parametrize("suffix", _RECOGNISED_SUFFIXES)
def test_every_listed_language_recognises_a_line_comment_edit(suffix: str) -> None:
    diff, heads = _comment_edit(f"src/module{suffix}")

    assert _recognize(diff, heads) is True


def test_an_indented_comment_edit_is_recognised() -> None:
    path = "src/app.ts"
    diff = _file(
        path,
        " function f() {",
        "-    // keep it short",
        "+    // keep it shorter",
        " }",
    )
    heads = {path: "function f() {\n    // keep it shorter\n}\n"}

    assert _recognize(diff, heads) is True


def test_adding_comment_lines_is_recognised() -> None:
    path = "src/lib.go"
    diff = _file(path, " package lib", "+// Package lib does things.", "+// More words.")
    heads = {path: "package lib\n// Package lib does things.\n// More words.\n"}

    assert _recognize(diff, heads) is True


def test_a_comment_edit_in_a_later_hunk_is_located_by_its_new_side_position() -> None:
    path = "src/app.js"
    head = "".join(f"let v{n} = {n};\n" for n in range(1, 10)) + "// after\n"
    diff = _file(path, " let v9 = 9;", "-// before", "+// after", start=9)

    assert _recognize(diff, {path: head}) is True


def test_an_escaped_quote_does_not_leave_the_lexer_inside_a_string() -> None:
    """Without escape handling the string never closes and the comment reads as content."""
    path = "src/app.js"
    head = 'const s = "say \\"hi\\"";\n// new note\n'
    diff = _file(path, ' const s = "say \\"hi\\"";', "-// old note", "+// new note")

    assert _recognize(diff, {path: head}) is True


def test_a_quote_character_literal_does_not_open_a_string() -> None:
    path = "src/main.c"
    head = "char q = '\"';\n// new note\n"
    diff = _file(path, " char q = '\"';", "-// old note", "+// new note")

    assert _recognize(diff, {path: head}) is True


def test_a_block_comment_opener_inside_a_string_does_not_open_a_block() -> None:
    path = "src/app.ts"
    head = 'const s = "/*";\n// new note\n'
    diff = _file(path, ' const s = "/*";', "-// old note", "+// new note")

    assert _recognize(diff, {path: head}) is True


def test_a_closed_block_comment_before_the_edit_is_fine() -> None:
    path = "src/App.java"
    head = "/* licence\n   header */\n// new note\nclass App {}\n"
    diff = _file(path, "    header */", "-// old note", "+// new note", " class App {}", start=2)

    assert _recognize(diff, {path: head}) is True


# ── refused: the line is not provably a comment ───────────────────────────────


def test_a_slash_slash_line_inside_a_continued_string_literal_is_refused() -> None:
    """A backslash line continuation keeps the string open; the ``//`` line is content."""
    path = "src/app.js"
    head = 'const s = "first \\\n// new text \\\nend";\n'
    diff = _file(path, ' const s = "first \\', "-// old text \\", "+// new text \\", ' end";')

    assert _recognize(diff, {path: head}) is False


def test_a_slash_slash_line_inside_a_c_string_continuation_is_refused() -> None:
    path = "src/main.c"
    head = 'const char *s = "first \\\n// new text \\\nend";\n'
    diff = _file(path, ' const char *s = "first \\', "-// old text \\", "+// new text \\", ' end";')

    assert _recognize(diff, {path: head}) is False


def test_a_slash_slash_line_inside_a_block_comment_is_refused() -> None:
    path = "src/app.js"
    head = "/*\n// new note\n*/\nlet a = 1;\n"
    diff = _file(path, " /*", "-// old note", "+// new note", " */")

    assert _recognize(diff, {path: head}) is False


def test_a_block_comment_the_lexer_cannot_close_is_refused() -> None:
    path = "src/app.js"
    head = "/* never closed\nlet a = 1;\n// new note\n"
    diff = _file(path, " let a = 1;", "-// old note", "+// new note", start=2)

    assert _recognize(diff, {path: head}) is False


@pytest.mark.parametrize(
    ("path", "marker_line"),
    [
        ("src/app.js", "const t = `template`;"),
        ("src/app.ts", "const t = `${a}`;"),
        ("src/lib.go", "var raw = `raw string`"),
        ("src/lib.rs", 'let raw = r#"raw"#;'),
        ("src/main.cpp", 'auto raw = R"(raw)";'),
        ("src/Program.cs", 'var path = @"C:\\tmp";'),
    ],
)
def test_a_file_with_a_backtick_or_raw_string_marker_is_refused(
    path: str, marker_line: str
) -> None:
    head = f"{marker_line}\n// new note\n"
    diff = _file(path, f" {marker_line}", "-// old note", "+// new note")

    assert _recognize(diff, {path: head}) is False
    # The same edit without the marker is recognised: the marker is what refuses it.
    plain_head = "int a = 1;\n// new note\n"
    plain_diff = _file(path, " int a = 1;", "-// old note", "+// new note")
    assert _recognize(plain_diff, {path: plain_head}) is True


def test_a_code_line_changed_beside_a_comment_is_refused() -> None:
    path = "src/app.js"
    head = "let a = 2;\n// new note\n"
    diff = _file(path, "-let a = 1;", "+let a = 2;", "-// old note", "+// new note")

    assert _recognize(diff, {path: head}) is False


def test_a_trailing_comment_on_a_code_line_is_refused() -> None:
    path = "src/app.js"
    head = "let a = 1; // new note\n"
    diff = _file(path, "-let a = 1; // old note", "+let a = 1; // new note")

    assert _recognize(diff, {path: head}) is False


def test_turning_a_comment_into_code_is_refused() -> None:
    path = "src/app.js"
    head = "deleteEverything();\n"
    diff = _file(path, "-// deleteEverything();", "+deleteEverything();")

    assert _recognize(diff, {path: head}) is False


def test_an_edit_without_head_text_is_refused() -> None:
    diff, _heads = _comment_edit("src/app.js")

    assert _recognize(diff, {}) is False


def test_head_text_that_does_not_carry_the_added_line_is_refused() -> None:
    """The lexer proves the head file; a head that disagrees with the diff proves nothing."""
    path = "src/app.js"
    diff = _file(path, " int a = 1;", "-// old note", "+// new note", " int b = 2;")
    heads = {path: "int a = 1;\nlaunch();\nint b = 2;\n"}

    assert _recognize(diff, heads) is False


def test_an_empty_diff_is_not_comment_only() -> None:
    assert _recognize("", {}) is False


def test_a_binary_entry_is_not_comment_only() -> None:
    diff = "diff --git a/img.png b/img.png\nBinary files a/img.png and b/img.png differ\n"

    assert _recognize(diff, {}) is False


# ── refused: the language is not on the list ──────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "src/mode.py",
        ".github/workflows/ci.yml",
        "config/app.yaml",
        "docs/guide.md",
        "scripts/run.sh",
        "Makefile",
        "pyproject.toml",
        "config/app.ini",
        "src/style.css",
        "src/app.php",
    ],
)
@pytest.mark.parametrize("marker", ["//", "#"])
def test_a_language_off_the_list_is_never_comment_only(path: str, marker: str) -> None:
    """``#`` lines can be content (prompts, block scalars); ``//`` is floor division in Python."""
    diff = _file(path, " keep", f"-{marker} old", f"+{marker} new")
    heads = {path: f"keep\n{marker} new\n"}

    assert _recognize(diff, heads) is False


def test_a_diff_mixing_a_recognised_file_with_an_unlisted_one_is_refused() -> None:
    js_diff, js_heads = _comment_edit("src/app.js")
    py_diff = _file("src/mode.py", " keep", "-# old", "+# new")
    heads = {**js_heads, "src/mode.py": "keep\n# new\n"}

    assert _recognize(js_diff, js_heads) is True
    assert _recognize(js_diff + py_diff, heads) is False


def test_a_diff_mixing_a_comment_edit_with_a_code_edit_elsewhere_is_refused() -> None:
    js_diff, js_heads = _comment_edit("src/app.js")
    code_diff = _file("src/other.js", "-let a = 1;", "+let a = 2;")
    heads = {**js_heads, "src/other.js": "let a = 2;\n"}

    assert _recognize(js_diff + code_diff, heads) is False


def test_two_recognised_files_together_are_recognised() -> None:
    js_diff, js_heads = _comment_edit("src/app.js")
    go_diff, go_heads = _comment_edit("src/lib.go")

    assert _recognize(js_diff + go_diff, {**js_heads, **go_heads}) is True


# ── wiring into the triage decision ───────────────────────────────────────────


def test_triage_matches_comment_only_and_whitespace_still_does_not() -> None:
    """The whitespace recognizer keeps refusing comment edits; ``commentOnly`` owns them."""
    from mergecraft.classify.triage import recognize_whitespace_only, triage_diff
    from mergecraft.config.settings import FastPathSettings

    diff, heads = _comment_edit("src/app.js")
    config = FastPathSettings.model_validate({"enabled": True, "skipLlm": ["commentOnly"]})

    decision = triage_diff(diff, config=config, head_files=heads, passed_checks=[])

    assert recognize_whitespace_only(diff) is False
    assert (decision.tier, decision.recognizer) == ("skip", "commentOnly")


def test_triage_refuses_a_comment_only_skip_without_head_text() -> None:
    from mergecraft.classify.triage import triage_diff
    from mergecraft.config.settings import FastPathSettings

    diff, _heads = _comment_edit("src/app.js")
    config = FastPathSettings.model_validate({"enabled": True, "skipLlm": ["commentOnly"]})

    decision = triage_diff(diff, config=config, head_files={}, passed_checks=[])

    assert decision.tier == "full"
    assert decision.reason == "no recognizer matches the whole diff"


def test_comment_only_is_exported() -> None:
    from mergecraft.classify import triage

    assert "recognize_comment_only" in triage.__all__
    assert callable(triage.recognize_comment_only)
