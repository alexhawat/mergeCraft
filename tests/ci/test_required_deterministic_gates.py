"""The existing required static context cannot go green after a failed artifact lane."""

from __future__ import annotations

import json
import os
import subprocess

import pytest

from tests.ci.workflow_support import as_list, job, load_workflow, workflow_on

_PREREQUISITES = {
    "changes",
    "toolchain",
    "deployment-candidate",
    "eval-gate",
    "privilege-root",
    "deterministic-integration",
    "action-e2e",
    "image-scan-slim",
    "image-scan-analyzers",
}


@pytest.mark.parametrize("failed_job", sorted(_PREREQUISITES))
@pytest.mark.parametrize("status", ["success", "failure", "cancelled", "skipped"])
def test_actual_required_guard_rejects_unsuccessful_dependency(
    failed_job: str, status: str
) -> None:
    spec = job(load_workflow("ci.yml"), "static")
    assert set(as_list(spec["needs"])) == _PREREQUISITES
    assert spec["if"] == "always()"
    guard = spec["steps"][0]
    results = {name: {"result": "success"} for name in _PREREQUISITES}
    results[failed_job]["result"] = status
    run = subprocess.run(
        ["bash", "-ec", guard["run"]],
        env={**os.environ, "REQUIRED_JOB_RESULTS": json.dumps(results)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert (run.returncode == 0) == (status == "success"), run.stdout + run.stderr
    if status != "success":
        assert failed_job in run.stderr


def test_required_artifact_lane_is_reusable_keyless_and_not_duplicated() -> None:
    ci = load_workflow("ci.yml")
    e2e = job(ci, "action-e2e")
    assert e2e["uses"] == "./.github/workflows/e2e.yml"
    assert e2e["with"] == {"required-security": True, "image-artifact": "mergecraft-slim-image"}
    assert "secrets" not in e2e
    assert "pull_request" not in workflow_on(load_workflow("e2e.yml"))
    integration = job(ci, "deterministic-integration")
    assert integration["strategy"]["matrix"]["python"] == ["3.11", "3.14"]
    assert any(step.get("run") == "make test-integration" for step in integration["steps"])
    assert "secrets" not in json.dumps(integration)


@pytest.mark.parametrize("verifier", ["success", "failure", "cancelled", "skipped"])
def test_image_only_required_guard_still_requires_verified_candidate(verifier: str) -> None:
    guard = job(load_workflow("ci.yml"), "static")["steps"][0]["run"]
    results: dict[str, dict[str, object]] = {name: {"result": "skipped"} for name in _PREREQUISITES}
    results["changes"] = {"result": "success", "outputs": {"image_only": "true"}}
    results["deployment-candidate"] = {"result": verifier}
    run = subprocess.run(
        ["bash", "-ec", guard],
        env={**os.environ, "REQUIRED_JOB_RESULTS": json.dumps(results)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert (run.returncode == 0) == (verifier == "success")
