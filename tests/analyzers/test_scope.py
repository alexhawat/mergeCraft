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
