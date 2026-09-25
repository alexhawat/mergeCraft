"""Shared helpers for lane D cascade decide-step contract tests."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Any

from tests.ci.workflow_support import REPO_ROOT, job, load_workflow

_WORKFLOW = "mergecraft.yml"
_REVIEW_JOB = "review"
_SCRIPT_BY_STEP_ID = {
    "fallback": "scripts/decide_codex_fallback.sh",
    "claude_fallback": "scripts/decide_claude_fallback.sh",
}
# The scripts the trusted-copy step must stage, preserving layout so a copy
# resolves its shared library from ``$(dirname "$0")/..`` exactly as the
# workspace copy does.
TRUSTED_SCRIPTS = (
    "scripts/decide_codex_fallback.sh",
    "scripts/decide_claude_fallback.sh",
    "scripts/lib/provider_verdict_guard.sh",
)
# A stable head SHA and run identity the mock check-run payload and the decide
# steps agree on. The real gate binds a check to ``<run_id>:<run_attempt>``.
HEAD_SHA = "abc123def4567890abcdef1234567890abcd1234"
RUN_ID = "123"
RUN_ATTEMPT = "2"


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
    app_id: int = 15368,
    app_slug: str = "github-actions",
    external_id: str = f"{RUN_ID}:{RUN_ATTEMPT}",
) -> Path:
    """Install a fake ``gh`` that answers mergecraft-approval check-run queries.

    The payload carries the fields the run-bound filter reads — issuer ``app``,
    ``head_sha`` and ``external_id`` — so the same mock exercises both the old
    name-only lookup and the attributable lookup without changing callers.
    """
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
                        "status": "completed",
                        "head_sha": HEAD_SHA,
                        "external_id": external_id,
                        "completed_at": "2026-09-01T00:00:00Z",
                        "app": {"id": app_id, "slug": app_slug},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    gh_path.write_text(
        textwrap.dedent(
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
        ).replace("__PAYLOAD__", str(payload_path)),
        encoding="utf-8",
    )
    gh_path.chmod(0o755)
    return bin_dir


def stage_trusted_copy(tmp_path: Path, *, run_id: str = RUN_ID) -> Path:
    """Stage the three decide scripts under a runner-home trusted root.

    Mirrors the layout the self-workflow's trusted-copy step produces before
    any mergeCraft step runs: ``<root>/scripts/...`` with the shared library in
    ``<root>/scripts/lib/``, so the copy resolves its own library relative to
    the copied script rather than the checkout.
    """
    root = tmp_path / f"mergecraft-trusted-{run_id}"
    for relative in TRUSTED_SCRIPTS:
        source = REPO_ROOT / relative
        assert source.is_file(), f"missing trusted script at {relative}"
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return root


def run_decide_script(
    tmp_path: Path,
    script: Path,
    *,
    env: dict[str, str],
    gh_mock_dir: Path | None = None,
    cwd: Path | None = None,
) -> tuple[dict[str, str], subprocess.CompletedProcess[str]]:
    """Execute a decide-step bash script and return parsed ``GITHUB_OUTPUT``.

    ``cwd`` defaults to the repository root; pass a trusted-copy root to prove
    the script carries no dependency on the checkout it was copied out of.
    """
    output = tmp_path / "github_output"
    output.write_text("", encoding="utf-8")
    script_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path),
        "GITHUB_OUTPUT": str(output),
        "GITHUB_RUN_ID": RUN_ID,
        "GITHUB_RUN_ATTEMPT": RUN_ATTEMPT,
        "EVENT_NAME": "pull_request_target",
        "REPO": "acme/demo",
        "HEAD_SHA": HEAD_SHA,
        "BASELINE_ID": "111222333",
    }
    if gh_mock_dir is not None:
        script_env["PATH"] = f"{gh_mock_dir}:{script_env['PATH']}"
    script_env.update(env)
    completed = subprocess.run(
        [str(script)],
        check=False,
        capture_output=True,
        text=True,
        env=script_env,
        cwd=str(cwd if cwd is not None else REPO_ROOT),
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
