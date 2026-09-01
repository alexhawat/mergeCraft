"""Shared helpers for lane D cascade decide-step contract tests."""

from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path
from typing import Any

from tests.ci.workflow_support import job, load_workflow

_WORKFLOW = "mergecraft.yml"
_REVIEW_JOB = "review"
_SCRIPT_BY_STEP_ID = {
    "fallback": "scripts/decide_codex_fallback.sh",
    "claude_fallback": "scripts/decide_claude_fallback.sh",
}


def step_by_id(step_id: str) -> dict[str, Any]:
    """Return the review-job step whose ``id`` matches ``step_id``."""
    steps = job(load_workflow(_WORKFLOW), _REVIEW_JOB).get("steps")
    assert isinstance(steps, list), "review job steps must be a list"
    for step in steps:
        if isinstance(step, dict) and step.get("id") == step_id:
            return step
    raise AssertionError(f"review job missing step id={step_id!r}")


def decide_script(step_id: str) -> Path:
    """Return the extracted decide-step script path."""
    rel = _SCRIPT_BY_STEP_ID.get(step_id)
    if rel is None:
        raise AssertionError(f"no extracted script for step id={step_id!r}")
    path = Path(__file__).resolve().parents[2] / rel
    assert path.is_file(), f"missing decide script at {path}"
    return path


def evidence_packet(*, verdict: str | None = None, broken: bool = False) -> str:
    """Build a JSON evidence packet or an intentionally unparseable body."""
    if broken:
        return "{not-json"
    if verdict is None:
        return ""
    return json.dumps({"decision": {"verdict": verdict}})


def parse_github_output(path: Path) -> dict[str, str]:
    """Parse single-line ``key=value`` rows from ``$GITHUB_OUTPUT``."""
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key] = value
    return out


def write_gh_mock(
    tmp_path: Path,
    *,
    check_run_id: str = "999888777",
    conclusion: str = "neutral",
) -> Path:
    """Install a fake ``gh`` that answers mergecraft-approval check-run queries."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    gh_path = bin_dir / "gh"
    payload_path = tmp_path / "gh_check_runs.json"
    payload_path.write_text(
        json.dumps(
            {
                "check_runs": [
                    {
                        "id": int(check_run_id),
                        "name": "mergecraft-approval",
                        "conclusion": conclusion,
                        "completed_at": "2026-09-01T00:00:00Z",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    gh_path.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            if [[ "$*" == *check-runs* ]]; then
              cat {json.dumps(str(payload_path))}
              exit 0
            fi
            echo "unexpected gh invocation: $*" >&2
            exit 1
            """
        ),
        encoding="utf-8",
    )
    gh_path.chmod(0o755)
    return bin_dir


def run_decide_script(
    tmp_path: Path,
    script: Path,
    *,
    env: dict[str, str],
    gh_mock_dir: Path | None = None,
) -> tuple[dict[str, str], subprocess.CompletedProcess[str]]:
    """Execute a decide-step bash script and return parsed ``GITHUB_OUTPUT``."""
    output = tmp_path / "github_output"
    output.write_text("", encoding="utf-8")
    script_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path),
        "GITHUB_OUTPUT": str(output),
        "EVENT_NAME": "pull_request_target",
        "REPO": "acme/demo",
        "HEAD_SHA": "abc123def4567890abcdef1234567890abcd1234",
        "BASELINE_ID": "111222333",
    }
    if gh_mock_dir is not None:
        script_env["PATH"] = f"{gh_mock_dir}:{script_env['PATH']}"
    script_env.update(env)
    repo_root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [str(script)],
        check=False,
        capture_output=True,
        text=True,
        env=script_env,
        cwd=str(repo_root),
    )
    assert completed.returncode == 0, (
        f"decide script failed ({completed.returncode}): "
        f"stdout={completed.stdout!r} stderr={completed.stderr!r}"
    )
    return parse_github_output(output), completed


def claude_step_if_expression() -> str:
    """Return the ``if:`` expression for the Claude decide step."""
    step = step_by_id("claude_fallback")
    expr = step.get("if")
    assert isinstance(expr, str), "claude_fallback missing if:"
    assert expr.strip(), "claude_fallback if: is empty"
    return expr


def claude_review_if_expression() -> str:
    """Return the ``if:`` expression for the Claude review step."""
    steps = job(load_workflow(_WORKFLOW), _REVIEW_JOB).get("steps")
    assert isinstance(steps, list)
    for step in steps:
        if isinstance(step, dict) and step.get("id") == "mergecraft_claude":
            expr = step.get("if")
            assert isinstance(expr, str), "mergecraft_claude missing if:"
            assert expr.strip(), "mergecraft_claude if: is empty"
            return expr
    raise AssertionError("mergecraft_claude step missing")
