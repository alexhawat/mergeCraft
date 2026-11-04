"""The scheduled advisory sweep (#1069) — workflow shape.

The sweep changes *when* an advisory is seen, not what gates a merge: it runs on
a schedule and on demand against ``main`` only, never on a pull request, so it
adds no required check. It reuses the PR image scan's Trivy pin, policy and
waiver file, and its only write scope is ``issues`` on the reporting job.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.ci.workflow_support import (
    as_list,
    assert_third_party_uses_sha_pinned,
    job,
    load_workflow,
    workflow_on,
)

_WORKFLOW = "security-sweep.yml"


@pytest.fixture(scope="module")
def doc() -> dict[str, Any]:
    return load_workflow(_WORKFLOW)


def _steps(doc: dict[str, Any], name: str) -> list[dict[str, Any]]:
    steps = job(doc, name).get("steps")
    assert isinstance(steps, list)
    return [step for step in steps if isinstance(step, dict)]


def _uses(doc: dict[str, Any], name: str, prefix: str) -> dict[str, Any]:
    for step in _steps(doc, name):
        if str(step.get("uses", "")).startswith(prefix):
            return step
    raise AssertionError(f"{name} has no step using {prefix}")


def test_runs_daily_and_on_demand_but_never_on_a_pull_request(doc: dict[str, Any]) -> None:
    on = workflow_on(doc)
    assert isinstance(on, dict)
    assert set(on) == {"schedule", "workflow_dispatch"}, (
        f"the sweep must not run on pull requests (no new required check): {sorted(on)}"
    )
    crons = [entry.get("cron") for entry in as_list(on["schedule"])]
    assert len(crons) == 1
    assert str(crons[0]).split()[2:] == ["*", "*", "*"], "the sweep runs daily"


def test_every_job_speaks_for_main_only(doc: dict[str, Any]) -> None:
    for name, definition in (doc.get("jobs") or {}).items():
        assert "github.ref == 'refs/heads/main'" in str(definition.get("if", "")), (
            f"{name} must be guarded to main: a dispatch from another branch would "
            "otherwise close the tracking issue while main is still affected"
        )


def test_permissions_are_minimal(doc: dict[str, Any]) -> None:
    assert doc.get("permissions") == {"contents": "read"}
    for name, definition in (doc.get("jobs") or {}).items():
        expected = {"contents": "read"}
        if name == "report":
            expected["issues"] = "write"
        assert definition.get("permissions") == expected, f"{name}: {definition.get('permissions')}"


def test_the_python_audit_runs_lockcheck_and_make_security(doc: dict[str, Any]) -> None:
    runs = "\n".join(str(step.get("run", "")) for step in _steps(doc, "python-audit"))
    assert "make lockcheck" in runs
    assert "make security" in runs
    assert "--format json" in runs, "pip-audit must emit the JSON the report parses"
    assert "BANDIT_JSON=" in runs


def test_the_image_scan_reuses_the_pr_scan_trivy_pin_policy_and_waivers(
    doc: dict[str, Any],
) -> None:
    pr_scan = load_workflow("image-security.yml")
    reference = _uses(pr_scan, "scan", "aquasecurity/trivy-action@")
    sweep = _uses(doc, "image-scan", "aquasecurity/trivy-action@")
    assert sweep["uses"] == reference["uses"]
    for key in ("version", "severity", "ignore-unfixed", "trivyignores"):
        assert sweep["with"][key] == reference["with"][key], key
    assert sweep["with"]["image-ref"].startswith("${{ env.IMAGE }}:")
    assert doc["env"]["IMAGE"] == "ghcr.io/alexhawat/mergecraft"
    matrix = job(doc, "image-scan")["strategy"]["matrix"]["tag"]
    assert sorted(matrix) == ["analyzers", "latest"]
    runs = "\n".join(str(step.get("run", "")) for step in _steps(doc, "image-scan"))
    assert "scripts/check_trivyignore_expiry.py" in runs


def test_the_report_upserts_one_issue_by_fingerprint_and_closes_when_clean(
    doc: dict[str, Any],
) -> None:
    steps = _steps(doc, "report")
    runs = "\n".join(str(step.get("run", "")) for step in steps)
    assert "scripts/security_sweep_report.py" in runs
    assert "<!-- security-sweep:" in runs, "the issue is matched by its body marker"
    assert "gh issue edit" in runs
    assert "gh issue create" in runs
    assert "gh issue close" in runs
    conditions = {str(step.get("name")): str(step.get("if", "")) for step in steps}
    assert (
        "steps.summary.outputs.status == 'findings'"
        in conditions["Open or update the tracking issue"]
    )
    assert (
        "steps.summary.outputs.status == 'clear'"
        in conditions["Close the tracking issue once the sweep is clean"]
    )
    assert "always()" in str(job(doc, "report").get("if"))
    assert set(as_list(job(doc, "report").get("needs"))) == {"python-audit", "image-scan"}


def test_third_party_actions_are_sha_pinned() -> None:
    assert_third_party_uses_sha_pinned(_WORKFLOW)
