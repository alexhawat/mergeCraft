"""Workflow contracts for CI speedup (path skips, sharded coverage, artifacts)."""

from __future__ import annotations

from tests.ci.workflow_support import load_workflow, read_text


def test_ci_has_pr_classifier_and_sharded_coverage_gate() -> None:
    doc = load_workflow("ci.yml")
    assert "changes" in (doc.get("jobs") or {})
    text = read_text(".github/workflows/ci.yml")
    assert "ci_pr_touches_code.py" in text
    assert 'MERGECRAFT_TEST_SPLITS: "2"' in text
    assert "mergecraft-coverage-json" in text


def test_integration_reuses_coverage_artifacts() -> None:
    text = read_text(".github/workflows/integration.yml")
    assert "ci_fetch_coverage_artifact.sh" in text
    assert "MERGECRAFT_HEAD_COVERAGE_PATH" in text
    assert "MERGECRAFT_BASE_COVERAGE_PATH" in text
    assert "github.event.pull_request.head.sha" in text
    assert "lookup-only" not in text
    assert "path: coverage.json" in text
    assert "mergecraft-coverage-main-${{ github.event.pull_request.base.sha }}" in text
