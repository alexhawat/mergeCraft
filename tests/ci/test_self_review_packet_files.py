"""The self-review passes evidence packets between steps as files, never through env.

A step's environment is capped at 128 KiB per variable (Linux ``MAX_ARG_STRLEN``).
A large PR's packet passed through ``env:`` stopped the persist and verdict
steps from starting ("Argument list too long"), so the gate recorded no verdict
and failed closed although the review had approved (#923). These tests pin the
file hand-off end to end with a packet well past that cap.
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import TYPE_CHECKING, Any

from tests.ci.support_self_review_cascade import (
    decide_script,
    evidence_packet,
    run_decide_script,
    step_by_id,
)
from tests.ci.workflow_support import job, load_workflow

if TYPE_CHECKING:
    from pathlib import Path

_WORKFLOW = "mergecraft.yml"
_ENV_VALUE_CAP = 128 * 1024
_RUNGS = ("opencode-go", "codex", "claude")
_RUNG_LABELS = {"opencode-go": "OpenCode Go", "codex": "Codex", "claude": "Claude"}


def _large_packet(verdict: str) -> str:
    """Return a packet JSON body larger than one environment variable may hold."""
    body = json.dumps({"decision": {"verdict": verdict}, "padding": "x" * (2 * _ENV_VALUE_CAP)})
    assert len(body) > _ENV_VALUE_CAP
    return body


def _review_steps() -> list[dict[str, Any]]:
    steps = job(load_workflow(_WORKFLOW), "review").get("steps")
    assert isinstance(steps, list)
    return [step for step in steps if isinstance(step, dict)]


def _persist_step(rung: str) -> dict[str, Any]:
    name = f"Persist evidence packet ({_RUNG_LABELS[rung]})"
    for step in _review_steps():
        if step.get("name") == name:
            return step
    raise AssertionError(f"review job has no step named {name!r}")


def _run_step(step: dict[str, Any], tmp_path: Path, env: dict[str, str]) -> None:
    """Run a step's ``run:`` body the way Actions does (bash -e -o pipefail)."""
    script = tmp_path / "step.sh"
    script.write_text(str(step["run"]), encoding="utf-8")
    completed = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", str(script)],
        check=False,
        capture_output=True,
        text=True,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), **env},
    )
    assert completed.returncode == 0, completed.stderr


def test_no_review_step_receives_a_packet_through_env() -> None:
    """Only ``outputs.evidence_packet != ''`` (a boolean) may reach a step's env."""
    for step in _review_steps():
        for key, value in (step.get("env") or {}).items():
            text = str(value)
            if "outputs.evidence_packet" not in text:
                continue
            assert "outputs.evidence_packet != ''" in text, (
                f"step {step.get('name')!r} passes a packet through env {key}; "
                "pass a file path instead (#923)"
            )


def test_each_persist_step_copies_the_file_its_rung_wrote(tmp_path: Path) -> None:
    for rung in _RUNGS:
        runner_temp = tmp_path / rung
        evidence = runner_temp / "mergecraft"
        evidence.mkdir(parents=True)
        packet = _large_packet("success")
        (evidence / "acme-demo-7-merge-evidence-packet.json").write_text(packet, encoding="utf-8")

        _run_step(
            _persist_step(rung),
            tmp_path,
            {"RUNNER_TEMP": str(runner_temp), "RUNG_EMITTED_PACKET": "true"},
        )

        assert (runner_temp / f"packet-{rung}.json").read_text(encoding="utf-8") == packet


def test_a_rung_that_emitted_no_packet_persists_nothing(tmp_path: Path) -> None:
    """A packet left by an earlier rung is never filed under a rung that emitted none."""
    evidence = tmp_path / "mergecraft"
    evidence.mkdir()
    (evidence / "acme-demo-7-merge-evidence-packet.json").write_text(
        evidence_packet(verdict="success"), encoding="utf-8"
    )

    _run_step(
        _persist_step("codex"),
        tmp_path,
        {"RUNNER_TEMP": str(tmp_path), "RUNG_EMITTED_PACKET": "false"},
    )

    assert not (tmp_path / "packet-codex.json").exists()


def test_the_verdict_recorder_reads_the_last_rung_from_its_file(tmp_path: Path) -> None:
    files = {rung: tmp_path / f"packet-{rung}.json" for rung in _RUNGS}
    files["opencode-go"].write_text(_large_packet("failure"), encoding="utf-8")
    files["codex"].write_text(_large_packet("success"), encoding="utf-8")
    output = tmp_path / "github_output"
    output.write_text("", encoding="utf-8")

    _run_step(
        step_by_id("approval_verdict"),
        tmp_path,
        {
            "GITHUB_OUTPUT": str(output),
            **{
                f"{rung.upper().replace('-', '_')}_PACKET_FILE": str(path)
                for rung, path in files.items()
            },
        },
    )

    recorded = dict(
        line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines() if line
    )
    assert recorded == {"approval_verdict": "success", "approval_rung": "codex"}


def test_the_codex_fallback_decision_reads_a_large_packet_file(tmp_path: Path) -> None:
    packet = tmp_path / "packet-opencode-go.json"
    packet.write_text(_large_packet("failure"), encoding="utf-8")

    outputs, _ = run_decide_script(
        tmp_path,
        decide_script("fallback"),
        env={"OPENCODE_GO_OUTCOME": "success", "OPENCODE_GO_PACKET_FILE": str(packet)},
    )

    assert outputs.get("need") == "false"


def test_the_claude_backstop_decision_reads_a_large_packet_file(tmp_path: Path) -> None:
    packet = tmp_path / "packet-codex.json"
    packet.write_text(_large_packet("success"), encoding="utf-8")

    outputs, _ = run_decide_script(
        tmp_path,
        decide_script("claude_fallback"),
        env={
            "OPENCODE_GO_OUTCOME": "failure",
            "CODEX_OUTCOME": "failure",
            "CODEX_PACKET_FILE": str(packet),
            "OPENCODE_GO_PACKET_FILE": str(tmp_path / "packet-opencode-go.json"),
        },
    )

    assert outputs.get("need") == "false"
