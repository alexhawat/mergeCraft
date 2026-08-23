"""Batch HI RED — base-branch coverage gate + merge ref (#432).

Pins D6: gate coverage on push to ``pre-0.0.1`` / ``main``, prefer measuring
``refs/pull/N/merge`` on pull requests, and report delta vs the base branch so
inherited drops are distinguishable from regressions caused by the PR.

Implementation lands in W18 (``.github/workflows/`` + delta script). No
line-touching coverage tests — #432's ruled-out list is binding.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from tests.ci.coverage_base_branch import (
    checkout_uses_merge_ref,
    coverage_delta_report_offense,
    job_runs_coverage_gate,
    load_fixture,
    missing_push_coverage_branches,
    pr_coverage_merge_ref_offense,
    push_coverage_gate_offenses,
    scan_workflows,
)
from tests.ci.workflow_support import REPO_ROOT, job, load_workflow, read_text

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "workflow_coverage_hi"
_INTEGRATION_WORKFLOW = "integration.yml"
_CI_CD_WORKFLOW = "ci-cd.yml"
_DELTA_SCRIPT = REPO_ROOT / "scripts" / "check_coverage_delta.py"


def _install_hi_fixtures(tmp_path: Path) -> Path:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    for src in sorted(_FIXTURES_DIR.glob("*.yml")):
        shutil.copyfile(src, workflows / src.name)
    return workflows


def _load_module(path: Path, module_name: str) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _coverage_json(path: Path, percent: float) -> Path:
    payload = {
        "totals": {
            "percent_covered": percent,
            "num_statements": 100,
            "covered_lines": int(percent),
        },
        "files": {},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class TestFixtureAnchors:
    """Sanity: fixtures model #432 gaps without the production workflows."""

    def test_bad_pr_fixture_scores_head_not_merge(self) -> None:
        offense = pr_coverage_merge_ref_offense(
            load_fixture("pr_head_only.yml"),
            workflow="pr_head_only.yml",
        )
        assert offense is not None
        assert offense.job == "integration-pr"

    def test_good_pr_fixture_checks_merge_ref(self) -> None:
        doc = load_fixture("pr_merge_ref.yml")
        gate_job = job(doc, "integration-pr")
        assert checkout_uses_merge_ref(gate_job)
        assert pr_coverage_merge_ref_offense(doc, workflow="pr_merge_ref.yml") is None

    def test_bad_push_fixture_lacks_coverage_gate(self) -> None:
        offenses = push_coverage_gate_offenses(
            load_fixture("push_no_coverage.yml"),
            workflow="push_no_coverage.yml",
        )
        assert {offense.branch for offense in offenses} == {"main", "pre-0.0.1"}

    def test_good_push_fixture_runs_coverage_gate(self) -> None:
        doc = load_fixture("push_with_coverage.yml")
        assert push_coverage_gate_offenses(doc, workflow="push_with_coverage.yml") == []
        verify = job(doc, "verify")
        assert job_runs_coverage_gate(verify)

    def test_good_delta_fixture_reports_vs_base(self) -> None:
        offense = coverage_delta_report_offense(
            load_fixture("coverage_with_delta.yml"),
            workflow="coverage_with_delta.yml",
        )
        assert offense is None


class TestPushCoverageGateScan:
    """Unit coverage for ``tests.ci.coverage_base_branch``."""

    def test_scan_flags_push_without_coverage_fixture(self, tmp_path: Path) -> None:
        _install_hi_fixtures(tmp_path)
        offenses = scan_workflows(tmp_path)
        flagged = {offense.workflow for offense in offenses}
        assert "push_no_coverage.yml" in flagged

    def test_scan_passes_push_with_coverage_fixture(self, tmp_path: Path) -> None:
        workflows = _install_hi_fixtures(tmp_path)
        (workflows / "push_no_coverage.yml").unlink()
        offenses = scan_workflows(tmp_path)
        assert offenses == []


class TestProductionWorkflows:
    """Integration: real workflows must satisfy D6 after W18."""

    def test_ci_cd_workflow_runs_make_ci_on_push(self) -> None:
        text = read_text(f".github/workflows/{_CI_CD_WORKFLOW}")
        assert "make ci" in text

    def test_repo_has_push_coverage_gate_for_main_and_pre_0_0_1(self) -> None:
        missing = missing_push_coverage_branches(REPO_ROOT)
        assert missing == [], f"push branches missing coverage gate: {missing}"

    def test_integration_pr_coverage_checks_merge_ref(self) -> None:
        offense = pr_coverage_merge_ref_offense(
            load_workflow(_INTEGRATION_WORKFLOW),
            workflow=_INTEGRATION_WORKFLOW,
        )
        assert offense is None, f"integration.yml merge ref: {offense}"

    def test_integration_coverage_reports_delta_vs_base(self) -> None:
        offense = coverage_delta_report_offense(
            load_workflow(_INTEGRATION_WORKFLOW),
            workflow=_INTEGRATION_WORKFLOW,
        )
        assert offense is None, f"integration.yml delta report: {offense}"


class TestCoverageDeltaScript:
    """Unit: inherited-vs-caused attribution via ``check_coverage_delta.py``."""

    def test_check_coverage_delta_script_exists(self) -> None:
        assert _DELTA_SCRIPT.is_file(), (
            f"{_DELTA_SCRIPT.relative_to(REPO_ROOT)} missing — W18 adds delta reporting"
        )

    def test_compare_to_base_marks_inherited_drop(self, tmp_path: Path) -> None:
        if not _DELTA_SCRIPT.is_file():
            pytest.fail("scripts/check_coverage_delta.py missing — W18 adds delta reporting")
        module = _load_module(_DELTA_SCRIPT, "check_coverage_delta")
        compare = getattr(module, "compare_to_base", None)
        assert callable(compare), "check_coverage_delta.compare_to_base missing"

        base = _coverage_json(tmp_path / "base.json", 82.0)
        head = _coverage_json(tmp_path / "head.json", 81.0)
        result = compare(head, base)

        inherited = getattr(result, "inherited", None)
        message = getattr(result, "message", None)
        if inherited is not None:
            assert inherited is True
        elif isinstance(message, str):
            assert "inherited" in message.lower()
        else:
            pytest.fail("compare_to_base must expose inherited or message for attribution")

    def test_compare_to_base_marks_caused_drop(self, tmp_path: Path) -> None:
        if not _DELTA_SCRIPT.is_file():
            pytest.fail("scripts/check_coverage_delta.py missing — W18 adds delta reporting")
        module = _load_module(_DELTA_SCRIPT, "check_coverage_delta_caused")
        compare = getattr(module, "compare_to_base", None)
        assert callable(compare)

        base = _coverage_json(tmp_path / "base.json", 82.0)
        head = _coverage_json(tmp_path / "head.json", 81.5)
        result = compare(head, base)

        inherited = getattr(result, "inherited", None)
        caused = getattr(result, "caused_by_change", None)
        message = getattr(result, "message", None)
        if caused is not None:
            assert caused is True
        elif inherited is not None:
            assert inherited is False
        elif isinstance(message, str):
            assert "inherited" not in message.lower()
        else:
            pytest.fail("compare_to_base must distinguish caused vs inherited drops")


__all__ = [
    "TestCoverageDeltaScript",
    "TestFixtureAnchors",
    "TestProductionWorkflows",
    "TestPushCoverageGateScan",
]
