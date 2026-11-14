"""The required review gate passes recognized neutral outcomes for deliberate skips.

A pull request whose every changed file matches the review ignore paths runs no LLM
review: the orchestrator records a ``skip`` triage tier with the ``ignorePaths``
recognizer and publishes ``mergecraft-approval=neutral`` ("nothing to review"). The
``mergecraft review`` gate used to fail every non-success verdict, so a changelog-only
or lockfile-only pull request could never pass the required check.

The gate passes that neutral and an explicit base-side review policy skip.
It learns the reason from this run's own
evidence packet (the self-workflow's verdict recorder turns it into the
``approval_reason`` job output; the consumer templates read it from the action's
``evidence_packet`` output), never from PR text, labels or a check-run, and only after
the neutral ``mergecraft-approval`` check has been attributed to this run and head. The
same reason stops the Codex fallback and the Claude backstop: a later rung would reach
the same result.

Every case runs the workflow's own ``run:`` scripts as shell, the way the runner does.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.ci.support_self_review_cascade import (
    HEAD_SHA,
    RUN_ATTEMPT,
    RUN_ID,
    parse_github_output,
    run_decide_script,
    stage_trusted_copy,
    write_gh_mock,
)
from tests.ci.workflow_support import REPO_ROOT, job

_GATE_STEP = "Fail when mergeCraft would not approve"
_SKIP_STEP = "Report review skipped"
_SELF = ".github/workflows/mergecraft.yml"
_HARDENED_TPL = "scripts/example_workflows/hardened.yml.tpl"
_HARDENED = "examples/workflows/mergecraft-hardened.yml"
_DOGFOOD = "docs/artifacts/dogfood-mergecraft.yml"

_IGNORE_REASON = "nothing to review: all 2 changed file(s) are ignored by config"

_PACKET_EXPRESSIONS = {
    "REVIEW_VERDICT": (
        "${{ steps.mergecraft.outputs.evidence_packet != '' && "
        "fromJSON(steps.mergecraft.outputs.evidence_packet).decision.verdict || '' }}"
    ),
    "REVIEW_SKIP_RECOGNIZER": (
        "${{ steps.mergecraft.outputs.evidence_packet != '' && "
        "fromJSON(steps.mergecraft.outputs.evidence_packet).triage.tier == 'skip' && "
        "fromJSON(steps.mergecraft.outputs.evidence_packet).triage.recognizer || '' }}"
    ),
    "REVIEW_SKIP_REASON": (
        "${{ steps.mergecraft.outputs.evidence_packet != '' && "
        "fromJSON(steps.mergecraft.outputs.evidence_packet).triage.reason || '' }}"
    ),
}


def _load(relative: str) -> dict[str, Any]:
    loaded = yaml.safe_load((REPO_ROOT / relative).read_text(encoding="utf-8").replace("__", "X"))
    assert isinstance(loaded, dict), relative
    return loaded


def _step(
    relative: str, job_name: str, *, name: str | None = None, step_id: str | None = None
) -> dict[str, Any]:
    for step in job(_load(relative), job_name).get("steps") or []:
        if not isinstance(step, dict):
            continue
        if (name is not None and step.get("name") == name) or (
            step_id is not None and step.get("id") == step_id
        ):
            return step
    raise AssertionError(f"{relative}: no step {name or step_id!r} in job {job_name}")


def _packet(
    verdict: str | None,
    *,
    tier: str | None = None,
    recognizer: str | None = None,
    reason: str = _IGNORE_REASON,
) -> dict[str, Any]:
    packet: dict[str, Any] = {}
    if verdict is not None:
        packet["decision"] = {"verdict": verdict, "reason": f"{verdict}: fixture"}
    if tier is not None:
        packet["triage"] = {"tier": tier, "recognizer": recognizer, "reason": reason}
    return packet


_ALL_IGNORED = _packet("neutral", tier="skip", recognizer="ignorePaths")


def _check(
    conclusion: str,
    *,
    external_id: str = f"{RUN_ID}:{RUN_ATTEMPT}",
    app: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": 7,
        "name": "mergecraft-approval",
        "conclusion": conclusion,
        "status": "completed",
        "head_sha": HEAD_SHA,
        "external_id": external_id,
        "completed_at": "2026-11-12T00:00:00Z",
        "app": app or {"id": 15368, "slug": "github-actions"},
    }


def _gh_mock(tmp_path: Path, checks: list[dict[str, Any]]) -> Path:
    bin_dir = tmp_path / "gate-bin"
    bin_dir.mkdir()
    payload = tmp_path / "check_runs.json"
    payload.write_text(json.dumps({"check_runs": checks}), encoding="utf-8")
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$*" != *check-runs* ]]; then echo "unexpected gh: $*" >&2; exit 1; fi\n'
        f'cat "{payload}"\n',
        encoding="utf-8",
    )
    gh.chmod(0o755)
    return bin_dir


def _run_script(
    run: str, tmp_path: Path, env: dict[str, str], *, path_prefix: Path | None = None
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    output = tmp_path / "github_output"
    summary = tmp_path / "step_summary.md"
    output.write_text("", encoding="utf-8")
    summary.write_text("", encoding="utf-8")
    script = tmp_path / f"step-{len(list(tmp_path.glob('step-*.sh')))}.sh"
    script.write_text(run, encoding="utf-8")
    full_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path),
        "GITHUB_OUTPUT": str(output),
        "GITHUB_STEP_SUMMARY": str(summary),
        "GITHUB_RUN_ID": RUN_ID,
        "GITHUB_RUN_ATTEMPT": RUN_ATTEMPT,
        "REPO": "acme/demo",
        "HEAD_SHA": HEAD_SHA,
        "GH_TOKEN": "ghs_fixture",
        "EXPECTED_APP_ID": "",
        **env,
    }
    if path_prefix is not None:
        full_env["PATH"] = f"{path_prefix}:{full_env['PATH']}"
    completed = subprocess.run(
        ["bash", str(script)],
        check=False,
        capture_output=True,
        text=True,
        env=full_env,
        cwd=str(tmp_path),
    )
    return completed, output, summary


# ── self-workflow: verdict recorder → approval gate ─────────────────────────


def _record_self(tmp_path: Path, packets: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Run the review-backstop verdict recorder over per-rung packet files."""
    step = _step(_SELF, "review-backstop", step_id="approval_verdict")
    env: dict[str, str] = {}
    for rung, key in (
        ("opencode-go", "OPENCODE_GO_PACKET_FILE"),
        ("codex", "CODEX_PACKET_FILE"),
        ("claude", "CLAUDE_PACKET_FILE"),
    ):
        path = tmp_path / f"packet-{rung}.json"
        if rung in packets:
            path.write_text(json.dumps(packets[rung]), encoding="utf-8")
        env[key] = str(path)
    completed, output, _ = _run_script(str(step["run"]), tmp_path, env)
    assert completed.returncode == 0, completed.stderr
    return parse_github_output(output)


def _gate_self(
    tmp_path: Path, recorded: dict[str, str], checks: list[dict[str, Any]]
) -> tuple[subprocess.CompletedProcess[str], str]:
    step = _step(_SELF, "approval-gate", name=_GATE_STEP)
    env = {
        "APPROVAL_VERDICT": recorded.get("approval_verdict", ""),
        "APPROVAL_RUNG": recorded.get("approval_rung", ""),
        "APPROVAL_REASON": recorded.get("approval_reason", ""),
        "APPROVAL_IGNORED_COUNT": recorded.get("approval_ignored_count", ""),
    }
    completed, _, summary = _run_script(
        str(step["run"]), tmp_path, env, path_prefix=_gh_mock(tmp_path, checks)
    )
    return completed, summary.read_text(encoding="utf-8")


# ── consumer templates: packet expressions → approval gate ──────────────────


def _packet_env(packet: dict[str, Any] | None) -> dict[str, str]:
    """Evaluate the three packet expressions the consumer gate's env declares."""
    if packet is None:
        return dict.fromkeys(_PACKET_EXPRESSIONS, "")
    decision = packet.get("decision") or {}
    triage = packet.get("triage") or {}
    return {
        "REVIEW_VERDICT": str(decision.get("verdict") or ""),
        "REVIEW_SKIP_RECOGNIZER": (
            str(triage.get("recognizer") or "") if triage.get("tier") == "skip" else ""
        ),
        "REVIEW_SKIP_REASON": str(triage.get("reason") or ""),
    }


def _gate_consumer(
    relative: str, tmp_path: Path, packet: dict[str, Any] | None, checks: list[dict[str, Any]]
) -> tuple[subprocess.CompletedProcess[str], str]:
    step = _step(relative, "review", name=_GATE_STEP)
    completed, _, summary = _run_script(
        str(step["run"]), tmp_path, _packet_env(packet), path_prefix=_gh_mock(tmp_path, checks)
    )
    return completed, summary.read_text(encoding="utf-8")


@dataclass(frozen=True)
class GateCase:
    packet: dict[str, Any] | None
    checks: tuple[dict[str, Any], ...]
    passes: bool


_GATE_CASES: dict[str, GateCase] = {
    "success-passes": GateCase(_packet("success"), (_check("success"),), passes=True),
    "neutral-all-ignored-attributable-check-passes": GateCase(
        _ALL_IGNORED, (_check("neutral"),), passes=True
    ),
    "neutral-all-ignored-no-check-fails": GateCase(_ALL_IGNORED, (), passes=False),
    "neutral-all-ignored-foreign-check-fails": GateCase(
        _ALL_IGNORED,
        (_check("neutral", app={"id": 99999, "slug": "foreign-approver"}),),
        passes=False,
    ),
    "neutral-all-ignored-other-run-check-fails": GateCase(
        _ALL_IGNORED, (_check("neutral", external_id="999:1"),), passes=False
    ),
    "neutral-all-ignored-disagreeing-success-check-fails": GateCase(
        _ALL_IGNORED, (_check("success"),), passes=False
    ),
    "neutral-without-reason-fails": GateCase(_packet("neutral"), (_check("neutral"),), False),
    "neutral-other-skip-recognizer-fails": GateCase(
        _packet("neutral", tier="skip", recognizer="pinBump", reason="pin bump"),
        (_check("neutral"),),
        passes=False,
    ),
    "neutral-lite-tier-fails": GateCase(
        _packet("neutral", tier="lite", recognizer="ignorePaths"), (_check("neutral"),), False
    ),
    "failure-fails": GateCase(_packet("failure"), (_check("failure"),), passes=False),
    "failure-with-ignore-triage-fails": GateCase(
        _packet("failure", tier="skip", recognizer="ignorePaths"), (_check("failure"),), False
    ),
}
_GATE_IDS = list(_GATE_CASES)


@pytest.mark.parametrize("case_id", _GATE_IDS, ids=_GATE_IDS)
def test_self_gate(case_id: str, tmp_path: Path) -> None:
    case = _GATE_CASES[case_id]
    packets = {} if case.packet is None else {"opencode-go": case.packet}
    recorded = _record_self(tmp_path, packets)
    completed, _ = _gate_self(tmp_path, recorded, list(case.checks))
    assert (completed.returncode == 0) is case.passes, completed.stdout + completed.stderr


@pytest.mark.parametrize(
    ("case", "passes"),
    [
        pytest.param("policy", True, id="head-bound-policy"),
        pytest.param("missing_packet", False, id="missing-packet"),
        pytest.param("unknown_recognizer", False, id="unknown-recognizer"),
        pytest.param("wrong_tier", False, id="wrong-tier"),
        pytest.param("stale_packet_head", False, id="stale-packet-head"),
        pytest.param("missing_check", False, id="missing-check"),
        pytest.param("wrong_check_head", False, id="wrong-check-head"),
        pytest.param("wrong_attempt", False, id="wrong-attempt"),
        pytest.param("wrong_publisher", False, id="wrong-publisher"),
        pytest.param("wrong_conclusion", False, id="wrong-conclusion"),
    ],
)
def test_self_gate_policy_skip_requires_bound_packet_and_check(
    tmp_path: Path, case: str, *, passes: bool
) -> None:
    packet = _packet("neutral", tier="skip", recognizer="reviewPolicy")
    packet["reviewed_head_sha"] = HEAD_SHA
    check = _check("neutral")
    if case == "unknown_recognizer":
        packet["triage"]["recognizer"] = "unrecognized"
    elif case == "wrong_tier":
        packet["triage"]["tier"] = "full"
    elif case == "stale_packet_head":
        packet["reviewed_head_sha"] = "c" * 40
    elif case == "wrong_check_head":
        check["head_sha"] = "c" * 40
    elif case == "wrong_attempt":
        check["external_id"] = f"{RUN_ID}:1"
    elif case == "wrong_publisher":
        check["app"] = {"id": 999, "slug": "unrelated"}
    elif case == "wrong_conclusion":
        check["conclusion"] = "failure"

    packets = {} if case == "missing_packet" else {"opencode-go": packet}
    recorded = _record_self(tmp_path, packets)
    checks = [] if case == "missing_check" else [check]
    completed, summary = _gate_self(tmp_path, recorded, checks)
    assert (completed.returncode == 0) is passes, completed.stdout + completed.stderr
    if passes:
        assert recorded["approval_reason"] == "review_policy"
        assert "No approval was granted." in summary


@pytest.mark.parametrize(
    "relative", [_HARDENED_TPL, _HARDENED, _DOGFOOD], ids=["tpl", "hardened", "dogfood"]
)
@pytest.mark.parametrize("case_id", _GATE_IDS, ids=_GATE_IDS)
def test_consumer_gate(relative: str, case_id: str, tmp_path: Path) -> None:
    case = _GATE_CASES[case_id]
    completed, _ = _gate_consumer(relative, tmp_path, case.packet, list(case.checks))
    assert (completed.returncode == 0) is case.passes, completed.stdout + completed.stderr


def test_self_gate_names_the_reason_and_count_as_a_notice(tmp_path: Path) -> None:
    recorded = _record_self(tmp_path, {"opencode-go": _ALL_IGNORED})
    completed, summary = _gate_self(tmp_path, recorded, [_check("neutral")])

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "::notice title=mergecraft not reviewed::" in completed.stdout
    assert "all 2 changed files are ignored by review.ignorePaths" in completed.stdout
    assert "passing without a review" in completed.stdout
    assert "::error" not in completed.stdout
    assert "not reviewed" in summary
    assert HEAD_SHA in summary


@pytest.mark.parametrize("relative", [_HARDENED, _DOGFOOD], ids=["hardened", "dogfood"])
def test_consumer_gate_names_the_reason_and_count_as_a_notice(
    relative: str, tmp_path: Path
) -> None:
    completed, summary = _gate_consumer(relative, tmp_path, _ALL_IGNORED, [_check("neutral")])

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "::notice title=mergeCraft not reviewed::" in completed.stdout
    assert "all 2 changed files are ignored by review.ignorePaths" in completed.stdout
    assert "::error" not in completed.stdout
    assert "not reviewed" in summary


@pytest.mark.parametrize("api_available", [True, False], ids=["missing-check", "api-error"])
@pytest.mark.parametrize(
    ("outcome", "passes"), [("failure", False), ("success", True)], ids=["failed", "successful"]
)
def test_hardened_gate_honors_review_step_outcome(
    tmp_path: Path, api_available: bool, outcome: str, passes: bool
) -> None:
    step = _step(_HARDENED_TPL, "review", name=_GATE_STEP)
    assert step["env"]["REVIEW_STEP_OUTCOME"] == "${{ steps.mergecraft.outcome }}"
    gh_bin = _gh_mock(tmp_path, [])
    if not api_available:
        (gh_bin / "gh").write_text("#!/bin/bash\nexit 1\n", encoding="utf-8")
        sleep = gh_bin / "sleep"
        sleep.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
        sleep.chmod(0o755)
    completed, _, _ = _run_script(
        str(step["run"]), tmp_path, {"REVIEW_STEP_OUTCOME": outcome}, path_prefix=gh_bin
    )
    assert (completed.returncode == 0) is passes, completed.stdout + completed.stderr
    if not passes:
        assert "review step failed" in completed.stdout
        assert "check-runs query failed" not in completed.stderr


def test_ordinary_neutral_keeps_todays_error(tmp_path: Path) -> None:
    recorded = _record_self(tmp_path, {"codex": _packet("neutral")})
    completed, _ = _gate_self(tmp_path, recorded, [_check("neutral")])

    assert completed.returncode != 0
    assert "mergecraft review verdict is neutral (rung=codex)" in completed.stdout


# ── verdict recorder ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("packets", "reason", "count"),
    [
        ({"opencode-go": _ALL_IGNORED}, "ignore_paths", "2"),
        ({"opencode-go": _packet("neutral")}, "", ""),
        ({"opencode-go": _packet("success", tier="skip", recognizer="ignorePaths")}, "", ""),
        ({"opencode-go": _ALL_IGNORED, "codex": _packet("neutral")}, "", ""),
        (
            {"opencode-go": _packet("neutral", tier="skip", recognizer="ignorePaths", reason="x")},
            "ignore_paths",
            "",
        ),
        ({}, "", ""),
    ],
    ids=[
        "all-ignored",
        "plain-neutral",
        "success-is-not-the-ignore-neutral",
        "last-rung-decides",
        "unparsable-count-keeps-the-reason",
        "no-packet",
    ],
)
def test_recorder_exports_the_reason_from_the_last_rungs_packet(
    tmp_path: Path, packets: dict[str, dict[str, Any]], reason: str, count: str
) -> None:
    recorded = _record_self(tmp_path, packets)
    assert recorded.get("approval_reason") == reason
    assert recorded.get("approval_ignored_count") == count


def test_reason_crosses_jobs_as_review_backstop_outputs() -> None:
    """A job output can only be written by this run, which binds the reason to it."""
    recorder = _step(_SELF, "review-backstop", step_id="approval_verdict")
    assert recorder["env"]["HEAD_SHA"] == "${{ github.event.pull_request.head.sha }}"
    doc = _load(_SELF)
    outputs = job(doc, "review-backstop").get("outputs") or {}
    assert "steps.approval_verdict.outputs.approval_reason" in outputs["approval_reason"]
    assert (
        "steps.approval_verdict.outputs.approval_ignored_count" in outputs["approval_ignored_count"]
    )
    env = _step(_SELF, "approval-gate", name=_GATE_STEP).get("env") or {}
    assert env["APPROVAL_REASON"] == "${{ needs.review-backstop.outputs.approval_reason }}"
    assert (
        env["APPROVAL_IGNORED_COUNT"]
        == "${{ needs.review-backstop.outputs.approval_ignored_count }}"
    )


@pytest.mark.parametrize(
    "relative", [_HARDENED_TPL, _HARDENED, _DOGFOOD], ids=["tpl", "hardened", "dogfood"]
)
def test_consumer_gate_reads_the_reason_from_the_actions_own_packet(relative: str) -> None:
    """The evaluator above mirrors these exact expressions."""
    env = _step(relative, "review", name=_GATE_STEP).get("env") or {}
    for key, expression in _PACKET_EXPRESSIONS.items():
        assert env[key] == expression, key


# ── skipped review still follows SKIPPED_REVIEW ─────────────────────────────


@pytest.mark.parametrize(
    ("relative", "job_name"),
    [(_SELF, "approval-gate"), (_HARDENED, "review"), (_DOGFOOD, "review")],
    ids=["self", "hardened", "dogfood"],
)
@pytest.mark.parametrize(
    ("setting", "passes"), [("fail", False), ("pass", True)], ids=["fail", "pass"]
)
def test_skipped_review_follows_skipped_review(
    tmp_path: Path, relative: str, job_name: str, setting: str, *, passes: bool
) -> None:
    step = _step(relative, job_name, name=_SKIP_STEP)
    completed, _, _ = _run_script(
        str(step["run"]), tmp_path, {"SKIPPED_REVIEW": setting, "IS_SAME_REPO": "false"}
    )
    assert (completed.returncode == 0) is passes


# ── rung short-circuit ──────────────────────────────────────────────────────


def test_codex_fallback_is_not_spent_on_an_all_ignored_neutral(tmp_path: Path) -> None:
    root = stage_trusted_copy(tmp_path)
    outputs, completed = run_decide_script(
        tmp_path,
        root / "scripts/decide_codex_fallback.sh",
        env={"OPENCODE_GO_OUTCOME": "success", "OPENCODE_GO_PACKET": json.dumps(_ALL_IGNORED)},
        cwd=root,
    )
    assert completed.returncode == 0, completed.stderr
    assert outputs.get("need") == "false"
    assert "ignorePaths" in completed.stdout


@pytest.mark.parametrize(
    ("head", "conclusion", "external_id", "need"),
    [
        (HEAD_SHA, "neutral", f"{RUN_ID}:{RUN_ATTEMPT}", "false"),
        ("stale-head", "neutral", f"{RUN_ID}:{RUN_ATTEMPT}", "true"),
        (HEAD_SHA, "neutral", f"{RUN_ID}:1", "true"),
        (HEAD_SHA, "failure", f"{RUN_ID}:{RUN_ATTEMPT}", "true"),
    ],
    ids=["attributed", "stale-packet-head", "stale-check-attempt", "wrong-check-conclusion"],
)
def test_codex_policy_skip_requires_current_packet_and_neutral_check(
    tmp_path: Path, head: str, conclusion: str, external_id: str, need: str
) -> None:
    root = stage_trusted_copy(tmp_path)
    packet = _packet("neutral", tier="skip", recognizer="reviewPolicy")
    packet["reviewed_head_sha"] = head
    outputs, _ = run_decide_script(
        tmp_path,
        root / "scripts/decide_codex_fallback.sh",
        env={"OPENCODE_GO_OUTCOME": "success", "OPENCODE_GO_PACKET": json.dumps(packet)},
        gh_mock_dir=write_gh_mock(tmp_path, conclusion=conclusion, external_id=external_id),
        cwd=root,
    )
    assert outputs["need"] == need


@pytest.mark.parametrize("packet", ["", "{not-json"], ids=["missing", "malformed"])
def test_codex_cannot_infer_policy_skip_without_a_typed_packet(tmp_path: Path, packet: str) -> None:
    root = stage_trusted_copy(tmp_path)
    outputs, _ = run_decide_script(
        tmp_path,
        root / "scripts/decide_codex_fallback.sh",
        env={"OPENCODE_GO_OUTCOME": "success", "OPENCODE_GO_PACKET": packet},
        gh_mock_dir=write_gh_mock(tmp_path, conclusion="neutral"),
        cwd=root,
    )
    assert outputs["need"] == "true"


@pytest.mark.parametrize(
    ("head", "checks", "passes"),
    [
        (HEAD_SHA, (_check("neutral"),), True),
        ("stale-head", (_check("neutral"),), False),
        (HEAD_SHA, (_check("neutral", external_id=f"{RUN_ID}:1"),), False),
        (HEAD_SHA, (), False),
        (HEAD_SHA, (_check("neutral", app={"id": 7, "slug": "foreign"}),), False),
    ],
    ids=["attributed", "stale-packet-head", "stale-check-attempt", "no-check", "wrong-publisher"],
)
def test_hardened_policy_skip_requires_current_packet_and_neutral_check(
    tmp_path: Path, head: str, checks: tuple[dict[str, Any], ...], passes: bool
) -> None:
    step = _step(_HARDENED_TPL, "review", name=_GATE_STEP)
    env = _packet_env(_packet("neutral", tier="skip", recognizer="reviewPolicy"))
    env["REVIEWED_HEAD_SHA"] = head
    completed, _, summary = _run_script(
        str(step["run"]), tmp_path, env, path_prefix=_gh_mock(tmp_path, list(checks))
    )
    assert (completed.returncode == 0) is passes
    if passes:
        assert "not reviewed" in summary.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "packet",
    [
        _packet("neutral"),
        _packet("neutral", tier="skip", recognizer="pinBump"),
        _packet("neutral", tier="lite", recognizer="ignorePaths"),
    ],
    ids=["plain-neutral", "other-skip-recognizer", "lite-tier"],
)
def test_codex_fallback_still_runs_for_every_other_neutral(
    tmp_path: Path, packet: dict[str, Any]
) -> None:
    root = stage_trusted_copy(tmp_path)
    outputs, completed = run_decide_script(
        tmp_path,
        root / "scripts/decide_codex_fallback.sh",
        env={"OPENCODE_GO_OUTCOME": "success", "OPENCODE_GO_PACKET": json.dumps(packet)},
        cwd=root,
    )
    assert completed.returncode == 0, completed.stderr
    assert outputs.get("need") == "true"


@pytest.mark.parametrize(
    ("packet", "need"),
    [(_ALL_IGNORED, "false"), (_packet("neutral"), "true")],
    ids=["all-ignored-holds-backstop", "failover-neutral-spends-backstop"],
)
def test_claude_backstop_after_a_failover_eligible_rung(
    tmp_path: Path, packet: dict[str, Any], need: str
) -> None:
    """A failover-eligible failure normally lets a neutral through; not this one."""
    root = stage_trusted_copy(tmp_path)
    gh_dir = write_gh_mock(tmp_path, conclusion="neutral")
    outputs, completed = run_decide_script(
        tmp_path,
        root / "scripts/decide_claude_fallback.sh",
        env={
            "OPENCODE_GO_OUTCOME": "failure",
            "OPENCODE_GO_FAILOVER_ELIGIBLE": "true",
            "CODEX_OUTCOME": "skipped",
            "OPENCODE_GO_PACKET": json.dumps(packet),
        },
        gh_mock_dir=gh_dir,
        cwd=root,
    )
    assert completed.returncode == 0, completed.stderr
    assert outputs.get("need") == need


def test_codex_job_runs_only_when_the_decide_step_asks() -> None:
    """``need=false`` from the decide step is what keeps ``review-codex`` from starting."""
    doc = _load(_SELF)
    codex_needed = job(doc, "review")["outputs"]["codex_needed"]
    assert "steps.fallback.outputs.need == 'true'" in codex_needed
    assert "needs.review.outputs.codex_needed == 'true'" in job(doc, "review-codex")["if"]


# ── template parity ─────────────────────────────────────────────────────────


def _all_ignored_branch(relative: str, job_name: str) -> str:
    run = str(_step(relative, job_name, name=_GATE_STEP)["run"])
    start = run.index("# Every changed file is ignored")
    end = run.index('if [ "${verdict}" != "success" ]', start)
    return run[start:end]


def test_hardened_example_and_dogfood_carry_the_templates_branch() -> None:
    expected = _all_ignored_branch(_HARDENED_TPL, "review")
    assert _all_ignored_branch(_HARDENED, "review") == expected
    assert _all_ignored_branch(_DOGFOOD, "review") == expected
