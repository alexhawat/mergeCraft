"""F4 / F5 (#749, #750) — the pin automation may only claim what it can do.

The contract is exercised by *running* the workflow's shell snippets under
stubs, not by asserting on the YAML text: the subject titles are read back out
of ``$GITHUB_OUTPUT`` and the push behaviour is read from a recording ``git``
stub. ``stage=manifest`` must emit a Conventional-Commit subject at or under
the 72-character cap; ``stage=pin`` must not attempt the ``GITHUB_TOKEN`` push
GitHub refuses by construction, and must instead print the exact local command
plus the reason.
"""

from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING, Any

from tests.ci.workflow_support import REPO_ROOT, job, load_workflow

if TYPE_CHECKING:
    from pathlib import Path

_WORKFLOW = "bump-action-pin.yml"
_JOB = "prepare"
_SUBJECT_CAP = 72
_DIGEST = "sha256:" + "a" * 64
_MANIFEST_COMMIT = "b" * 40
_STUB_PREAMBLE = (
    "set -euo pipefail\n"
    "make() { return 0; }\n"
    'git() { printf "%s\\n" "$*" >> "$GIT_CALL_LOG"; case "$1" in diff) return 1 ;; esac; return 0; }\n'
)


def _steps() -> list[dict[str, Any]]:
    return list(job(load_workflow(_WORKFLOW), _JOB)["steps"])


def _run_step(
    step: dict[str, Any],
    *,
    env: dict[str, str],
    tmp_path: Path,
) -> tuple[subprocess.CompletedProcess[str], str, str, str]:
    """Execute one step's ``run`` body under stubs.

    Returns ``(process, step_summary, git_calls, github_output)``.
    """
    label = str(step.get("name", "step")).lower().replace(" ", "-")
    summary_path = tmp_path / f"{label}.summary"
    output_path = tmp_path / f"{label}.output"
    git_log = tmp_path / f"{label}.git"
    script = _STUB_PREAMBLE + str(step["run"]) + "\n"
    full_env = {
        **os.environ,
        **env,
        "GITHUB_OUTPUT": str(output_path),
        "GITHUB_STEP_SUMMARY": str(summary_path),
        "GIT_CALL_LOG": str(git_log),
    }
    proc = subprocess.run(
        ["bash", "-c", script],
        cwd=REPO_ROOT,
        env=full_env,
        capture_output=True,
        text=True,
        check=False,
    )
    summary = summary_path.read_text(encoding="utf-8") if summary_path.exists() else ""
    calls = git_log.read_text(encoding="utf-8") if git_log.exists() else ""
    output = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
    return proc, summary, calls, output


def _step_named(name: str) -> dict[str, Any]:
    for step in _steps():
        if step.get("name") == name:
            return step
    raise AssertionError(f"step {name!r} missing from {_WORKFLOW}")


def _title_from_output(github_output: str) -> str:
    for line in github_output.splitlines():
        if line.startswith("title="):
            return line[len("title=") :]
    raise AssertionError(f"step did not write a title to $GITHUB_OUTPUT: {github_output!r}")


def _title_for_stage(stage: str, tmp_path: Path) -> str:
    env = {
        "STAGE": stage,
        "IMAGE_DIGEST": _DIGEST,
        "SHORT": "abcd1234",
        "MANIFEST_COMMIT": _MANIFEST_COMMIT,
        "SOURCE_REVISION": "c" * 40,
        "GH_TOKEN": "not-a-real-token",
    }
    proc, _summary, _calls, output = _run_step(
        _step_named("Prepare the change"), env=env, tmp_path=tmp_path
    )
    assert proc.returncode == 0, (
        f"stage={stage} prepare snippet failed:\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    return _title_from_output(output)


def test_manifest_stage_subject_is_within_the_commit_cap(tmp_path: Path) -> None:
    """F4 (#749) — ``stage=manifest`` must emit a subject <= 72 characters."""
    title = _title_for_stage("manifest", tmp_path)
    assert title.startswith("chore(action): ")
    assert len(title) <= _SUBJECT_CAP, (
        f"stage=manifest subject is {len(title)} characters (cap {_SUBJECT_CAP}): {title!r}"
    )


def test_pin_stage_subject_is_within_the_commit_cap(tmp_path: Path) -> None:
    """F4 (#749) — ``stage=pin`` already truncates; keep it that way."""
    title = _title_for_stage("pin", tmp_path)
    assert title.startswith("chore(action): ")
    assert len(title) <= _SUBJECT_CAP, (
        f"stage=pin subject is {len(title)} characters (cap {_SUBJECT_CAP}): {title!r}"
    )


def _pin_stage_run_steps() -> list[dict[str, Any]]:
    """Run steps that execute for ``stage=pin`` (manifest-only steps are skipped)."""
    selected: list[dict[str, Any]] = []
    for step in _steps():
        if "run" not in step:
            continue
        condition = str(step.get("if", ""))
        if "stage == 'manifest'" in condition or 'stage == "manifest"' in condition:
            continue
        selected.append(step)
    return selected


def test_pin_stage_does_not_attempt_a_git_push(tmp_path: Path) -> None:
    """F5 (#750) — GitHub refuses a ``GITHUB_TOKEN`` push touching workflows."""
    env = {
        "STAGE": "pin",
        "IMAGE_DIGEST": "",
        "SHORT": "",
        "MANIFEST_COMMIT": _MANIFEST_COMMIT,
        "SOURCE_REVISION": "",
        "GH_TOKEN": "not-a-real-token",
        "BRANCH": f"chore/action-pin-{_MANIFEST_COMMIT[:8]}",
        "TITLE": "chore(action): pin self-review to verified manifest bbbbbbbb",
    }
    pushes: list[str] = []
    for step in _pin_stage_run_steps():
        proc, _summary, calls, _output = _run_step(step, env=env, tmp_path=tmp_path)
        assert proc.returncode == 0, (
            f"pin step {step.get('name')!r} failed:\n{proc.stdout}\n{proc.stderr}"
        )
        pushes.extend(line for line in calls.splitlines() if line.startswith("push"))
    assert pushes == [], f"stage=pin must not push; it invoked: {pushes}"


def test_pin_stage_prints_the_prepared_local_command(tmp_path: Path) -> None:
    """F5 (#750) — the pin stage prepares P and hands the operator the command."""
    env = {
        "STAGE": "pin",
        "IMAGE_DIGEST": "",
        "SHORT": "",
        "MANIFEST_COMMIT": _MANIFEST_COMMIT,
        "SOURCE_REVISION": "",
        "GH_TOKEN": "not-a-real-token",
        "BRANCH": f"chore/action-pin-{_MANIFEST_COMMIT[:8]}",
        "TITLE": "chore(action): pin self-review to verified manifest bbbbbbbb",
    }
    proc, summary, _calls, _output = _run_step(
        _step_named("Summarise the next step"), env=env, tmp_path=tmp_path
    )
    assert proc.returncode == 0, f"summary step failed:\n{proc.stdout}\n{proc.stderr}"
    assert "make action-pin-prepare" in summary, (
        "the pin stage must print the exact local command that completes P; "
        f"summary was:\n{summary}"
    )
    assert "RELEASE_BASE_BRANCH=main" in summary
    assert _MANIFEST_COMMIT in summary
    assert "gh pr create" not in summary, (
        "the pin stage cannot push, so it must not advertise opening a PR"
    )


def test_workflow_header_no_longer_claims_to_automate_p() -> None:
    """F5 (#750) — the header advertises C and prepares P, not 'the mechanical half'."""
    header = (REPO_ROOT / ".github" / "workflows" / _WORKFLOW).read_text(encoding="utf-8")
    assert "mechanical half" not in header, (
        "the header must stop claiming to automate the cycle's mechanical half: the pin "
        "stage cannot push"
    )
