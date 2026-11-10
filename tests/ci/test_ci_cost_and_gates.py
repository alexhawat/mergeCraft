"""W3.4-1 / W0.4-3 — CI runs each expensive step once, and the scanners can block.

These read the real workflow files: the contracts are about what the required
checks do, not about a hand-built job.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.ci.workflow_support import REPO_ROOT, as_list, job, load_workflow, read_text, workflow_on

_ACTIONLINT_TEMPLATE = (
    REPO_ROOT / "src" / "mergecraft" / "analyzers" / "catalog" / "actionlint-sarif-template.txt"
)
_REQUIRED = {
    line.strip()
    for line in read_text("scripts/ci_required_verify_checks.txt").splitlines()
    if line.strip() and not line.startswith("#")
}


def _steps(workflow: str, name: str) -> list[dict[str, Any]]:
    return list(job(load_workflow(workflow), name)["steps"])


def _step(workflow: str, job_name: str, step_name: str) -> dict[str, Any]:
    return next(s for s in _steps(workflow, job_name) if s.get("name") == step_name)


def test_main_ci_runs_are_never_cancelled_so_base_coverage_gets_published() -> None:
    """A cancelled main run publishes no base coverage artifact; PRs then re-measure it."""
    group = load_workflow("ci.yml")["concurrency"]
    assert group["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}"


def test_required_check_names_are_still_produced_by_ci() -> None:
    doc = load_workflow("ci.yml")
    names = {str(spec.get("name", "")) for spec in doc["jobs"].values()}
    expanded: set[str] = set()
    for key, spec in doc["jobs"].items():
        matrix = (spec.get("strategy") or {}).get("matrix") or {}
        pythons = matrix.get("python") or [None]
        groups = matrix.get("group") or [None]
        for python in pythons:
            for group in groups:
                label = str(spec.get("name", key)).replace("${{ matrix.python }}", str(python))
                expanded.add(label.replace("${{ matrix.group }}", str(group)))
    assert expanded >= _REQUIRED, _REQUIRED - expanded
    assert names


def test_py314_shards_do_not_repeat_the_suite_the_coverage_gate_runs() -> None:
    steps = _steps("ci.yml", "test")
    run_steps = [s for s in steps if s.get("run") == "make test"]
    assert len(run_steps) == 1
    assert "matrix.python != '3.14'" in run_steps[0]["if"]
    for step in steps:
        if "uses" in step:
            assert "matrix.python != '3.14'" in step["if"], step.get("name")
    gate = [s for s in _steps("ci.yml", "coverage-gate") if s.get("run") == "make coverage-gate"]
    assert len(gate) == 1


def test_integration_workflow_does_not_repeat_the_keyless_integration_suite() -> None:
    """ci.yml deterministic-integration is the one run; integration-pr only gates the delta."""
    integration = load_workflow("integration.yml")
    pr_job = job(integration, "integration-pr")
    assert pr_job["strategy"]["matrix"]["python"] == ["3.14"]
    assert all(step.get("run") != "make test-integration" for step in pr_job["steps"])
    assert "github.event_name == 'pull_request'" in pr_job["if"]
    ci = job(load_workflow("ci.yml"), "deterministic-integration")
    assert any(step.get("run") == "make test-integration" for step in ci["steps"])


def test_ci_has_no_pr_side_base_coverage_cache_seed() -> None:
    """The seed step saved HEAD coverage under the base-SHA key (audit CIR-F7)."""
    text = read_text(".github/workflows/integration.yml")
    assert "actions/cache/save" not in text
    assert "MERGECRAFT_COVERAGE_ARTIFACT_EVENT: push" in text
    assert "MERGECRAFT_COVERAGE_ARTIFACT_STATUS: any" in text


def test_slim_image_is_built_once_and_reused() -> None:
    doc = load_workflow("ci.yml")
    builders = [
        name
        for name, spec in doc["jobs"].items()
        if any("docker/build-push-action" in str(s.get("uses", "")) for s in spec.get("steps", []))
    ]
    assert builders == ["slim-image"]
    for consumer in ("privilege-root", "image-scan-slim", "action-e2e"):
        assert "slim-image" in as_list(doc["jobs"][consumer]["needs"])
    assert job(doc, "action-e2e")["with"]["image-artifact"] == "mergecraft-slim-image"
    assert job(doc, "image-scan-slim")["with"]["slim-artifact"] == "mergecraft-slim-image"
    tags = _step("ci.yml", "slim-image", "Build slim image once")["with"]["tags"].split()
    assert {"mergecraft:e2e", "mergecraft:lane-a", "mergecraft:scan-slim"} <= set(tags)
    privilege = " ".join(str(s.get("run", "")) for s in _steps("ci.yml", "privilege-root"))
    assert "mergecraft:lane-a" in privilege


def test_e2e_skips_its_own_build_when_given_the_shared_image() -> None:
    steps = _steps("e2e.yml", "e2e-pr")
    build = next(s for s in steps if s.get("name") == "Build production image (PR artifact)")
    assert build["if"] == "inputs.image-artifact == ''"
    load = next(s for s in steps if s.get("name") == "Load shared slim image")
    assert load["if"] == "inputs.image-artifact != ''"
    assert "mergecraft-slim.tar" in load["run"]


def test_docs_only_prs_skip_image_builds_and_scans() -> None:
    doc = load_workflow("ci.yml")
    for name in (
        "slim-image",
        "image-scan-slim",
        "image-scan-analyzers",
        "action-e2e",
        "privilege-root",
        "deterministic-integration",
        "eval-gate",
    ):
        condition = doc["jobs"][name]["if"]
        assert "needs.changes.outputs.code == 'true'" in condition, name
        assert "github.event_name != 'pull_request'" in condition, name


def test_pull_request_image_scan_workflow_trigger_is_gone() -> None:
    """CI calls image-security.yml; a second pull_request trigger would build twice."""
    on = workflow_on(load_workflow("image-security.yml"))
    assert "pull_request" not in on
    assert {"workflow_call", "schedule", "workflow_dispatch"} <= set(on)
    assert "push" not in workflow_on(load_workflow("docker.yml"))


def test_mutation_advisory_is_nightly_only() -> None:
    condition = job(load_workflow("ci.yml"), "mutation-advisory")["if"]
    assert "pull_request" not in condition
    assert "push" not in condition
    assert "schedule" in condition


def test_static_waits_for_both_image_scans() -> None:
    needs = as_list(job(load_workflow("ci.yml"), "static")["needs"])
    assert {"image-scan-slim", "image-scan-analyzers"} <= set(needs)


def test_required_static_job_blocks_on_workflow_lint() -> None:
    step = _step("ci.yml", "static", "Workflow lint (actionlint + zizmor, blocking)")
    assert step["run"] == "make workflow-lint"
    assert not step.get("continue-on-error", False)


@pytest.mark.parametrize(
    "step_name",
    [
        "npm audit (agent-clis lockfile)",
        "Scanner waivers are well-formed and unexpired",
        "Emit semgrep SARIF",
        "Emit trufflehog SARIF",
    ],
)
def test_required_security_job_blocks_on_each_scanner(step_name: str) -> None:
    step = _step("ci.yml", "security", step_name)
    assert not step.get("continue-on-error", False)


def test_semgrep_and_trufflehog_steps_pass_fail_on_findings() -> None:
    for name in ("Emit semgrep SARIF", "Emit trufflehog SARIF"):
        assert "--fail-on-findings" in _step("ci.yml", "security", name)["run"]
    # Evidence uploads still run after a failing scan.
    for step in _steps("ci.yml", "security"):
        if str(step.get("name", "")).startswith("Upload semgrep"):
            assert "always()" in step["if"]


def test_image_scan_fails_on_unwaived_findings_and_checks_waiver_expiry() -> None:
    steps = _steps("image-security.yml", "scan")
    names = [s.get("name") for s in steps]
    assert names.index("Reject expired scan waivers") < names.index("Scan built image")
    scan = steps[names.index("Scan built image")]
    assert str(scan["with"]["exit-code"]) == "1"
    assert not scan.get("continue-on-error", False)


def test_docs_only_guard_requires_skips_only_for_docs_only_prs() -> None:
    """The static guard: a docs-only PR may skip the image jobs, a code PR may not."""
    import json
    import subprocess

    guard = job(load_workflow("ci.yml"), "static")["steps"][0]["run"]
    needs = as_list(job(load_workflow("ci.yml"), "static")["needs"])

    def run(event: str, code: str, skipped: set[str]) -> int:
        results: dict[str, Any] = {n: {"result": "success"} for n in needs}
        for name in skipped:
            results[name] = {"result": "skipped"}
        results["changes"] = {"result": "success", "outputs": {"code": code, "image_only": "false"}}
        return subprocess.run(
            ["bash", "-ec", guard],
            env={**os.environ, "REQUIRED_JOB_RESULTS": json.dumps(results), "EVENT_NAME": event},
            capture_output=True,
            text=True,
            check=False,
        ).returncode

    docs_skips = {
        "eval-gate",
        "privilege-root",
        "deterministic-integration",
        "action-e2e",
        "image-scan-slim",
        "image-scan-analyzers",
    }
    assert run("pull_request", "false", docs_skips) == 0
    assert run("pull_request", "true", docs_skips) == 1
    assert run("push", "false", docs_skips) == 1
    assert run("pull_request", "false", docs_skips | {"toolchain"}) == 1
    assert run("pull_request", "true", set()) == 0


def test_dockerfile_syntax_directive_is_the_first_line() -> None:
    for name in ("Dockerfile", "Dockerfile.analyzers"):
        lines = (REPO_ROOT / "docker" / name).read_text(encoding="utf-8").splitlines()
        assert lines[0].startswith("# syntax=docker/dockerfile:"), name
        assert lines[1].startswith("# SPDX-License-Identifier"), name


def test_dockerignore_is_an_allow_list_covering_every_copy_source() -> None:
    patterns = [
        line.strip()
        for line in read_text(".dockerignore").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert patterns[0] == "*"
    allowed = {p.removeprefix("!") for p in patterns if p.startswith("!")}
    for name in ("Dockerfile", "Dockerfile.analyzers"):
        for line in (REPO_ROOT / "docker" / name).read_text(encoding="utf-8").splitlines():
            if not line.startswith("COPY ") or "--from=" in line:
                continue
            for source in line.split()[1:-1]:
                top = source.removeprefix("./")
                assert any(
                    top == a
                    or top == a.removesuffix("/**")
                    or top.startswith(a.removesuffix("/**").rstrip("/") + "/")
                    for a in allowed
                ), f"{name} COPYs {source}, which .dockerignore drops"


def test_classifier_runs_from_the_base_blob_on_pull_requests() -> None:
    step = _step("classify-pr.yml", "changes", "Docs-only vs code paths")
    assert 'git show "$BASE_SHA:scripts/ci_pr_touches_code.py"' in step["run"]
    assert "python3 -I" in step["run"]
    assert step["env"]["BASE_SHA"] == "${{ github.event.pull_request.base.sha }}"


@pytest.mark.skipif(
    shutil.which("actionlint") is None or shutil.which("zizmor") is None,
    reason="actionlint and zizmor must be installed",
)
def test_seeded_workflow_defects_fail_workflow_lint(tmp_path: Path) -> None:
    """A syntax error (actionlint) and an expression injection (zizmor) each exit non-zero."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy(REPO_ROOT / "scripts" / "workflow_lint.sh", scripts / "workflow_lint.sh")
    template = tmp_path / "src/mergecraft/analyzers/catalog"
    template.mkdir(parents=True)
    shutil.copy(_ACTIONLINT_TEMPLATE, template / _ACTIONLINT_TEMPLATE.name)
    (tmp_path / ".github").mkdir()
    shutil.copy(REPO_ROOT / ".github" / "zizmor.yml", tmp_path / ".github" / "zizmor.yml")
    cache = tmp_path / "cache"
    cache.mkdir()
    for tool in ("actionlint", "zizmor"):
        (cache / tool).symlink_to(shutil.which(tool) or "")
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir()
    env = {**os.environ, "MERGECRAFT_TOOL_CACHE": str(cache)}

    def lint() -> int:
        return subprocess.run(
            ["bash", str(scripts / "workflow_lint.sh")],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        ).returncode

    clean = (
        "name: t\non: push\npermissions: {}\njobs:\n  a:\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - run: echo ok\n"
    )
    (workflows / "t.yml").write_text(clean, encoding="utf-8")
    assert lint() == 0
    (workflows / "t.yml").write_text(clean.replace("echo ok", "echo ok\n    bad: key"), "utf-8")
    assert lint() != 0
    injected = clean.replace("on: push", "on: pull_request_target").replace(
        "echo ok", "echo ${{ github.event.pull_request.title }}"
    )
    (workflows / "t.yml").write_text(injected, encoding="utf-8")
    assert lint() != 0
