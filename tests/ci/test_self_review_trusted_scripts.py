"""The privileged review job must not execute scripts from the PR workspace.

A mergeCraft rung checks the PR head out *into* ``$GITHUB_WORKSPACE`` and then
hands the same workspace to the next step. After the first rung, anything the
job reads from the workspace belongs to the branch under review — including the
fallback decision scripts, which the job runs with a write-scoped token. The
scripts must therefore run from a copy taken while the workspace is still the
trusted default-branch checkout, stored somewhere the container never mounts,
with its content hash recorded and re-verified before every use.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from tests.ci.support_self_review_cascade import (
    TRUSTED_SCRIPTS,
    evidence_packet,
    run_decide_script,
    stage_trusted_copy,
    step_by_id,
    write_gh_mock,
)
from tests.ci.workflow_support import REPO_ROOT, job, load_workflow

_WORKFLOW = "mergecraft.yml"
_REVIEW_JOB = "review"
_MERGECRAFT_ACTION = "alexhawat/mergeCraft@"
_TRUSTED_MARKER = "mergecraft-trusted-"

# `./scripts/...`, a bare `scripts/...` command, or `bash|sh|source scripts/...`.
# An absolute runner-home path such as `$HOME/mergecraft-trusted-<id>/scripts/...`
# is deliberately not a match: the lookbehind excludes a preceding `/`, `$`,
# `~`, `.`, `-` or word character.
_WORKSPACE_RELATIVE = re.compile(
    r"(?m)^\s*(?:bash|sh|source|\.)\s+scripts/"
    r"|(?<![\w/$.~-])\./[\w./-]+"
    r"|(?<![\w/$.~-])scripts/[\w./-]+"
)
_SCRIPT_REFERENCE = re.compile(r"scripts/(?:lib/)?[\w./-]+\.sh")


def _review_steps() -> list[dict[str, object]]:
    steps = job(load_workflow(_WORKFLOW), _REVIEW_JOB).get("steps")
    assert isinstance(steps, list), "review job steps must be a list"
    return [step for step in steps if isinstance(step, dict)]


def _first_mergecraft_index(steps: list[dict[str, object]]) -> int:
    for index, step in enumerate(steps):
        uses = step.get("uses")
        if isinstance(uses, str) and uses.startswith(_MERGECRAFT_ACTION):
            return index
    raise AssertionError(f"review job has no step using {_MERGECRAFT_ACTION}…")


def _trusted_copy_step(
    steps: list[dict[str, object]],
) -> tuple[int, dict[str, object]]:
    for index, step in enumerate(steps):
        run = step.get("run")
        if isinstance(run, str) and _TRUSTED_MARKER in run:
            return index, step
    raise AssertionError(
        "review job has no step staging a trusted copy under a "
        f"{_TRUSTED_MARKER!r} path; the decide scripts still run from the workspace"
    )


def test_no_workspace_relative_script_runs_after_a_mergecraft_step() -> None:
    """Once a rung has switched the workspace to the PR head, stop reading it."""
    steps = _review_steps()
    start = _first_mergecraft_index(steps)
    offending = [
        str(step.get("name") or index)
        for index, step in enumerate(steps[start:], start=start)
        if isinstance(step.get("run"), str) and _WORKSPACE_RELATIVE.search(str(step["run"]))
    ]
    assert not offending, (
        "review job runs workspace-relative scripts after the first mergeCraft "
        f"step: {offending}; the workspace holds PR-head content by then"
    )


def test_a_trusted_copy_is_staged_before_the_first_mergecraft_step() -> None:
    """Copy the three scripts out of the trusted checkout, hash them, hide them."""
    steps = _review_steps()
    copy_index, copy_step = _trusted_copy_step(steps)
    assert copy_index < _first_mergecraft_index(steps), (
        "the trusted copy must be taken before the first mergeCraft step — that is "
        "the last point at which the workspace is provably the default branch"
    )
    run = str(copy_step.get("run"))
    assert "GITHUB_SHA" in run, "the trusted-copy step must reference GITHUB_SHA"
    assert "git rev-parse" in run, (
        "the trusted-copy step must assert HEAD == GITHUB_SHA before copying"
    )
    assert "sha256sum" in run, (
        "the trusted-copy step must record the copied files' sha256sum in a step output"
    )
    assert "GITHUB_OUTPUT" in run, "the sha256sum must be written as a step output"
    assert copy_step.get("id"), "the trusted-copy step needs an id so decide steps can use it"
    assert set(_SCRIPT_REFERENCE.findall(run)) == set(TRUSTED_SCRIPTS), (
        f"the trusted copy must stage exactly {list(TRUSTED_SCRIPTS)}"
    )
    assert "$HOME" in run or "${HOME}" in run, (
        "the copy must live under the runner home, outside every Docker mount"
    )
    destination_lines = [line for line in run.splitlines() if _TRUSTED_MARKER in line]
    assert destination_lines, "no destination path mentions the trusted-copy root"
    assert any("HOME" in line for line in destination_lines), (
        "the trusted-copy destination must be under $HOME"
    )
    for line in destination_lines:
        assert "RUNNER_TEMP" not in line, (
            "$RUNNER_TEMP is mounted into the Action container and the workspace is "
            "the tree the PR can rewrite; neither is a safe home for the copy"
        )
        assert "GITHUB_WORKSPACE" not in line, (
            "the workspace is the tree the PR can rewrite; it is not a safe home "
            "for the trusted copy"
        )
    assert "RUNNER_TEMP" not in run, (
        "$RUNNER_TEMP is Docker-mounted into the Action container, so a compromised "
        "rung could rewrite the decide scripts there"
    )


def test_decide_steps_run_the_verified_copy() -> None:
    steps = _review_steps()
    _, copy_step = _trusted_copy_step(steps)
    copy_id = copy_step.get("id")
    assert isinstance(copy_id, str), "trusted-copy step is missing an id"
    assert copy_id, "trusted-copy step id must not be empty"
    for step_id in ("fallback", "claude_fallback"):
        step = step_by_id(step_id)
        blob = yaml.safe_dump(step)
        run = step.get("run")
        assert isinstance(run, str), f"{step_id} has no run:"
        assert f"steps.{copy_id}." in blob or _TRUSTED_MARKER in run, (
            f"{step_id} does not run the staged copy; it still resolves the script "
            "relative to the workspace"
        )
        assert "sha256sum" in run, (
            f"{step_id} must re-verify the copied scripts' hashes before running them"
        )


def test_no_workflow_comment_claims_the_job_never_checks_out() -> None:
    """The false premise that hid the workspace-ownership change must be gone."""
    text = (REPO_ROOT / ".github/workflows/mergecraft.yml").read_text(encoding="utf-8")
    assert "never checks out" not in text.lower(), (
        "mergecraft.yml still claims the review job never checks out, directly "
        "beneath the actions/checkout step that does"
    )


@pytest.mark.parametrize(
    ("script_rel", "env"),
    [
        (
            "scripts/decide_codex_fallback.sh",
            {"NOUS_OUTCOME": "success", "NOUS_PACKET": evidence_packet(verdict="failure")},
        ),
        (
            "scripts/decide_claude_fallback.sh",
            {
                "NOUS_OUTCOME": "failure",
                "CODEX_OUTCOME": "failure",
                "NOUS_PACKET": "",
                "CODEX_PACKET": "",
            },
        ),
    ],
)
def test_decide_scripts_still_produce_need_from_a_trusted_copy(
    tmp_path: Path,
    script_rel: str,
    env: dict[str, str],
) -> None:
    """Relative library resolution must survive the copy, or the cascade breaks."""
    root = stage_trusted_copy(tmp_path)
    gh_dir = write_gh_mock(tmp_path, conclusion="neutral")
    outputs, completed = run_decide_script(
        tmp_path,
        root / script_rel,
        env=env,
        gh_mock_dir=gh_dir,
        cwd=root,
    )
    assert completed.returncode == 0, (
        f"{script_rel} failed from the trusted copy: stderr={completed.stderr!r}"
    )
    assert outputs.get("need") in {"true", "false"}, (
        f"{script_rel} did not emit need= from the trusted copy: {outputs!r}"
    )
