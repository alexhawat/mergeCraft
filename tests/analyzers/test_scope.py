"""Diff scoping and ``introduced_by_pr`` semantics (D6)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

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
index 1111111..2222222 100644
--- a/README.md
+++ b/README.md
@@ -1,3 +1,4 @@
 # Title
+added line
 unchanged
diff --git a/src/app.py b/src/app.py
index 3333333..4444444 100644
--- a/src/app.py
+++ b/src/app.py
@@ -10,1 +10,2 @@
 def run():
+    return 1
"""
    added = list(scope.iter_added_diff_lines(diff))
    assert added == [
        ("README.md", 2, "added line"),
        ("src/app.py", 11, "    return 1"),
    ]


# --------------------------------------------------------------------------- #
# #269 — ``base_comparison_available`` returns ``offline`` instead of
# ``not offline``.
#
# This is not a cosmetic inversion. ``pipeline.py:361`` feeds the result into
# ``_apply_baseline_suppression(..., base_run_performed=base_run)``, which hands
# it to ``annotate_introduced_by_pr``. Today an **online** ``baseComparison:
# full`` run annotates as if no base comparison happened, and an **offline** run
# claims one did. The consumer cases below exist so a future refactor cannot
# reintroduce the wrong attribution one layer up while the pure function stays
# correct. W12 fixes it.
# --------------------------------------------------------------------------- #


@pytest.mark.xfail(
    reason="green after W12: base_comparison_available returns `offline` (#269)",
    strict=False,
)
def test_base_comparison_available_is_true_when_online_and_full() -> None:
    scope = import_module("mergecraft.analyzers.scope")
    assert scope.base_comparison_available(base_comparison="full", offline=False) is True


@pytest.mark.xfail(
    reason="green after W12: base_comparison_available returns `offline` (#269)",
    strict=False,
)
def test_base_comparison_available_is_false_when_offline_and_full() -> None:
    scope = import_module("mergecraft.analyzers.scope")
    assert scope.base_comparison_available(base_comparison="full", offline=True) is False


@pytest.mark.parametrize("base_comparison", ["diff", "none", ""])
@pytest.mark.parametrize("offline", [False, True])
def test_base_comparison_available_is_false_unless_comparison_is_full(
    base_comparison: str, offline: bool
) -> None:
    """The ``!= "full"`` short-circuit is untouched by W12 — guard it."""
    scope = import_module("mergecraft.analyzers.scope")
    assert (
        scope.base_comparison_available(base_comparison=base_comparison, offline=offline) is False
    )


def _record_base_run_performed(monkeypatch: pytest.MonkeyPatch, pipeline: Any) -> list[bool]:
    """Capture what ``pipeline`` actually hands ``annotate_introduced_by_pr``."""
    recorded: list[bool] = []
    real = pipeline.annotate_introduced_by_pr

    def _recording(
        findings: list[Any], *, base_run_performed: bool, is_new_in_base: bool = False
    ) -> list[Any]:
        recorded.append(base_run_performed)
        return real(  # type: ignore[no-any-return]
            findings,
            base_run_performed=base_run_performed,
            is_new_in_base=is_new_in_base,
        )

    monkeypatch.setattr(pipeline, "annotate_introduced_by_pr", _recording)
    return recorded


def _run_full_comparison_pipeline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, offline: bool
) -> list[bool]:
    from mergecraft.analyzers import adapters, pipeline
    from mergecraft.analyzers.registry import get_manifest

    settings_mod = import_module("mergecraft.config.settings")
    monkeypatch.setattr(
        pipeline,
        "_analyzers_settings",
        lambda _root: settings_mod.AnalyzersSettings(baseComparison="full"),
    )
    monkeypatch.setattr(pipeline, "detect_enabled", lambda **_: [get_manifest("ruff")])

    finding = _sample_finding("src/fixture_app/handler.py", 12)
    monkeypatch.setattr(
        adapters,
        "run_adapter",
        lambda **_: adapters.AdapterRunResult(findings=[finding], skipped=False),
    )

    recorded = _record_base_run_performed(monkeypatch, pipeline)
    pipeline.run_analyzer_pipeline(
        repo_root=tmp_path,
        changed_files=["src/fixture_app/handler.py"],
        tier="trusted",
        offline=offline,
        shell="restricted",
    )
    assert recorded, "the pipeline never reached annotate_introduced_by_pr"
    return recorded


@pytest.mark.xfail(
    reason="green after W12: online full comparison reaches the annotator as False (#269)",
    strict=False,
)
def test_online_full_comparison_reaches_the_annotator_as_performed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The live bug: an online ``full`` run must claim the base comparison ran."""
    recorded = _run_full_comparison_pipeline(monkeypatch, tmp_path, offline=False)
    assert recorded == [True]


@pytest.mark.xfail(
    reason="green after W12: offline full comparison reaches the annotator as True (#269)",
    strict=False,
)
def test_offline_full_comparison_never_claims_a_base_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The mirror image: offline cannot have compared against base."""
    recorded = _run_full_comparison_pipeline(monkeypatch, tmp_path, offline=True)
    assert recorded == [False]
