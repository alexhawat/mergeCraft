"""The approval gate must take its verdict from this run, not from any check-run.

A `mergecraft-approval` check-run is a claim about a review. The gate that
enforces it used to trust the *name* and the *latest* one, so any app could post
a passing check and mask a failing verdict from a PR workflow. The gate now
takes the verdict from the review job's own output (which only this run can
write) and treats a check merely as corroboration: same head, issued by
`github-actions` or the configured App, same `<run_id>:<run_attempt>`, and a
conclusion that agrees. A foreign, unattributable, disagreeing or missing check
fails closed; only the hardened example keeps its documented fail-open notice
when no `mergecraft-approval` check exists at all.

These tests extract each gate's `run:` and the shared routing library and drive
them against a `gh` mock, so the contract is exercised as shell, the way the
workflow runs it.
"""

from __future__ import annotations

import json
import os
import subprocess
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.ci.support_self_review_cascade import (
    RUN_ATTEMPT,
    RUN_ID,
    evidence_packet,
    run_decide_script,
    stage_trusted_copy,
    write_gh_mock,
)
from tests.ci.workflow_support import REPO_ROOT, job, load_workflow

HEAD_SHA = "abc123def4567890abcdef1234567890abcd1234"
GITHUB_ACTIONS_APP: dict[str, Any] = {"id": 15368, "slug": "github-actions"}
FOREIGN_APP: dict[str, Any] = {"id": 99999, "slug": "foreign-approver"}
CONFIGURED_APP: dict[str, Any] = {"id": 4242, "slug": "mergecraft-configured"}
MATCHING_EXTERNAL_ID = f"{RUN_ID}:{RUN_ATTEMPT}"

_GATE_STEP = "Fail when mergeCraft would not approve"


@dataclass(frozen=True)
class GateTarget:
    """One copy of the approval gate and where its verdict comes from."""

    name: str
    relative: str
    job_name: str


_SELF = GateTarget("self", ".github/workflows/mergecraft.yml", "approval-gate")
_HARDENED = GateTarget("hardened", "scripts/example_workflows/hardened.yml.tpl", "review")
_DOGFOOD = GateTarget("dogfood", "docs/artifacts/dogfood-mergecraft.yml", "review")
# SW2 hardened the self-workflow's gate; the hardened example and the dogfood
# artifact are SW3's to update, so only their cases stay expected-red.
_XFAIL_CONSUMER_GATE = pytest.mark.xfail(
    reason="green after SW3.3 / SW3.7: hardened example and dogfood gate hardening",
    strict=False,
)
_TARGET_PARAMS: list[Any] = [
    pytest.param(_SELF, id="self"),
    pytest.param(_HARDENED, id="hardened", marks=_XFAIL_CONSUMER_GATE),
    pytest.param(_DOGFOOD, id="dogfood", marks=_XFAIL_CONSUMER_GATE),
]
# The hardened example and the dogfood artifact keep their documented
# fail-open behaviour when no mergecraft-approval check exists at all.
_FAIL_OPEN_WHEN_CHECK_ABSENT = {_HARDENED.name, _DOGFOOD.name}


def _gate_doc(target: GateTarget) -> dict[str, Any]:
    loaded = yaml.safe_load((REPO_ROOT / target.relative).read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), f"{target.relative} did not parse as a mapping"
    return loaded


def _gate_step(target: GateTarget) -> dict[str, Any]:
    steps = job(_gate_doc(target), target.job_name).get("steps")
    assert isinstance(steps, list), f"{target.relative}: {target.job_name} steps not a list"
    for step in steps:
        if isinstance(step, dict) and step.get("name") == _GATE_STEP:
            return step
    raise AssertionError(f"{target.relative}: no {_GATE_STEP!r} step in {target.job_name}")


def _output_env(step: dict[str, Any]) -> tuple[str, bool]:
    """Return ``(env_key, reads_packet)`` for the step's own-output source.

    A gate must read the review job's output through ``env:``. The self-workflow
    exposes a bare verdict (``approval_verdict``); the hardened example and the
    dogfood artifact read the evidence packet directly.
    """
    env_block = step.get("env") or {}
    assert isinstance(env_block, dict)
    for key, value in env_block.items():
        if not isinstance(value, str):
            continue
        if "needs.review.outputs.approval_verdict" in value:
            return str(key), False
        if "outputs.evidence_packet" in value:
            return str(key), True
    raise AssertionError(
        "the gate does not read this run's own output through env: — it must not "
        "derive its verdict from a check-run alone"
    )


def _check(
    *,
    conclusion: str = "success",
    app: dict[str, Any] = GITHUB_ACTIONS_APP,
    external_id: str = MATCHING_EXTERNAL_ID,
    check_id: int = 1,
    completed_at: str = "2026-09-01T00:00:00Z",
    head_sha: str = HEAD_SHA,
    status: str = "completed",
) -> dict[str, Any]:
    return {
        "id": check_id,
        "name": "mergecraft-approval",
        "conclusion": conclusion,
        "status": status,
        "head_sha": head_sha,
        "external_id": external_id,
        "completed_at": completed_at,
        "app": app,
    }


def _write_gate_gh_mock(tmp_path: Path, checks: list[dict[str, Any]]) -> Path:
    """Install a `gh` stub that emulates the check-runs query and `--jq`."""
    bin_dir = tmp_path / "gate-bin"
    bin_dir.mkdir(parents=True)
    payload_path = tmp_path / "gate_check_runs.json"
    payload_path.write_text(json.dumps({"check_runs": checks}), encoding="utf-8")
    script = textwrap.dedent(
        """\
        #!/usr/bin/env bash
        set -euo pipefail
        if [[ "$*" != *check-runs* ]]; then
          echo "unexpected gh invocation: $*" >&2
          exit 1
        fi
        jq_expr=""
        args=("$@")
        i=0
        while [ "$i" -lt "${#args[@]}" ]; do
          arg="${args[$i]}"
          if [ "$arg" = "--jq" ]; then
            i=$((i + 1))
            jq_expr="${args[$i]}"
          fi
          i=$((i + 1))
        done
        if [ -n "$jq_expr" ]; then
          jq -r "$jq_expr" "__PAYLOAD__"
        else
          cat "__PAYLOAD__"
        fi
        """
    ).replace("__PAYLOAD__", str(payload_path))
    gh_path = bin_dir / "gh"
    gh_path.write_text(script, encoding="utf-8")
    gh_path.chmod(0o755)
    return bin_dir


def _run_gate(
    target: GateTarget,
    tmp_path: Path,
    *,
    verdict: str,
    checks: list[dict[str, Any]],
    expected_app_id: str = "",
) -> int:
    """Run the gate's ``run:`` with the given own-output verdict and checks."""
    step = _gate_step(target)
    output_key, reads_packet = _output_env(step)
    run = step.get("run")
    assert isinstance(run, str), f"{target.name}: gate run: is not a string"
    assert run.strip(), f"{target.name}: gate has no run:"

    env: dict[str, str] = {**os.environ}
    env.update(
        {
            "REPO": "acme/demo",
            "HEAD_SHA": HEAD_SHA,
            "GH_TOKEN": "ghs_fixture",
            "GITHUB_RUN_ID": RUN_ID,
            "GITHUB_RUN_ATTEMPT": RUN_ATTEMPT,
            "EXPECTED_APP_ID": expected_app_id,
        }
    )
    expression_values = {
        "github.run_id": RUN_ID,
        "github.run_attempt": RUN_ATTEMPT,
        "github.repository": "acme/demo",
        "github.event.pull_request.head.sha": HEAD_SHA,
        "secrets.MERGECRAFT_APP_ID": expected_app_id,
    }
    env_block = step.get("env") or {}
    assert isinstance(env_block, dict)
    for key, value in env_block.items():
        if not isinstance(value, str):
            continue
        if "outputs.approval_verdict" in value or "outputs.evidence_packet" in value:
            continue
        for marker, resolved in expression_values.items():
            if marker in value:
                env[str(key)] = resolved
    env[output_key] = evidence_packet(verdict=verdict) if reads_packet and verdict else verdict

    gh_dir = _write_gate_gh_mock(tmp_path, checks)
    env["PATH"] = f"{gh_dir}:{env.get('PATH', '/usr/bin:/bin')}"

    script_path = tmp_path / "gate.sh"
    script_path.write_text(run, encoding="utf-8")
    completed = subprocess.run(
        ["bash", str(script_path)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
    )
    return completed.returncode


def _assert_blocks(target: GateTarget, tmp_path: Path, **kwargs: Any) -> None:
    returncode = _run_gate(target, tmp_path, **kwargs)
    assert returncode != 0, (
        f"{target.name}: gate passed (exit 0) where it must fail closed — "
        "the check cannot vouch for a verdict this run did not produce"
    )


def _assert_passes(target: GateTarget, tmp_path: Path, **kwargs: Any) -> None:
    returncode = _run_gate(target, tmp_path, **kwargs)
    assert returncode == 0, (
        f"{target.name}: gate blocked (exit {returncode}) where this run's own "
        "output and a corroborating check agree on success"
    )


# ── structural wiring ──────────────────────────────────────────────────────


@pytest.mark.parametrize("target", _TARGET_PARAMS)
def test_gate_reads_this_runs_own_output(target: GateTarget) -> None:
    key, _ = _output_env(_gate_step(target))
    assert key


@pytest.mark.parametrize("target", _TARGET_PARAMS)
def test_gate_queries_the_check_by_name_with_an_explicit_page(target: GateTarget) -> None:
    run = str(_gate_step(target).get("run"))
    assert "check_name=mergecraft-approval" in run, (
        "the gate must ask for mergecraft-approval by name so a large CI matrix "
        "cannot push it off the first page"
    )
    assert "per_page=100" in run
    assert "filter=all" in run


def test_self_workflow_exposes_the_run_verdict_as_job_outputs() -> None:
    """Another run cannot write a job output, so binding to one is run binding."""
    outputs = job(load_workflow("mergecraft.yml"), "review").get("outputs") or {}
    assert isinstance(outputs, dict)
    assert "approval_verdict" in outputs, "review job must expose approval_verdict"
    assert "approval_rung" in outputs, "review job must expose which rung ran"
    env_block = _gate_step(_SELF).get("env") or {}
    assert isinstance(env_block, dict)
    assert any(
        isinstance(value, str) and "needs.review.outputs.approval_verdict" in value
        for value in env_block.values()
    ), "approval-gate must read needs.review.outputs.approval_verdict"


def test_shared_routing_lib_uses_the_same_name_filtered_query() -> None:
    text = (REPO_ROOT / "scripts/lib/provider_verdict_guard.sh").read_text(encoding="utf-8")
    assert "check_name=mergecraft-approval" in text
    assert "per_page=100" in text
    assert "filter=all" in text


# ── behavioral matrix ──────────────────────────────────────────────────────


@pytest.mark.parametrize("target", _TARGET_PARAMS)
def test_newer_foreign_success_cannot_mask_a_genuine_success(
    target: GateTarget, tmp_path: Path
) -> None:
    _assert_passes(
        target,
        tmp_path,
        verdict="success",
        checks=[
            _check(check_id=1),
            _check(
                check_id=2,
                app=FOREIGN_APP,
                external_id="",
                completed_at="2026-09-02T00:00:00Z",
            ),
        ],
    )


@pytest.mark.parametrize("target", _TARGET_PARAMS)
def test_output_failure_blocks_despite_a_newer_foreign_success(
    target: GateTarget, tmp_path: Path
) -> None:
    _assert_blocks(
        target,
        tmp_path,
        verdict="failure",
        checks=[
            _check(
                check_id=2,
                app=FOREIGN_APP,
                external_id="",
                completed_at="2026-09-02T00:00:00Z",
            )
        ],
    )


@pytest.mark.parametrize("target", _TARGET_PARAMS)
def test_github_actions_check_with_matching_attempt_corroborates_success(
    target: GateTarget, tmp_path: Path
) -> None:
    _assert_passes(target, tmp_path, verdict="success", checks=[_check()])


@pytest.mark.parametrize("target", _TARGET_PARAMS)
def test_configured_app_check_corroborates_success(target: GateTarget, tmp_path: Path) -> None:
    _assert_passes(
        target,
        tmp_path,
        verdict="success",
        checks=[_check(app=CONFIGURED_APP)],
        expected_app_id=str(CONFIGURED_APP["id"]),
    )


@pytest.mark.parametrize("target", _TARGET_PARAMS)
def test_wrong_external_id_is_unattributable_and_blocks(target: GateTarget, tmp_path: Path) -> None:
    _assert_blocks(
        target,
        tmp_path,
        verdict="success",
        checks=[_check(external_id="999:9")],
    )


@pytest.mark.parametrize("target", _TARGET_PARAMS)
def test_empty_output_with_no_check(target: GateTarget, tmp_path: Path) -> None:
    """A missing packet and a missing check: self fails closed, examples notice."""
    returncode = _run_gate(target, tmp_path, verdict="", checks=[])
    if target.name in _FAIL_OPEN_WHEN_CHECK_ABSENT:
        assert returncode == 0, f"{target.name}: the documented missing-check notice is fail-open"
    else:
        assert returncode != 0, "self review must fail closed with no verdict and no check"


@pytest.mark.parametrize("target", _TARGET_PARAMS)
def test_empty_output_with_a_corroborating_check_blocks(target: GateTarget, tmp_path: Path) -> None:
    _assert_blocks(target, tmp_path, verdict="", checks=[_check()])


@pytest.mark.parametrize("target", _TARGET_PARAMS)
@pytest.mark.parametrize("verdict", ["failure", "neutral"])
def test_forged_github_actions_success_cannot_pass_a_non_success_run(
    target: GateTarget, tmp_path: Path, verdict: str
) -> None:
    """A PR workflow can create a github-actions check; the output must outvote it."""
    _assert_blocks(target, tmp_path, verdict=verdict, checks=[_check()])


@pytest.mark.parametrize("target", _TARGET_PARAMS)
def test_matching_check_with_failure_conclusion_blocks(target: GateTarget, tmp_path: Path) -> None:
    _assert_blocks(
        target,
        tmp_path,
        verdict="success",
        checks=[_check(conclusion="failure")],
    )


@pytest.mark.parametrize("target", _TARGET_PARAMS)
def test_a_lone_foreign_check_cannot_pass(target: GateTarget, tmp_path: Path) -> None:
    _assert_blocks(
        target,
        tmp_path,
        verdict="success",
        checks=[_check(app=FOREIGN_APP)],
    )


# ── shared routing library ─────────────────────────────────────────────────


def test_routing_prefers_the_packet_verdict_over_a_foreign_check(
    tmp_path: Path,
) -> None:
    root = stage_trusted_copy(tmp_path)
    gh_dir = write_gh_mock(tmp_path, conclusion="failure", app_slug="foreign-approver")
    outputs, completed = run_decide_script(
        tmp_path,
        root / "scripts/decide_codex_fallback.sh",
        env={"NOUS_OUTCOME": "success", "NOUS_PACKET": evidence_packet(verdict="failure")},
        gh_mock_dir=gh_dir,
        cwd=root,
    )
    assert completed.returncode == 0
    assert outputs.get("need") == "false", (
        "the packet carries this rung's verdict; the check-run is only corroboration"
    )


def test_routing_never_treats_a_foreign_check_as_a_verdict(tmp_path: Path) -> None:
    root = stage_trusted_copy(tmp_path)
    gh_dir = write_gh_mock(
        tmp_path,
        conclusion="success",
        app_slug="foreign-approver",
        external_id=f"{RUN_ID}:{RUN_ATTEMPT}",
    )
    outputs, completed = run_decide_script(
        tmp_path,
        root / "scripts/decide_codex_fallback.sh",
        env={"NOUS_OUTCOME": "success", "NOUS_PACKET": ""},
        gh_mock_dir=gh_dir,
        cwd=root,
    )
    assert completed.returncode == 0
    assert outputs.get("need") == "true", (
        "a check-run from an app this repo does not trust is not a fallback verdict"
    )
