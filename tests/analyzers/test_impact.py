"""Tests for change-impact extraction (S6 / #94).

Covers declaration extraction via the shipped ast-grep catalog entry, hunk
filtering, cross-file references, reference/declaration truncation, extraction-
failure propagation, and the ``impactPath`` artifact contract.

Declaration extraction always needs the managed ``ast-grep`` binary; the dev
extra pins ``ast-grep-cli`` to the same version as
``analyzers/catalog/ast-grep.yaml`` so it is on ``PATH`` under ``uv run``.
Reference lookup shells out to ``git grep``, so any test that expects
declarations to resolve references needs a real (committed) git repo — a bare
temp dir makes ``git grep`` fail, which is itself exercised as the
extraction-failure path below.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import pytest

from mergecraft.analyzers.impact import (
    _MAX_DECLARATIONS,
    _MAX_REFS,
    _changed_paths,
    _intersects_hunks,
    _parse_hunks,
    extract_impact,
    write_impact,
)

_SAMPLE_DIFF = """diff --git a/src/example.py b/src/example.py
index abc..def 100644
--- a/src/example.py
+++ b/src/example.py
@@ -1,3 +1,4 @@
 def existing_func():
     pass

+def new_func():
+    return 42
diff --git a/src/util.ts b/src/util.ts
index 111..222 100644
--- a/src/util.ts
+++ b/src/util.ts
@@ -1,2 +1,5 @@
 export const CONSTANT = 1

+export function helper(): string {
+    return "hello"
+}
diff --git a/README.md b/README.md
index 000..111 100644
--- /dev/null
+++ b/README.md
@@ -0,0 +1 @@
+# my project
"""


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "dev@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "config", "user.name", "Dev"], cwd=repo, check=True, capture_output=True)
    return repo


def _write_and_commit(repo: Path, files: dict[str, str]) -> None:
    for relpath, content in files.items():
        path = repo / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "add files"], cwd=repo, check=True, capture_output=True
    )


def _added_file_diff(path: str, content: str) -> str:
    """A minimal diff that adds ``path`` wholesale, so every declaration in it
    falls within the (single, whole-file) hunk range."""
    lines = content.splitlines()
    hunk_body = "\n".join(f"+{line}" for line in lines)
    return (
        f"diff --git a/{path} b/{path}\n"
        "index a..b 100644\n"
        "--- /dev/null\n"
        f"+++ b/{path}\n"
        f"@@ -0,0 +1,{len(lines)} @@\n"
        f"{hunk_body}\n"
    )


def test_changed_paths_extracts_post_image_paths() -> None:
    paths = _changed_paths(_SAMPLE_DIFF)
    assert paths == ["src/example.py", "src/util.ts", "README.md"]


def test_parse_hunks_extracts_ranges() -> None:
    hunks = _parse_hunks(_SAMPLE_DIFF)
    assert "src/example.py" in hunks
    assert "src/util.ts" in hunks
    assert "README.md" in hunks
    assert hunks["src/example.py"] == [(1, 4)]
    assert hunks["src/util.ts"] == [(1, 5)]
    assert hunks["README.md"] == [(1, 1)]


def test_intersects_hunks() -> None:
    ranges = [(5, 10), (20, 30)]
    assert _intersects_hunks(5, ranges)
    assert _intersects_hunks(10, ranges)
    assert _intersects_hunks(7, ranges)
    assert not _intersects_hunks(4, ranges)
    assert not _intersects_hunks(11, ranges)
    assert not _intersects_hunks(31, ranges)


def test_extract_impact_returns_declarations_within_hunks(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    # existing_func @ line 1, new_func @ line 7. Hunk range 1-4.
    txt = "def existing_func():\n    pass\n\n\n\n\ndef new_func():\n    return 42\n"
    _write_and_commit(repo, {"src/example.py": txt})
    result = extract_impact(_SAMPLE_DIFF, str(repo))
    assert result is not None
    rows = result["impactPath"]
    decl_names = [r["declaration"] for r in rows if r["file"] == "src/example.py"]
    assert "existing_func" in decl_names, "Missing existing_func"
    assert "new_func" not in decl_names, "new_func should be excluded"
    assert result["totalDeclarations"] > 0


def test_hunk_filter_excludes_unchanged_declarations(tmp_path: Path) -> None:
    diff = """diff --git a/src/app.py b/src/app.py
index a..b 100644
--- a/src/app.py
+++ b/src/app.py
@@ -10,3 +10,4 @@
 def unchanged():
     pass

+def changed():
+    return True
"""
    repo = _git_repo(tmp_path)
    txt = "def stale():\n    pass\n\n\ndef unchanged():\n    pass\n\n\ndef updated():\n    return 42\n\n\ndef changed():\n    return True\n"
    _write_and_commit(repo, {"src/app.py": txt})
    result = extract_impact(diff, str(repo))
    assert result is not None
    decl_names = {r["declaration"] for r in result["impactPath"]}
    assert "changed" in decl_names
    assert "stale" not in decl_names
    assert "unchanged" not in decl_names
    assert "updated" not in decl_names


def test_empty_diff_returns_empty() -> None:
    result = extract_impact("", "/tmp")
    assert result is not None
    assert result["totalDeclarations"] == 0
    assert result["impactPath"] == []


def test_write_impact_returns_none_when_empty() -> None:
    assert write_impact("", "/tmp", "/tmp", 1) is None


def test_write_impact_writes_json_when_nonempty(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    _write_and_commit(repo, {"src/example.py": "def f():\n    pass\n"})
    diff_parts = [
        "diff --git a/src/example.py b/src/example.py",
        "index a..b 100644",
        "--- a/src/example.py",
        "+++ b/src/example.py",
        "@@ -1 +1,2 @@",
        " def f():",
        "+    pass",
    ]
    diff = "\n".join(diff_parts)
    written = write_impact(diff, str(repo), str(tmp_path), 42)
    assert written is not None
    assert written["impactPath"].endswith("pr-42-impact.json")
    assert written["impactDeclarationCount"] == 1
    data = json.loads(Path(written["impactPath"]).read_text())
    assert data["impactPath"][0]["declaration"] == "f"


def test_extract_impact_respects_max_declarations(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    diff_parts = []
    files: dict[str, str] = {}
    for i in range(_MAX_DECLARATIONS + 5):
        mod_parts = [
            f"diff --git a/src/mod_{i}.py b/src/mod_{i}.py",
            "index a..b 100644",
            "--- /dev/null",
            f"+++ b/src/mod_{i}.py",
            "@@ -0,0 +1,2 @@",
            f"+def func_{i}():",
            "+    pass",
        ]
        diff_parts.append("\n".join(mod_parts))
        files[f"src/mod_{i}.py"] = f"def func_{i}():\n    pass\n"
    _write_and_commit(repo, files)
    diff = "\n".join(diff_parts)
    result = extract_impact(diff, str(repo))
    assert result is not None
    assert result["truncated"] is True
    assert len(result["impactPath"]) == _MAX_DECLARATIONS
    assert result["totalDeclarations"] == _MAX_DECLARATIONS + 5


def test_extract_impact_missing_file_does_not_crash() -> None:
    diff = "diff --git a/phantom.py b/phantom.py\nindex a..b 100644\n--- /dev/null\n+++ b/phantom.py\n@@ -0,0 +1 @@\n+def phantom():\n+    pass\n"
    result = extract_impact(diff, "/tmp/nonexistent")
    assert result is not None
    assert result["totalDeclarations"] == 0
    assert result["impactPath"] == []


def test_cross_file_references_include_usages_in_git_repo(tmp_path: Path) -> None:
    """A real git repo: usages of a changed declaration in other files appear.

    Guards the ``git grep`` subprocess path (path:line:content parsing,
    exclude_file filtering, and the -w word match). The declaration file
    itself is excluded; cross-file usages are kept."""
    repo = _git_repo(tmp_path)
    _write_and_commit(
        repo,
        {
            "src/app.py": "def changed():\n    return True\n",
            "src/consumer.py": "from app import changed\nresult = changed()\n",
        },
    )

    diff = """diff --git a/src/app.py b/src/app.py
index a..b 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1,2 @@
 def changed():
+    return True
"""

    result = extract_impact(diff, str(repo))
    assert result is not None
    rows = result["impactPath"]
    app_row = next(r for r in rows if r["file"] == "src/app.py")
    assert app_row["declaration"] == "changed"
    assert app_row["referencesTruncated"] is False
    ref_files = [ref["file"] for ref in app_row["references"]]
    assert "src/consumer.py" in ref_files, f"expected consumer.py ref in {ref_files}"
    assert "src/app.py" not in ref_files, "declaration file must be excluded from references"
    ref_lines = [ref["line"] for ref in app_row["references"] if ref["file"] == "src/consumer.py"]
    assert 1 in ref_lines, f"expected import usage (line 1) in {ref_lines}"
    assert 2 in ref_lines, f"expected call usage (line 2) in {ref_lines}"


def test_cross_file_references_word_match_excludes_substrings(tmp_path: Path) -> None:
    """-w word match: a declaration name must not match inside a longer identifier."""
    repo = _git_repo(tmp_path)
    _write_and_commit(
        repo,
        {
            "src/app.py": "def run():\n    return 1\n",
            "src/runner.py": "def runner():\n    return run()\n",
        },
    )

    diff = """diff --git a/src/app.py b/src/app.py
index a..b 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1,2 @@
 def run():
+    return 1
"""

    result = extract_impact(diff, str(repo))
    assert result is not None
    rows = result["impactPath"]
    app_row = next(r for r in rows if r["file"] == "src/app.py")
    assert app_row["declaration"] == "run"
    # "runner" contains "run" but -w must exclude it; only "return run()" matches.
    ref_lines = [ref["line"] for ref in app_row["references"]]
    assert ref_lines == [2], f"expected only the exact-symbol reference at line 2, got {ref_lines}"


def test_reference_truncation_flag_set_when_capped(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    files = {"src/app.py": "def shared():\n    return 1\n"}
    for i in range(_MAX_REFS + 4):
        files[f"src/consumer_{i}.py"] = "from app import shared\nresult = shared()\n"
    _write_and_commit(repo, files)

    diff = """diff --git a/src/app.py b/src/app.py
index a..b 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1,2 @@
 def shared():
+    return 1
"""
    result = extract_impact(diff, str(repo))
    assert result is not None
    app_row = next(r for r in result["impactPath"] if r["file"] == "src/app.py")
    assert app_row["referencesTruncated"] is True
    assert len(app_row["references"]) == _MAX_REFS


def test_extract_impact_returns_none_when_repo_unavailable_for_references() -> None:
    """No git repo present: declarations resolve fine but git grep cannot run at
    all (not just "no matches"). The whole artifact must be suppressed rather
    than published with silently-empty references (#94 / review finding)."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src"
        src.mkdir()
        (src / "example.py").write_text("def existing_func():\n    pass\n")
        result = extract_impact(_SAMPLE_DIFF, tmp)
        assert result is None


def test_write_impact_omits_key_when_reference_lookup_fails() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src"
        src.mkdir()
        (src / "example.py").write_text("def existing_func():\n    pass\n")
        assert write_impact(_SAMPLE_DIFF, tmp, tmp, 7) is None


def test_extract_impact_returns_none_when_ast_grep_binary_missing(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    _write_and_commit(repo, {"src/example.py": "def existing_func():\n    pass\n"})
    result = extract_impact(
        _SAMPLE_DIFF, str(repo), ast_grep_binary="/nonexistent/ast-grep-binary-xyz"
    )
    assert result is None


_LANGUAGE_FORMS: list[tuple[str, str, set[str]]] = [
    (
        "src/mod.py",
        "class Foo:\n    def method_one(self):\n        pass\n\n\ndef top_level():\n    pass\n",
        {"Foo", "method_one", "top_level"},
    ),
    (
        "src/mod.js",
        "function topFn(x) {\n  return x;\n}\n\nclass Widget {\n  render() {\n    return null;\n  }\n}\n\nconst arrow = (x) => x + 1;\n",
        {"topFn", "Widget", "render", "arrow"},
    ),
    (
        "src/mod.ts",
        "export default class DefaultWidget {\n}\n\nexport interface Props {\n  name: string;\n}\n\nconst arrow = (x: number) => x + 1;\n",
        {"DefaultWidget", "Props", "arrow"},
    ),
    (
        "src/mod.tsx",
        "export function Comp(props: Props) {\n  return null;\n}\n\ninterface Props {\n  name: string;\n}\n",
        {"Comp", "Props"},
    ),
    (
        "src/mod.go",
        "package main\n\nfunc TopFunc(x int) int {\n\treturn x\n}\n\ntype Widget struct {\n\tName string\n}\n\nfunc (w *Widget) Render() string {\n\treturn w.Name\n}\n",
        {"TopFunc", "Widget", "Render"},
    ),
    (
        "src/Mod.java",
        "public class Sample {\n    public void doThing(int x) {\n        System.out.println(x);\n    }\n\n    static class Inner {\n        void innerMethod() {}\n    }\n}\n",
        {"Sample", "doThing", "Inner", "innerMethod"},
    ),
    (
        "src/mod.rs",
        "pub fn top_fn(x: i32) -> i32 {\n    x\n}\n\npub struct Widget {\n    name: String,\n}\n\npub trait Shape {\n    fn area(&self) -> f64;\n}\n",
        {"top_fn", "Widget", "Shape", "area"},
    ),
    (
        "src/mod.c",
        "int top_func(int x) {\n    return x;\n}\n\nstruct Point {\n    int x;\n    int y;\n};\n",
        {"top_func", "Point"},
    ),
    (
        "src/mod.h",
        "int top_func(int x);\n\nstruct Point {\n    int x;\n};\n",
        {"top_func", "Point"},
    ),
    (
        "src/mod.cpp",
        "class Widget {\npublic:\n    void render() {\n    }\n};\n\nstruct Point {\n    int x;\n};\n",
        {"Widget", "render", "Point"},
    ),
]


@pytest.mark.parametrize(("relpath", "content", "expected"), _LANGUAGE_FORMS)
def test_declaration_extraction_covers_representative_forms(
    tmp_path: Path, relpath: str, content: str, expected: set[str]
) -> None:
    """Guards the ast-grep kind-based rules against the forms that tripped up
    the earlier hand-rolled regex table: indented Java methods, Go receiver
    methods, TS export-default classes, .tsx, and Rust trait signatures."""
    repo = _git_repo(tmp_path)
    _write_and_commit(repo, {relpath: content})
    diff = _added_file_diff(relpath, content)
    result = extract_impact(diff, str(repo))
    assert result is not None
    names = {r["declaration"] for r in result["impactPath"]}
    assert expected <= names, f"missing {expected - names} for {relpath}: got {names}"
