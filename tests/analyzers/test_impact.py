"""Tests for change-impact extraction (S6 / #94).

Covers declaration extraction, hunk filtering, cross-file references,
and the ``impactPath`` artifact contract.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from mergecraft.analyzers.impact import (
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


def test_extract_impact_returns_declarations_within_hunks() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src"
        src.mkdir()
        # existing_func @ line 1, new_func @ line 5. Hunk range 1-4.
        txt = "def existing_func():\n    pass\n\n\ndef new_func():\n    return 42\n"
        (src / "example.py").write_text(txt)
        result = extract_impact(_SAMPLE_DIFF, tmp)
        rows = result["impactPath"]
        decl_names = [r["declaration"] for r in rows if r["file"] == "src/example.py"]
        assert "existing_func" in decl_names, "Missing existing_func"
        assert "new_func" not in decl_names, "new_func should be excluded"
        assert result["totalDeclarations"] > 0


def test_hunk_filter_excludes_unchanged_declarations() -> None:
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
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src"
        src.mkdir()
        txt = "def stale():\n    pass\n\n\ndef unchanged():\n    pass\n\n\ndef updated():\n    return 42\n\n\ndef changed():\n    return True\n"
        (src / "app.py").write_text(txt)
        result = extract_impact(diff, tmp)
        decl_names = {r["declaration"] for r in result["impactPath"]}
        assert "changed" in decl_names
        assert "stale" not in decl_names
        assert "unchanged" not in decl_names
        assert "updated" not in decl_names


def test_empty_diff_returns_empty() -> None:
    result = extract_impact("", "/tmp")
    assert result["totalDeclarations"] == 0
    assert result["impactPath"] == []


def test_write_impact_returns_none_when_empty() -> None:
    assert write_impact("", "/tmp", "/tmp", 1) is None


def test_write_impact_writes_json_when_nonempty() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src"
        src.mkdir()
        (src / "example.py").write_text("def f():\n    pass\n")
        diff_parts = ["diff --git a/src/example.py b/src/example.py"]
        diff_parts.append("index a..b 100644")
        diff_parts.append("--- a/src/example.py")
        diff_parts.append("+++ b/src/example.py")
        diff_parts.append("@@ -1 +1,2 @@")
        diff_parts.append(" def f():")
        diff_parts.append("+    pass")
        diff = "\n".join(diff_parts)
        written = write_impact(diff, tmp, tmp, 42)
        assert written is not None
        assert written["impactPath"].endswith("pr-42-impact.json")
        assert written["impactDeclarationCount"] == 1
        data = json.loads(Path(written["impactPath"]).read_text())
        assert data["impactPath"][0]["declaration"] == "f"


def test_extract_impact_respects_max_declarations() -> None:
    from mergecraft.analyzers.impact import _MAX_DECLARATIONS

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src"
        src.mkdir()
        diff_parts = []
        for i in range(_MAX_DECLARATIONS + 5):
            mod_parts = [f"diff --git a/src/mod_{i}.py b/src/mod_{i}.py"]
            mod_parts.append("index a..b 100644")
            mod_parts.append("--- /dev/null")
            mod_parts.append(f"+++ b/src/mod_{i}.py")
            mod_parts.append("@@ -0,0 +1,2 @@")
            mod_parts.append(f"+def func_{i}():")
            mod_parts.append("+    pass")
            diff_parts.append("\n".join(mod_parts))
            (src / f"mod_{i}.py").write_text(f"def func_{i}():\n    pass\n")
        diff = "\n".join(diff_parts)
        result = extract_impact(diff, tmp)
        assert result["truncated"] is True
        assert len(result["impactPath"]) == _MAX_DECLARATIONS
        assert result["totalDeclarations"] == _MAX_DECLARATIONS + 5


def test_extract_impact_missing_file_does_not_crash() -> None:
    diff = "diff --git a/phantom.py b/phantom.py\nindex a..b 100644\n--- /dev/null\n+++ b/phantom.py\n@@ -0,0 +1 @@\n+def phantom():\n+    pass\n"
    result = extract_impact(diff, "/tmp/nonexistent")
    assert result["totalDeclarations"] == 0
    assert result["impactPath"] == []


def test_cross_file_references_include_usages_in_git_repo(tmp_path: Path) -> None:
    """A real git repo: usages of a changed declaration in other files appear.

    Guards the ``git grep`` subprocess path (path:line:content parsing,
    exclude_file filtering, and the -w word match). The declaration file
    itself is excluded; cross-file usages are kept."""
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "dev@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "config", "user.name", "Dev"], cwd=repo, check=True, capture_output=True)

    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("def changed():\n    return True\n")
    (repo / "src" / "consumer.py").write_text("from app import changed\nresult = changed()\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

    diff = """diff --git a/src/app.py b/src/app.py
index a..b 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1,2 @@
 def changed():
+    return True
"""

    result = extract_impact(diff, str(repo))
    rows = result["impactPath"]
    app_row = next(r for r in rows if r["file"] == "src/app.py")
    assert app_row["declaration"] == "changed"
    ref_files = [ref["file"] for ref in app_row["references"]]
    assert "src/consumer.py" in ref_files, f"expected consumer.py ref in {ref_files}"
    assert "src/app.py" not in ref_files, "declaration file must be excluded from references"
    ref = next(ref for ref in app_row["references"] if ref["file"] == "src/consumer.py")
    assert ref["line"] == 1, f"expected line 1 (from app import changed) but got {ref}"
    ref_lines = [ref["line"] for ref in app_row["references"] if ref["file"] == "src/consumer.py"]
    assert 1 in ref_lines, f"expected import usage (line 1) in {ref_lines}"
    assert 2 in ref_lines, f"expected call usage (line 2) in {ref_lines}"


def test_cross_file_references_word_match_excludes_substrings(tmp_path: Path) -> None:
    """-w word match: a declaration name must not match inside a longer identifier."""
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "dev@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "config", "user.name", "Dev"], cwd=repo, check=True, capture_output=True)

    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("def run():\n    return 1\n")
    (repo / "src" / "runner.py").write_text("def runner():\n    return run()\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

    diff = """diff --git a/src/app.py b/src/app.py
index a..b 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1,2 @@
 def run():
+    return 1
"""

    result = extract_impact(diff, str(repo))
    rows = result["impactPath"]
    app_row = next(r for r in rows if r["file"] == "src/app.py")
    assert app_row["declaration"] == "run"
    # "runner" contains "run" but -w must exclude it; only "return run()" matches.
    ref_lines = [ref["line"] for ref in app_row["references"]]
    assert ref_lines == [2], f"expected only the exact-symbol reference at line 2, got {ref_lines}"
