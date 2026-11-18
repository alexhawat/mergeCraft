"""The existing required static context cannot go green after a failed artifact lane."""

from __future__ import annotations

import json
import os
import subprocess

import pytest

from tests.ci.workflow_support import as_list, job, load_workflow, workflow_on

_PREREQUISITES = {
    "changes",
    "verify-rules",
    "static-checks",
    "test",
    "security",
    "coverage-gate",
    "toolchain",
    "deployment-candidate",
    "eval-gate",
    "privilege-root",
    "privileged-proofs",
    "deterministic-integration",
    "action-e2e",
    "image-scan-slim",
    "image-scan-analyzers",
}


def test_static_work_starts_without_waiting_for_the_final_gate() -> None:
    ci = load_workflow("ci.yml")
    checks = job(ci, "static-checks")
    gate = job(ci, "static")
    assert as_list(checks["needs"]) == ["changes"]
    assert checks["strategy"]["matrix"]["python"] == ["3.11", "3.14"]
    assert checks["strategy"]["fail-fast"] is False
    assert not checks.get("continue-on-error", False)
    assert checks["runs-on"] == gate["runs-on"] == "ubuntu-latest"
    assert checks["name"] != gate["name"]
    assert any(step.get("run") == "make ci-static" for step in checks["steps"])
    assert len(gate["steps"]) == 1, "the final gate must not repeat the static work"
    assert gate["strategy"]["matrix"]["python"] == ["3.11", "3.14"]
    assert gate["strategy"]["fail-fast"] is False
    assert not gate.get("continue-on-error", False)
    assert not gate["steps"][0].get("continue-on-error", False)


_GATED_ON_RULES = (
    "toolchain",
    "test",
    "deterministic-integration",
    "slim-image",
    "action-e2e",
    "image-scan-slim",
    "image-scan-analyzers",
)
_TIER_THREE_ON_PRS = (
    "deterministic-integration",
    "slim-image",
    "action-e2e",
    "image-scan-slim",
    "image-scan-analyzers",
    "privilege-root",
)


def test_rules_job_always_reports_and_gates_the_expensive_jobs() -> None:
    """Tier 1 (#1493): a rule violation stops the expensive jobs from starting.

    The rules job has no job-level ``if``: a skipped job skips every job that
    needs it, which would fail the required gate on docs-only and image-only PRs.
    """
    ci = load_workflow("ci.yml")
    rules = job(ci, "verify-rules")
    assert "if" not in rules
    assert as_list(rules["needs"]) == ["changes"]
    assert any(
        step.get("run") == "make lint && make typecheck && make lockcheck"
        for step in rules["steps"]
    )
    for name in _GATED_ON_RULES:
        assert "verify-rules" in as_list(job(ci, name)["needs"]), name


def test_tier_three_jobs_still_run_on_code_prs() -> None:
    """No merge queue requires tier 3 yet, so it must keep gating PRs (#1493)."""
    ci = load_workflow("ci.yml")
    assert "merge_group" in workflow_on(ci)
    for name in _TIER_THREE_ON_PRS:
        condition = job(ci, name)["if"]
        assert "needs.changes.outputs.code == 'true'" in condition, name
    for name in set(_TIER_THREE_ON_PRS) - {"slim-image"}:
        assert name in _PREREQUISITES, name


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
    results["verify-rules"] = {"result": "success"}
    for name in ("static-checks", "test", "security", "coverage-gate"):
        results[name] = {"result": "success"}
    results["deployment-candidate"] = {"result": verifier}
    run = subprocess.run(
        ["bash", "-ec", guard],
        env={**os.environ, "REQUIRED_JOB_RESULTS": json.dumps(results)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert (run.returncode == 0) == (verifier == "success")


@pytest.mark.parametrize("scope", ["code", "docs", "image"])
@pytest.mark.parametrize("failed_job", sorted(_PREREQUISITES))
@pytest.mark.parametrize("status", ["failure", "cancelled", "skipped"])
def test_final_gate_enforces_prerequisites_for_each_pr_scope(
    scope: str, failed_job: str, status: str
) -> None:
    """Allowed path skips cannot hide failures or skips of the parallel checks."""
    skipped = {
        "eval-gate",
        "privilege-root",
        "deterministic-integration",
        "action-e2e",
        "image-scan-slim",
        "image-scan-analyzers",
    }
    if scope == "image":
        skipped |= {"toolchain", "privileged-proofs"}
    elif scope == "code":
        skipped = set()
    results: dict[str, dict[str, object]] = {
        name: {"result": "skipped" if name in skipped else "success"} for name in _PREREQUISITES
    }
    results["changes"]["outputs"] = {
        "code": "true" if scope == "code" else "false",
        "image_only": "true" if scope == "image" else "false",
    }
    results[failed_job]["result"] = status
    guard = job(load_workflow("ci.yml"), "static")["steps"][0]["run"]
    run = subprocess.run(
        ["bash", "-ec", guard],
        env={
            **os.environ,
            "REQUIRED_JOB_RESULTS": json.dumps(results),
            "EVENT_NAME": "pull_request",
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert (run.returncode == 0) == (failed_job in skipped and status == "skipped"), (
        run.stdout + run.stderr
    )
