"""The pin automation's contracts, exercised by running its shell snippets.

The subjects are read back out of ``$GITHUB_OUTPUT`` and the push/PR behaviour
is read from recording ``git`` and ``gh`` stubs. Both stages push and open a PR
with the App token; merging stays human.
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
_APP_TOKEN = "not-a-real-token"
_STUB_PREAMBLE = (
    "set -euo pipefail\n"
    "make() { return 0; }\n"
    'git() { printf "%s\\n" "$*" >> "$GIT_CALL_LOG"; case "$1" in diff) return 1 ;; esac; return 0; }\n'
    'gh() { printf "%s\\n" "$*" >> "$GH_CALL_LOG"; '
    'case "$*" in *"pr list"*) return 0 ;; *"pr create"*) echo "https://example.test/pr/1" ;; esac; return 0; }\n'
)


def _steps() -> list[dict[str, Any]]:
    return list(job(load_workflow(_WORKFLOW), _JOB)["steps"])


def _run_step(
    step: dict[str, Any],
    *,
    env: dict[str, str],
    tmp_path: Path,
) -> tuple[subprocess.CompletedProcess[str], str, str, str, str]:
    """Execute one step's ``run`` body under stubs.

    Returns ``(process, step_summary, git_calls, gh_calls, github_output)``.
    """
    label = str(step.get("name", "step")).lower().replace(" ", "-")
    summary_path = tmp_path / f"{label}.summary"
    output_path = tmp_path / f"{label}.output"
    git_log = tmp_path / f"{label}.git"
    gh_log = tmp_path / f"{label}.gh"
    script = _STUB_PREAMBLE + str(step["run"]) + "\n"
    full_env = {
        **os.environ,
        **env,
        "GITHUB_OUTPUT": str(output_path),
        "GITHUB_STEP_SUMMARY": str(summary_path),
        "GIT_CALL_LOG": str(git_log),
        "GH_CALL_LOG": str(gh_log),
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
    gh_calls = gh_log.read_text(encoding="utf-8") if gh_log.exists() else ""
    output = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
    return proc, summary, calls, gh_calls, output


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
        "GH_TOKEN": _APP_TOKEN,
    }
    proc, _summary, _calls, _gh_calls, output = _run_step(
        _step_named("Prepare the change"), env=env, tmp_path=tmp_path
    )
    assert proc.returncode == 0, (
        f"stage={stage} prepare snippet failed:\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    return _title_from_output(output)


def test_manifest_stage_subject_is_within_the_commit_cap(tmp_path: Path) -> None:
    title = _title_for_stage("manifest", tmp_path)
    assert title.startswith("chore(action): ")
    assert len(title) <= _SUBJECT_CAP, (
        f"stage=manifest subject is {len(title)} characters (cap {_SUBJECT_CAP}): {title!r}"
    )


def test_pin_stage_subject_is_within_the_commit_cap(tmp_path: Path) -> None:
    title = _title_for_stage("pin", tmp_path)
    assert title.startswith("chore(action): ")
    assert len(title) <= _SUBJECT_CAP, (
        f"stage=pin subject is {len(title)} characters (cap {_SUBJECT_CAP}): {title!r}"
    )


def _pin_env() -> dict[str, str]:
    return {
        "EVENT": "workflow_dispatch",
        "INPUT_STAGE": "pin",
        "INPUT_MANIFEST": _MANIFEST_COMMIT,
        "MERGED_COMMIT": "",
        "STAGE": "pin",
        "IMAGE_DIGEST": "",
        "SHORT": "",
        "MANIFEST_COMMIT": _MANIFEST_COMMIT,
        "SOURCE_REVISION": "",
        "GH_TOKEN": _APP_TOKEN,
        "BRANCH": f"chore/action-pin-{_MANIFEST_COMMIT[:8]}",
        "TITLE": "chore(action): pin self-review to verified manifest bbbbbbbb",
        "PR_URL": "",
    }


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


def test_pin_stage_pushes_the_branch(tmp_path: Path) -> None:
    proc, _summary, calls, _gh_calls, _output = _run_step(
        _step_named("Push the branch"), env=_pin_env(), tmp_path=tmp_path
    )
    assert proc.returncode == 0, f"push step failed:\n{proc.stdout}\n{proc.stderr}"
    pushes = [line for line in calls.splitlines() if line.startswith("push")]
    assert pushes, "the pin stage must push its branch; it invoked no push"


def test_pin_stage_opens_a_pr_with_the_app_token(tmp_path: Path) -> None:
    step = _step_named("Open the pull request")
    assert (step.get("env") or {}).get("GH_TOKEN") == "${{ steps.app-token.outputs.token }}"
    proc, _summary, _calls, gh_calls, output = _run_step(step, env=_pin_env(), tmp_path=tmp_path)
    assert proc.returncode == 0, f"PR step failed:\n{proc.stdout}\n{proc.stderr}"
    assert "pr create" in gh_calls, f"no PR was opened; gh called: {gh_calls!r}"
    assert "url=https://example.test/pr/1" in output


def test_pin_stage_summary_requires_a_merge_commit(tmp_path: Path) -> None:
    proc, summary, _calls, _gh_calls, _output = _run_step(
        _step_named("Summarise the next step"), env=_pin_env(), tmp_path=tmp_path
    )
    assert proc.returncode == 0, f"summary step failed:\n{proc.stdout}\n{proc.stderr}"
    assert "Merge it with a merge commit" in summary
    assert _MANIFEST_COMMIT in summary


def test_header_says_merging_stays_human() -> None:
    header = (REPO_ROOT / ".github" / "workflows" / _WORKFLOW).read_text(encoding="utf-8")
    assert "What stays human: merging" in header
    assert "never merges" in header
