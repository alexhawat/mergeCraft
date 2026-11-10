"""Workflow contracts for CI speedup (path skips, sharded coverage, artifacts)."""

from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING

import pytest

from tests.ci.workflow_support import REPO_ROOT, job, load_workflow, read_text

if TYPE_CHECKING:
    from pathlib import Path


def test_ci_has_pr_classifier_and_sharded_coverage_gate() -> None:
    doc = load_workflow("ci.yml")
    assert "changes" in (doc.get("jobs") or {})
    text = read_text(".github/workflows/ci.yml")
    assert job(doc, "changes")["uses"] == "./.github/workflows/classify-pr.yml"
    assert "ci_pr_touches_code.py" in read_text(".github/workflows/classify-pr.yml")
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


def test_integration_waits_for_head_coverage_before_the_ratchet() -> None:
    steps = job(load_workflow("integration.yml"), "integration-pr")["steps"]
    names = [step.get("name") for step in steps]
    assert "Integration suite" not in names, "ci.yml deterministic-integration runs it once"
    assert names.index("Fetch base coverage (cache or ci-cd artifact)") < names.index(
        "Coverage ratchet"
    )
    assert names.index("Fetch head coverage from ci.yml artifact") < names.index("Coverage ratchet")


def test_delivery_gate_enables_complete_parallel_coverage() -> None:
    steps = job(load_workflow("ci-cd.yml"), "verify")["steps"]
    gate = next(step for step in steps if step.get("run") == "make ci")
    assert gate["env"]["MERGECRAFT_TEST_SPLITS"] == "2"
    assert "MERGECRAFT_TEST_GROUP" not in gate["env"], "delivery must never gate one partial shard"


@pytest.mark.parametrize("event", ["push", "workflow_dispatch"])
@pytest.mark.parametrize("exit_code", [0, 42])
def test_non_pr_coverage_uses_parallel_gate_and_propagates_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, event: str, exit_code: int
) -> None:
    """Execute the wrapper with a fake Make boundary; no base measurement may run."""
    make = tmp_path / "make"
    make.write_text(
        '#!/bin/sh\nprintf "%s:%s\\n" "$*" "$MERGECRAFT_TEST_SPLITS"\nexit "$STUB_MAKE_RC"\n'
    )
    make.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("GITHUB_EVENT_NAME", event)
    monkeypatch.setenv("STUB_MAKE_RC", str(exit_code))
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts/ci_coverage_delta_gate.sh")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == exit_code
    assert result.stdout.strip() == "coverage-gate:2"


def test_mypy_cache_cannot_restore_across_incompatible_toolchains() -> None:
    steps = job(load_workflow("ci.yml"), "static")["steps"]
    cache = next(step for step in steps if step.get("with", {}).get("path") == ".mypy_cache")
    options = cache["with"]
    prefix = options["restore-keys"].strip()
    assert len(options["restore-keys"].splitlines()) == 1
    for component in (
        "${{ runner.os }}",
        "${{ runner.arch }}",
        "${{ matrix.python }}",
        "${{ hashFiles('uv.lock', 'pyproject.toml') }}",
    ):
        assert component in prefix
    assert options["key"] == prefix + "${{ github.sha }}"
    static = next(step for step in steps if step.get("run") == "make ci-static")
    assert steps.index(cache) < steps.index(static)
    assert cache["if"] == static["if"]
