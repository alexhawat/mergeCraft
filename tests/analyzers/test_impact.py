"""Tests for change-impact extraction (S6 / #94).

Covers the ``analyzers.impact`` config toggle, the declaration-extraction
logic, and the ``impactPath`` artifact contract.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from mergecraft.analyzers.impact import _changed_paths, extract_impact, write_impact

# A minimal diff that touches two files with known declarations.
_SAMPLE_DIFF = """diff --git a/src/example.py b/src/example.py
index abc..def 100644
--- a/src/example.py
+++ b/src/example.py
@@ -1,3 +1,4 @@
 def existing_func():
     pass
+
+def new_func():
+    return 42
diff --git a/src/util.ts b/src/util.ts
index 111..222 100644
--- a/src/util.ts
+++ b/src/util.ts
@@ -1,2 +1,5 @@
 export const CONSTANT = 1
+
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


def test_extract_impact_returns_declarations() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src"
        src.mkdir()
        (src / "example.py").write_text(
            "def existing_func():\n    pass\n\n\ndef new_func():\n    return 42\n"
        )
        (src / "util.ts").write_text(
            'export const CONSTANT = 1\n\n\nexport function helper(): string {\n    return "hello"\n}\n'
        )

        result = extract_impact(_SAMPLE_DIFF, tmp)
        rows = result["impactPath"]
        assert isinstance(rows, list)
        # Should find: existing_func, new_func (python), CONSTANT, helper (ts)
        names = {(r["file"], r["declaration"]) for r in rows}
        assert ("src/example.py", "existing_func") in names, names
        assert ("src/example.py", "new_func") in names, names
        assert ("src/util.ts", "CONSTANT") in names
        assert ("src/util.ts", "helper") in names
        assert result["totalDeclarations"] == 4
        assert result["truncated"] is False


def test_extract_impact_readme_has_no_declarations() -> None:
    """Markdown files have no recognised patterns and contribute zero rows."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src"
        src.mkdir()
        (src / "example.py").write_text("def f():\n    pass\n")
        result = extract_impact(
            "diff --git a/README.md b/README.md\nindex a..b 100644\n--- /dev/null\n+++ b/README.md\n@@ -0,0 +1 @@\n+# readme\n",
            tmp,
        )
        rows = result["impactPath"]
        assert isinstance(rows, list)
        assert len(rows) == 0, "README.md should contribute no declarations"
        assert result["totalDeclarations"] == 0


def test_extract_impact_empty_diff_returns_empty() -> None:
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
        diff = "diff --git a/src/example.py b/src/example.py\nindex a..b 100644\n--- a/src/example.py\n+++ b/src/example.py\n@@ -1 +1,2 @@\n def f():\n+    pass\n"

        written = write_impact(diff, tmp, tmp, 42)
        assert written is not None
        assert written["impactPath"].endswith("pr-42-impact.json")
        assert written["impactDeclarationCount"] == 1
        assert written["impactTruncated"] is False

        data = json.loads(Path(written["impactPath"]).read_text(encoding="utf-8"))
        assert len(data["impactPath"]) == 1
        assert data["impactPath"][0]["declaration"] == "f"


def test_extract_impact_respects_max_declarations() -> None:
    """When more than _MAX_DECLARATIONS declarations exist, truncated is True."""
    from mergecraft.analyzers.impact import _MAX_DECLARATIONS

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src"
        src.mkdir()
        lines: list[str] = []
        diff_parts: list[str] = []
        for i in range(_MAX_DECLARATIONS + 5):
            lines.append(f"def func_{i}():\n    pass\n")
            diff_parts.append(
                f"diff --git a/src/mod_{i}.py b/src/mod_{i}.py\n"
                f"index a..b 100644\n"
                f"--- /dev/null\n"
                f"+++ b/src/mod_{i}.py\n"
                f"@@ -0,0 +1,2 @@\n"
                f"+def func_{i}():\n+    pass\n"
            )
            (src / f"mod_{i}.py").write_text(f"def func_{i}():\n    pass\n")

        diff = "\n".join(diff_parts)
        result = extract_impact(diff, tmp)
        assert result["truncated"] is True
        assert len(result["impactPath"]) == _MAX_DECLARATIONS
        assert result["totalDeclarations"] == _MAX_DECLARATIONS + 5


def test_extract_impact_missing_file_does_not_crash() -> None:
    """A diff referencing a file not checked out should be skipped, not crash."""
    diff = "diff --git a/phantom.py b/phantom.py\nindex a..b 100644\n--- /dev/null\n+++ b/phantom.py\n@@ -0,0 +1 @@\n+def phantom():\n+    pass\n"
    result = extract_impact(diff, "/tmp/nonexistent")
    assert result["totalDeclarations"] == 0
    assert result["impactPath"] == []
