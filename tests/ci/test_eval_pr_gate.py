"""E2 — keyless ``eval-replay`` + ``eval-gate`` is a required PR check (E-D2, E-D3).

Wave plan: ``.ignorelocal/waves/25-evals-calibration-wave-plan.md``.
Implementation does not exist yet: these assertions are RED until E2 wires
``eval-gate`` into ``.github/workflows/ci.yml``. Collection stays clean
because the workflow parser already exists.

``bench-detect`` stays out of the PR gate (needs credentials). Failure
output must name ``GateReport.regressed_metrics`` plus baseline / candidate
/ delta. The check summary states it proves structural replay, not live
detection quality.
"""

from __future__ import annotations

from tests.ci.workflow_support import job, load_workflow, read_text, workflow_on
from tests.evals.support_eval_calibration import (
    EVAL_GATE_JOB_ID,
    PROVIDER_SECRET_ENV,
    STRUCTURAL_BASELINE,
    ci_eval_gate_job,
    ci_eval_gate_source,
    job_script_text,
)


def test_ci_yml_runs_on_pull_request() -> None:
    """The PR workflow is the one that must grow the eval-gate check."""
    on_block = workflow_on(load_workflow("ci.yml"))
    assert isinstance(on_block, dict)
    assert "pull_request" in on_block


def test_ci_yml_has_blocking_eval_gate_job() -> None:
    """E-D2 — ``eval-gate`` is a required PR check, not advisory."""
    gate = ci_eval_gate_job()
    assert gate.get("continue-on-error") in (None, False)
    if_expr = gate.get("if")
    if isinstance(if_expr, str):
        lowered = if_expr.casefold()
        assert "pull_request" not in lowered or "!= 'pull_request'" not in lowered


def test_removing_eval_gate_job_fails() -> None:
    """Guard-deletion: dropping the job from ``ci.yml`` fails this test."""
    jobs = load_workflow("ci.yml").get("jobs") or {}
    assert EVAL_GATE_JOB_ID in jobs, "eval-gate was removed from ci.yml (E-D2 regression)"


def test_eval_gate_pr_job_is_keyless() -> None:
    """E-D2 — a PR gate that needs a paid key is a gate that gets disabled."""
    gate = ci_eval_gate_job()
    env = gate.get("env") or {}
    assert PROVIDER_SECRET_ENV.isdisjoint(set(env))
    assert "secrets" not in gate
    text = job_script_text(gate)
    for name in PROVIDER_SECRET_ENV:
        assert name not in text


def test_eval_gate_pr_job_runs_replay_and_regression_comparison() -> None:
    """Keyless structural tier: replay the bank, then gate against the baseline."""
    text = job_script_text(ci_eval_gate_job()).casefold()
    replayed = "eval-replay" in text or "replay-bank" in text
    gated = "eval-gate" in text or "eval gate" in text
    assert replayed, "PR eval-gate job must run eval-replay / replay-bank"
    assert gated, "PR eval-gate job must run eval-gate"
    assert "--baseline" in text
    assert "--candidate" in text
    assert STRUCTURAL_BASELINE in job_script_text(ci_eval_gate_job())


def test_eval_gate_pr_job_does_not_run_bench_detect() -> None:
    """E-D2 — ``bench-detect`` needs credentials and stays out of the PR gate."""
    text = job_script_text(ci_eval_gate_job()).casefold()
    assert "bench-detect" not in text
    assert "eval bench" not in text


def test_ci_yml_has_no_bench_detect_job() -> None:
    """Guard-deletion: ``bench-detect`` must not become its own PR job."""
    jobs = load_workflow("ci.yml").get("jobs") or {}
    assert "bench-detect" not in jobs


def test_mutation_advisory_is_not_the_eval_gate() -> None:
    """V1 — ``mutation-advisory`` stays advisory; it is not the E2 check."""
    advisory = job(load_workflow("ci.yml"), "mutation-advisory")
    assert advisory.get("continue-on-error") is True
    assert EVAL_GATE_JOB_ID != "mutation-advisory"


def test_eval_gate_pr_check_summary_states_structural_not_live_scope() -> None:
    """E-D3 — the check says it proves structural replay, not live detection."""
    source = ci_eval_gate_source().casefold()
    script = job_script_text(ci_eval_gate_job()).casefold()
    blob = f"{source}\n{script}"
    assert "structural replay" in blob
    assert "live detection" in blob
    assert "not" in blob


def test_eval_gate_pr_job_writes_step_summary() -> None:
    """Failure names the moved metric on the check surface, not a bare fail."""
    text = job_script_text(ci_eval_gate_job())
    source = ci_eval_gate_source()
    blob = f"{text}\n{source}"
    assert "GITHUB_STEP_SUMMARY" in blob or "format_pr_gate_summary" in blob


def test_eval_gate_pr_job_permissions_are_read_only() -> None:
    """The keyless gate needs checkout only — no write tokens."""
    gate = ci_eval_gate_job()
    permissions = gate.get("permissions")
    if permissions is None:
        workflow = load_workflow("ci.yml").get("permissions") or {}
        assert workflow.get("contents") == "read"
        return
    assert permissions.get("contents") == "read"
    for key, value in permissions.items():
        if key == "contents":
            continue
        assert value in ("read", "none", None)


def test_makefile_keeps_keyless_eval_targets() -> None:
    """GREEN pin — the Make surface E2 wires into CI already exists."""
    makefile = read_text("Makefile")
    for target in ("eval-gate", "eval-replay", "eval-convergence", "bench-detect"):
        assert f"{target}:" in makefile, f"Makefile missing {target}"


def test_release_yml_still_has_eval_gate() -> None:
    """E2 adds the PR check; it does not remove the release gate."""
    release = job(load_workflow("release.yml"), "eval-gate")
    text = job_script_text(release)
    assert "--baseline" in text
    assert STRUCTURAL_BASELINE in text
