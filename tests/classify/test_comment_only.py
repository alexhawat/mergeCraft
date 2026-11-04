"""The ``commentOnly`` recognizer: a ``//`` comment edit in a closed list of languages.

"Only comment lines changed" needs each language's string rules, so the recognizer is
deliberately narrow and refuses whenever it is unsure. It only considers ``//``-comment
languages, chosen by suffix (JSX and TSX are off the list: a JSX text child can start
with ``//`` and render; Rust is off the list: a lifetime's lone quote makes the quote
check unsound); ``Package.swift`` is refused by name. A Java file holding a unicode
escape (``\\u``) and a C-family file holding ``??`` (a trigraph can splice lines) are
refused. A changed line counts only
when it is ``//``, one space, and a purely alphabetic first word that is not a known
directive word, **and** a small lexer over the head-side file confirms the line is
reached outside a string literal. A file is refused outright when it contains a
backtick, a raw-string marker (``r#"``, ``R"``, ``@"``), a ``/*`` anywhere, a quote left
open at the end of a line, or any character outside printable ASCII plus tab and
newline (so ``U+2028``, ``U+2029``, a lone CR and NEL cannot split a line differently
for the lexer and the language). Lines are split on ``\n`` only. A removed line cannot
be checked against the head text, so a removal is refused. ``#``-comment languages
(Python, YAML, shell, Makefile, TOML, INI) and Markdown are never recognised: a line
that starts with ``#`` there can be content. A diff mixing a recognised file with
anything else is not recognised.
"""

from __future__ import annotations

from typing import Any

import pytest

_RECOGNISED_SUFFIXES = (
    ".js",
    ".ts",
    ".go",
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


# ── refused: the line is not provably a comment ───────────────────────────────


def test_a_block_comment_opener_inside_a_string_still_refuses_the_file() -> None:
    """Any ``/*`` refuses the file: no block-comment interplay is trusted, even in a string."""
    path = "src/app.ts"
    head = 'const s = "/*";\n// new note\n'
    diff = _file(path, ' const s = "/*";', "-// old note", "+// new note")
    plain_diff, plain_heads = _comment_edit(path)

    assert _recognize(diff, {path: head}) is False
    assert _recognize(plain_diff, plain_heads) is True


def test_a_closed_block_comment_anywhere_in_the_file_refuses_it() -> None:
    path = "src/App.java"
    head = "/* licence\n   header */\n// new note\nclass App {}\n"
    diff = _file(path, "    header */", "-// old note", "+// new note", " class App {}", start=2)
    plain_diff, plain_heads = _comment_edit(path)

    assert _recognize(diff, {path: head}) is False
    assert _recognize(plain_diff, plain_heads) is True


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
        "src/App.jsx",
        "src/App.tsx",
        "src/lib.rs",
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


# ── hardening: attack fixtures from the comment-only verification probe ──────


def _probe_diff(path: str, base: list[str], head: list[str]) -> str:
    """A one-hunk unified diff over whole files (simple line-by-line alignment)."""
    import difflib

    lines = list(difflib.unified_diff(base, head, f"a/{path}", f"b/{path}", lineterm="", n=3))
    return f"diff --git a/{path} b/{path}\n" + "\n".join(lines) + "\n"


def _probe(path: str, base: str, head: str) -> bool:
    diff = _probe_diff(path, base.split("\n")[:-1], head.split("\n")[:-1])
    return bool(_recognize(diff, {path: head}))


# (id, path, base, head) — verbatim from the probe; each must be refused.
_PROBE_REFUSED: list[tuple[str, str, str, str]] = [
    (
        "fp-legacy-go-build-constraint",
        "src/a.go",
        "// +build linux\n\npackage a\n",
        "// +build ignore\n\npackage a\n",
    ),
    (
        "fp-swift-tools-version",
        "Package.swift",
        "// swift-tools-version:5.5\nimport PackageDescription\n",
        "// swift-tools-version:5.9\nimport PackageDescription\n",
    ),
    (
        "fp-jsx-text-child",
        "src/App.jsx",
        "export const A = () => (\n  <p>\n    // old rendered text\n  </p>\n);\n",
        "export const A = () => (\n  <p>\n    // new rendered text\n  </p>\n);\n",
    ),
    (
        "fp-regex-quote-hides-block-opener",
        "src/a.js",
        "const r = /'/; /* start '\nend */\nlet z = 1;\n",
        "const r = /'/; /* start '\n// edit */ doEvil();\nend */\nlet z = 1;\n",
    ),
    (
        "fp-go-example-output",
        "src/a_test.go",
        'package a\n\nimport "fmt"\n\nfunc ExampleF() {\n\tfmt.Println(1)\n\t// Output: 1\n}\n',
        'package a\n\nimport "fmt"\n\nfunc ExampleF() {\n\tfmt.Println(1)\n\t// Output: 2\n}\n',
    ),
    (
        "fp-gcc-fallthrough-marker",
        "src/a.c",
        "switch (x) {\ncase 1:\n  f();\n  // note\ncase 2:\n  g();\n}\n",
        "switch (x) {\ncase 1:\n  f();\n  // fallthrough\ncase 2:\n  g();\n}\n",
    ),
    (
        "slash-slash-inside-a-string",
        "src/a.js",
        'const s = "a";\nconst t = "// x";\n',
        'const s = "a";\nconst t = "// y";\n',
    ),
    (
        "inside-a-block-comment",
        "src/a.c",
        "int a;\n/*\n// old\n*/\nint b;\n",
        "int a;\n/*\n// new\n*/\nint b;\n",
    ),
    ("python-hash", "src/a.py", "a = 1\n# old\n", "a = 1\n# new\n"),
    ("python-slash-slash", "src/a.py", "a = 1\n// old\n", "a = 1\n// new\n"),
    ("yaml-hash", "cfg.yaml", "a: 1\n# old\n", "a: 1\n# new\n"),
    ("backtick-file", "src/a.js", "const t = `x`;\n// old\n", "const t = `x`;\n// new\n"),
    (
        "go-cgo-preamble",
        "src/a.go",
        'package a\n\n// #include <stdio.h>\n// old\nimport "C"\n',
        'package a\n\n// #include <stdio.h>\n// new\nimport "C"\n',
    ),
    ("comment-turned-into-code", "src/a.js", "// x = 1;\nlet y;\n", "x = 1;\nlet y;\n"),
    ("code-beside-a-comment", "src/a.js", "let a = 1; // old\n", "let a = 2; // old\n"),
    (
        "go-build-directive",
        "src/a.go",
        "//go:build linux\n\npackage a\n",
        "//go:build windows\n\npackage a\n",
    ),
    ("rust-doc-comment", "src/a.rs", "/// old doc\nfn f() {}\n", "/// new doc\nfn f() {}\n"),
    (
        "eslint-pragma",
        "src/a.ts",
        "// eslint-disable-next-line no-eval\neval(x);\n",
        "// eslint-disable-next-line\neval(x);\n",
    ),
    (
        "ts-expect-error",
        "src/a.ts",
        "// note\nlet x: number = 'a' as any;\n",
        "// @ts-expect-error\nlet x: number = 'a' as any;\n",
    ),
    (
        "c-line-continuation-splice",
        "src/a.c",
        "#define X 1 \\\n// old\nint a;\n",
        "#define X 1 \\\n// new\nint a;\n",
    ),
    (
        "ts-triple-slash-reference",
        "src/a.ts",
        '/// <reference path="a.d.ts" />\nlet a;\n',
        '/// <reference path="b.d.ts" />\nlet a;\n',
    ),
    (
        "js-source-mapping-url",
        "dist/a.js",
        "x();\n//# sourceMappingURL=a.map\n",
        "x();\n//# sourceMappingURL=b.map\n",
    ),
    ("kotlin-text-block", "src/A.kt", 'val s = """\n// old\n"""\n', 'val s = """\n// new\n"""\n'),
]


@pytest.mark.parametrize(
    ("path", "base", "head"),
    [case[1:] for case in _PROBE_REFUSED],
    ids=[case[0] for case in _PROBE_REFUSED],
)
def test_every_probe_attack_is_refused(path: str, base: str, head: str) -> None:
    assert _probe(path, base, head) is False


@pytest.mark.parametrize(
    ("path", "base", "head"),
    [
        (
            "src/a.js",
            "let a = 1;\n// old\nlet b = 2;\n",
            "let a = 1;\n// new\nlet b = 2;\n",
        ),
        (
            "src/a.ts",
            'const u = "http://example.com/x";\n// old note\nexport const v = 1;\n',
            'const u = "http://example.com/x";\n// new note\nexport const v = 1;\n',
        ),
    ],
    ids=["js-plain-edit", "url-in-a-string-on-an-unchanged-line"],
)
def test_the_probe_true_positives_are_still_recognised(path: str, base: str, head: str) -> None:
    assert _probe(path, base, head) is True


def test_a_removal_only_comment_diff_is_refused() -> None:
    """A removed line exists only on the base side, so the head text cannot prove it."""
    path = "src/a.go"
    base = "package a\n\n// drop me\nfunc F() {}\n"
    head = "package a\n\nfunc F() {}\n"

    assert _probe(path, base, head) is False
    assert _probe(path, "package a\n\n// old\nfunc F() {}\n", "package a\n\n// new\nfunc F() {}\n")


@pytest.mark.parametrize(
    "separator",
    [" ", " ", "\r", "\x85"],
    ids=["U+2028", "U+2029", "lone-CR", "NEL"],
)
@pytest.mark.parametrize("path", ["src/a.js", "src/a.c"])
def test_a_line_terminator_other_than_newline_refuses_an_added_line(
    separator: str, path: str
) -> None:
    """The language may end the comment at the terminator and run the tail as code."""
    base_line = f"// note{separator}doEvil();"
    diff = (
        f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
        f"@@ -1,2 +1,3 @@\n let a = 1;\n+{base_line}\n let b = 2;\n"
    )
    head = f"let a = 1;\n{base_line}\nlet b = 2;\n"

    assert _recognize(diff, {path: head}) is False


@pytest.mark.parametrize(
    "separator",
    [" ", " ", "\r", "\x85"],
    ids=["U+2028", "U+2029", "lone-CR", "NEL"],
)
@pytest.mark.parametrize("path", ["src/a.js", "src/a.c"])
def test_a_line_terminator_other_than_newline_refuses_a_removed_line(
    separator: str, path: str
) -> None:
    base_line = f"// note{separator}doEvil();"
    diff = (
        f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
        f"@@ -1,3 +1,2 @@\n let a = 1;\n-{base_line}\n let b = 2;\n"
    )

    assert _recognize(diff, {path: "let a = 1;\nlet b = 2;\n"}) is False


def test_the_unicode_line_separator_attack_file_is_refused() -> None:
    """The verifier's runnable fixture: node runs ``doEvil()`` after the U+2028."""
    path = "src/a.js"
    head = (
        "function doEvil(){console.log('EVIL RAN (U+2028)')}\n"
        "let a = 1;\n// note doEvil();\nlet b = 2;\n"
    )
    diff = _file(path, " let a = 1;", "-// note", "+// note doEvil();", " let b = 2;", start=2)

    assert _recognize(diff, {path: head}) is False


def test_a_non_ascii_comment_is_refused() -> None:
    path = "src/app.js"
    diff = _file(path, " int a = 1;", "-// old note", "+// new café note", " int b = 2;")
    heads = {path: "int a = 1;\n// new café note\nint b = 2;\n"}

    assert _recognize(diff, heads) is False


def test_non_ascii_anywhere_in_the_head_text_refuses_the_file() -> None:
    path = "src/app.js"
    diff = _file(path, ' const s = "naïve";', "-// old note", "+// new note")
    heads = {path: 'const s = "naïve";\n// new note\n'}

    assert _recognize(diff, heads) is False


def test_a_crlf_file_is_refused() -> None:
    path = "src/app.js"
    diff = _file(path, " int a = 1;\r", "-// old note\r", "+// new note\r", " int b = 2;\r")
    heads = {path: "int a = 1;\r\n// new note\r\nint b = 2;\r\n"}

    assert _recognize(diff, heads) is False


def test_a_tab_indented_comment_is_still_recognised() -> None:
    path = "src/lib.go"
    diff = _file(path, " func F() {", "-\t// old note", "+\t// new note", " }")
    heads = {path: "func F() {\n\t// new note\n}\n"}

    assert _recognize(diff, heads) is True


def test_package_swift_is_refused_by_name() -> None:
    """``Package.swift`` is a manifest: its first comment line is read by SwiftPM."""
    manifest_diff, manifest_heads = _comment_edit("Package.swift")
    module_diff, module_heads = _comment_edit("Sources/App/Module.swift")

    assert _recognize(manifest_diff, manifest_heads) is False
    assert _recognize(module_diff, module_heads) is True


def test_a_quote_left_open_at_the_end_of_a_line_refuses_the_file() -> None:
    """A regex literal holding a quote is not modelled; the open quote proves nothing."""
    path = "src/app.js"
    diff = _file(path, " const r = /'/;", "-// old note", "+// new note")
    heads = {path: "const r = /'/;\n// new note\n"}
    plain_diff, plain_heads = _comment_edit(path)

    assert _recognize(diff, heads) is False
    assert _recognize(plain_diff, plain_heads) is True


def test_a_cgo_file_is_refused() -> None:
    path = "src/a.go"
    diff = _file(path, ' import "C"', "-// old note", "+// new note")
    heads = {path: 'import "C"\n// new note\n'}
    plain_diff, plain_heads = _comment_edit(path)

    assert _recognize(diff, heads) is False
    assert _recognize(plain_diff, plain_heads) is True


def _comment_to(path: str, comment: str) -> tuple[str, dict[str, str]]:
    diff = _file(path, " int a = 1;", "-// old note", f"+{comment}", " int b = 2;")
    return diff, {path: f"int a = 1;\n{comment}\nint b = 2;\n"}


@pytest.mark.parametrize(
    ("path", "comment"),
    [
        ("src/Main.java", "//noinspection SpellCheckingInspection"),
        ("src/a.go", "// +build linux"),
        ("src/a.go", "//go:generate stringer -type=Kind"),
        ("src/a.js", "// $FlowFixMe"),
        ("src/a.ts", "// @ts-ignore"),
        ("src/a_test.go", "// Output: 1"),
        ("src/Module.swift", "// swift-tools-version:5.9"),
        ("src/a.ts", "// eslint-disable"),
        ("src/A.kt", "// ktlint-disable"),
        ("src/Main.java", "// CHECKSTYLE:OFF"),
        ("src/a.js", "//no space after the slashes"),
        ("src/a.js", "//  two spaces before the word"),
        ("src/a.js", "// 2 is not a word"),
    ],
    ids=[
        "prefix-noinspection",
        "prefix-plus-build",
        "prefix-go-directive",
        "prefix-flow-fixme",
        "prefix-ts-ignore",
        "prefix-go-output",
        "prefix-swift-tools-version",
        "prefix-eslint-disable",
        "prefix-ktlint-disable",
        "prefix-checkstyle-off",
        "prefix-no-space",
        "prefix-two-spaces",
        "prefix-digit-first",
    ],
)
def test_a_comment_whose_first_token_is_not_a_plain_word_is_refused(
    path: str, comment: str
) -> None:
    """The shape rule: ``//``, one space, then a purely alphabetic first token."""
    diff, heads = _comment_to(path, comment)
    plain_diff, plain_heads = _comment_to(path, "// Plain words here")

    assert _recognize(diff, heads) is False
    assert _recognize(plain_diff, plain_heads) is True


@pytest.mark.parametrize(
    ("path", "comment"),
    [
        ("src/a.c", "// fallthrough"),
        ("src/a_test.go", "// Output"),
        ("src/a_test.go", "// Unordered output: 1 2"),
        ("src/Main.java", "// NOSONAR"),
        ("src/a.go", "// nolint"),
        ("src/a.go", "// revive disable"),
        ("src/a.go", "// golangci"),
        ("src/a.c", "// pragma once"),
        ("src/a.go", "// build ignore"),
    ],
    ids=[
        "word-fallthrough",
        "word-Output",
        "word-Unordered",
        "word-NOSONAR",
        "word-nolint",
        "word-revive",
        "word-golangci",
        "word-pragma",
        "word-build",
    ],
)
def test_a_comment_whose_first_word_is_a_directive_word_is_refused(path: str, comment: str) -> None:
    diff, heads = _comment_to(path, comment)

    assert _recognize(diff, heads) is False


# ── re-gate: Java unicode escapes, Rust, C trigraphs ──────────────────────────


def _regate(path: str, base: str, head: str) -> bool:
    """The re-gate probe's diff shape: split on newline, keep the trailing empty line."""
    import difflib

    lines = list(
        difflib.unified_diff(
            base.split("\n"), head.split("\n"), f"a/{path}", f"b/{path}", lineterm="", n=3
        )
    )
    diff = f"diff --git a/{path} b/{path}\n" + "\n".join(lines) + "\n"
    return bool(_recognize(diff, {path: head}))


_REGATE_REFUSED: list[tuple[str, str, str, str]] = [
    (
        "A2-java-unicode-escape-newline",
        "src/A.java",
        "class A {\n  // old\n  void f() {}\n}\n",
        "class A {\n  // note \\u000a doEvil();\n  void f() {}\n}\n",
    ),
    (
        "A3-java-unicode-escape-cr",
        "src/A.java",
        "class A {\n  // old\n}\n",
        "class A {\n  // note \\u000d doEvil();\n}\n",
    ),
    (
        "A14-java-unicode-escape-uu",
        "src/B.java",
        "class B {\n  // old\n}\n",
        "class B {\n  // note \\uu000a doEvil();\n}\n",
    ),
    (
        "A4-rust-lifetime-mis-pairs-quotes",
        "src/a.rs",
        "fn f<'a>(y: &'a u8) { let x: &'a u8 = y; let s = \"start '\n// old\"; }\n",
        "fn f<'a>(y: &'a u8) { let x: &'a u8 = y; let s = \"start '\n// edit\"; do_evil(); }\n",
    ),
    (
        "A12-rust-is-off-the-list",
        "src/a.rs",
        "fn f() { let c = '\\''; let s = \"x\"; }\n// old\n",
        "fn f() { let c = '\\''; let s = \"x\"; }\n// new\n",
    ),
    (
        "A13-rust-lifetime-only",
        "src/b.rs",
        "fn f<'a>(x: &'a str) -> &'a str { x }\n// old\n",
        "fn f<'a>(x: &'a str) -> &'a str { x }\n// new\n",
    ),
    (
        "A5-c-trigraph-splice",
        "src/a.c",
        "int a;\n// old\nint b = check();\n",
        "int a;\n// note ??/\nint b = check();\n",
    ),
    (
        "A7-swift-multiline-string",
        "src/a.swift",
        'let s = """\n// old\n"""\n',
        'let s = """\n// new\n"""\n',
    ),
    (
        "A8-kotlin-multiline-string",
        "src/A.kt",
        'val s = """\n// old\n"""\n',
        'val s = """\n// new\n"""\n',
    ),
    ("A9-crlf-file", "src/a.js", "let a;\r\n// old\r\n", "let a;\r\n// new\r\n"),
]


@pytest.mark.parametrize(
    ("path", "base", "head"),
    [case[1:] for case in _REGATE_REFUSED],
    ids=[case[0] for case in _REGATE_REFUSED],
)
def test_every_regate_attack_is_refused(path: str, base: str, head: str) -> None:
    assert _regate(path, base, head) is False


@pytest.mark.parametrize(
    ("path", "base", "head"),
    [
        (
            "src/a.go",
            "package a\n\nfunc F() {\n\t// old note\n}\n",
            "package a\n\nfunc F() {\n\t// new note\n}\n",
        ),
        (
            "src/a.go",
            "package a\n\n// F does x\nfunc F() {}\n",
            "package a\n\n// F does y\nfunc F() {}\n",
        ),
        ("src/a.cs", "class A {}\n// old\n", "class A {}\n// region things\n"),
    ],
    ids=["A10-tab-indented", "A11-go-doc-edit", "A15-csharp-region-word"],
)
def test_the_regate_true_positives_are_still_recognised(path: str, base: str, head: str) -> None:
    assert _regate(path, base, head) is True


def test_rust_is_not_on_the_recognised_suffix_list() -> None:
    from mergecraft.classify import triage

    diff, heads = _comment_edit("src/lib.rs")

    assert ".rs" not in triage.COMMENT_ONLY_SUFFIXES
    assert _recognize(diff, heads) is False


def test_the_recognised_suffix_list_is_exactly_the_closed_list() -> None:
    from mergecraft.classify import triage

    assert set(triage.COMMENT_ONLY_SUFFIXES) == set(_RECOGNISED_SUFFIXES)
    assert set(_RECOGNISED_SUFFIXES) == {
        ".js",
        ".ts",
        ".go",
        ".java",
        ".kt",
        ".c",
        ".h",
        ".cc",
        ".cpp",
        ".hpp",
        ".cs",
        ".swift",
    }


def test_a_java_unicode_escape_on_an_unchanged_head_line_refuses_the_file() -> None:
    """Java translates ``\\uXXXX`` before lexing, so no line of the file can be trusted."""
    path = "src/A.java"
    diff = _file(path, ' String s = "caf\\u00e9";', "-// old note", "+// new note")
    heads = {path: 'String s = "caf\\u00e9";\n// new note\n'}
    plain_diff, plain_heads = _comment_edit(path)

    assert _recognize(diff, heads) is False
    assert _recognize(plain_diff, plain_heads) is True


def test_a_java_unicode_escape_only_on_the_removed_side_refuses_the_edit() -> None:
    path = "src/A.java"
    diff = _file(path, " int a = 1;", "-// old \\u000a doEvil();", "+// new note", " int b = 2;")
    heads = {path: "int a = 1;\n// new note\nint b = 2;\n"}

    assert _recognize(diff, heads) is False


def test_the_compiled_java_unicode_escape_fixture_is_refused() -> None:
    """The verifier compiled this file: ``javac`` runs ``doEvil()`` from the comment."""
    path = "src/A.java"
    head = (
        "class A {\n"
        '  static void doEvil() { System.out.println("EVIL RAN (java \\\\u000a)"); }\n'
        "  public static void main(String[] a) {\n"
        "    // note \\u000a doEvil();\n"
        "  }\n"
        "}\n"
    )
    diff = _file(
        path,
        "   public static void main(String[] a) {",
        "-    // old note",
        "+    // note \\u000a doEvil();",
        "   }",
        start=3,
    )

    assert _recognize(diff, {path: head}) is False


@pytest.mark.parametrize("suffix", [".c", ".h", ".cc", ".cpp", ".hpp"])
def test_a_c_family_file_containing_a_trigraph_marker_is_refused(suffix: str) -> None:
    path = f"src/module{suffix}"
    diff = _file(path, ' const char *q = "what??";', "-// old note", "+// new note")
    heads = {path: 'const char *q = "what??";\n// new note\n'}
    plain_diff, plain_heads = _comment_edit(path)

    assert _recognize(diff, heads) is False
    assert _recognize(plain_diff, plain_heads) is True


def test_the_compiled_trigraph_fixture_is_refused() -> None:
    """The verifier compiled this file with ``-trigraphs``: ``??/`` splices ``check()`` in."""
    path = "src/t.c"
    head = (
        "#include <stdio.h>\n"
        'int check(void) { puts("check ran"); return 1; }\n'
        "int main(void) {\n"
        "  int b = 0;\n"
        "  // note ??/\n"
        "  b = check();\n"
        '  printf("b=%d\\n", b);\n'
        "  return 0;\n"
        "}\n"
    )
    diff = _file(
        path, "   int b = 0;", "-  // old note", "+  // note ??/", "   b = check();", start=4
    )

    assert _recognize(diff, {path: head}) is False


def test_a_trigraph_marker_only_on_the_removed_side_refuses_the_edit() -> None:
    path = "src/a.c"
    diff = _file(path, " int a = 1;", "-// old ??/", "+// new note", " int b = 2;")
    heads = {path: "int a = 1;\n// new note\nint b = 2;\n"}

    assert _recognize(diff, heads) is False


def test_nullish_coalescing_does_not_refuse_a_javascript_file() -> None:
    """The trigraph rule is for the C family; ``??`` is an ordinary JavaScript operator."""
    path = "src/app.js"
    diff = _file(path, " const v = a ?? b;", "-// old note", "+// new note")
    heads = {path: "const v = a ?? b;\n// new note\n"}

    assert _recognize(diff, heads) is True


@pytest.mark.parametrize(
    "separator",
    ["\u2028", "\u2029", "\r", "\x85"],
    ids=["U+2028", "U+2029", "lone-CR", "NEL"],
)
@pytest.mark.parametrize("path", ["src/a.js", "src/a.c"])
def test_a_paired_edit_whose_removed_line_hides_code_is_refused(separator: str, path: str) -> None:
    """The diff-side ASCII check, not the removal-only rule, must refuse this edit."""
    head = "let a = 1;\n// note here\nlet b = 2;\n"
    diff = (
        f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
        f"@@ -1,3 +1,3 @@\n let a = 1;\n-// note x{separator}doEvil();\n+// note here\n let b = 2;\n"
    )
    clean = diff.replace(f"x{separator}doEvil();", "x")

    assert _recognize(diff, {path: head}) is False
    assert _recognize(clean, {path: head}) is True
