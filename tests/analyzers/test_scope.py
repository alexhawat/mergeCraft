"""Diff scoping and ``introduced_by_pr`` semantics (D6)."""

from __future__ import annotations

from pathlib import Path

from tests.analyzers.support import import_module


def _sample_finding(path: str, line: int) -> object:
    finding_mod = import_module("mergecraft.analyzers.finding")
    return finding_mod.make_finding(
        tool="actionlint",
        rule_id="syntax-check",
        category="Maintainability & Code Quality",
        severity="Major",
        confidence="likely",
        message="issue",
        path=path,
        start_line=line,
        end_line=line,
        source="analyzer",
        introduced_by_pr="unknown",
    )


def test_finding_outside_diff_hunks_is_dropped() -> None:
    scope = import_module("mergecraft.analyzers.scope")
    diff = """diff --git a/README.md b/README.md
@@ -1,3 +1,4 @@
 # Title
+added line
 unchanged
"""
    finding = _sample_finding("scripts/deploy.sh", 5)
    kept = scope.filter_to_diff([finding], diff_text=diff)
    assert kept == []


def test_finding_on_changed_line_survives() -> None:
    scope = import_module("mergecraft.analyzers.scope")
    diff = """diff --git a/scripts/deploy.sh b/scripts/deploy.sh
@@ -1,5 +1,5 @@
 #!/usr/bin/env bash
 set -euo pipefail
 TARGET=$1
-echo old
+echo deploying to $TARGET
"""
    finding = _sample_finding("scripts/deploy.sh", 5)
    kept = scope.filter_to_diff([finding], diff_text=diff)
    assert len(kept) == 1


def test_new_dependency_survives_without_line_intersection(fixture_repo: Path) -> None:
    scope = import_module("mergecraft.analyzers.scope")
    diff = """diff --git a/requirements.txt b/requirements.txt
@@ -1 +1,2 @@
 requests==2.25.0
+insecure-package==0.0.1
"""
    finding = _sample_finding("requirements.txt", 2)
    kept = scope.apply_scope_exceptions([finding], diff_text=diff, repo_root=fixture_repo)
    assert len(kept) == 1


def test_introduced_by_pr_unknown_when_no_base_run() -> None:
    scope = import_module("mergecraft.analyzers.scope")
    finding = _sample_finding(".github/workflows/broken.yml", 2)
    scoped = scope.annotate_introduced_by_pr([finding], base_run_performed=False)
    assert scoped[0].introduced_by_pr == "unknown"


def test_introduced_by_pr_true_only_with_base_confirmation() -> None:
    scope = import_module("mergecraft.analyzers.scope")
    finding = _sample_finding(".github/workflows/broken.yml", 2)
    scoped = scope.annotate_introduced_by_pr(
        [finding], base_run_performed=True, is_new_in_base=True
    )
    assert scoped[0].introduced_by_pr == "true"


def test_introduced_by_base_diff_uses_line_and_rule_not_message() -> None:
    """Same message on a new line must not inherit base ``introduced_by_pr=false``."""
    scope = import_module("mergecraft.analyzers.scope")
    finding_mod = import_module("mergecraft.analyzers.finding")
    shared = {
        "tool": "ruff",
        "rule_id": "F401",
        "category": "Maintainability & Code Quality",
        "severity": "Minor",
        "confidence": "certain",
        "message": "Unused import os",
        "path": "src/fixture_app/handler.py",
        "source": "analyzer",
    }
    base = finding_mod.make_finding(**shared, start_line=10, end_line=10, introduced_by_pr="false")
    head = finding_mod.make_finding(
        **shared, start_line=20, end_line=20, introduced_by_pr="unknown"
    )

    annotated = scope.introduced_by_base_diff([head], [base])

    assert annotated[0].introduced_by_pr == "true"


def test_filter_generated_scope_drops_generated_findings_without_config_change() -> None:
    """Generated findings on touched paths drop unless generator config changed."""
    scope = import_module("mergecraft.analyzers.scope")
    finding = _sample_finding("src/generated/schema.py", 1)
    diff = """diff --git a/src/generated/schema.py b/src/generated/schema.py
@@ -1 +1,2 @@
 # generated
+extra
"""
    kept = scope.filter_generated_scope([finding], diff_text=diff)
    assert kept == []


def test_filter_generated_scope_keeps_generated_findings_when_config_changed() -> None:
    scope = import_module("mergecraft.analyzers.scope")
    finding = _sample_finding("src/generated/schema.py", 1)
    diff = """diff --git a/Makefile b/Makefile
@@ -1 +1,2 @@
 gen:
+	@echo regen
diff --git a/src/generated/schema.py b/src/generated/schema.py
@@ -1 +1,2 @@
 # generated
+extra
"""
    kept = scope.filter_generated_scope([finding], diff_text=diff)
    assert len(kept) == 1


def test_iter_added_diff_lines_yields_path_line_and_content() -> None:
    scope = import_module("mergecraft.analyzers.scope")
    diff = """diff --git a/README.md b/README.md
@@ -1,3 +1,4 @@
 # Title
+added line
 unchanged
diff --git a/src/app.py b/src/app.py
@@ -10,1 +10,2 @@
 def run():
+    return 1
"""
    added = list(scope.iter_added_diff_lines(diff))
    assert added == [
        ("README.md", 2, "added line"),
        ("src/app.py", 11, "    return 1"),
    ]
