"""#529 — workflow_dispatch must share the pull_request_target review prompt.

A dispatch run with no ``prompt`` input used to hand the agent
``Review the current pull request.`` — no PR number, no
``mergecraft_checkout_pr`` instruction. The agent then spent ~48 turns
discovering the PR. Both event paths now build the same prompt from one
script; an explicit ``inputs.prompt`` still passes through unchanged.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.ci.workflow_support import job, load_workflow

_WORKFLOW = "mergecraft.yml"
_REVIEW_JOB = "review"
_RESOLVE_STEP = "Resolve PR for workflow_dispatch"
_COMPOSE_STEP = "Compose review prompt"
_CHECKOUT_PR = "mergecraft_checkout_pr"
_BARE_FALLBACK = "Review the current pull request."


def _review_steps() -> list[dict[str, Any]]:
    steps = job(load_workflow(_WORKFLOW), _REVIEW_JOB).get("steps")
    assert isinstance(steps, list), "review job steps must be a list"
    return [step for step in steps if isinstance(step, dict)]


def _step(name: str) -> dict[str, Any]:
    for step in _review_steps():
        if step.get("name") == name:
            return step
    raise AssertionError(f"review job is missing step {name!r}")


def _compose_script() -> str:
    run = _step(_COMPOSE_STEP).get("run")
    assert isinstance(run, str), "Compose review prompt has no run script"
    assert run.strip(), "Compose review prompt run script is empty"
    return run


def _prompt_from_github_output(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    start = "text<<MERGECRAFT_PROMPT_EOF\n"
    end = "\nMERGECRAFT_PROMPT_EOF\n"
    assert start in text, f"GITHUB_OUTPUT missing prompt delimiter: {text!r}"
    after = text.split(start, 1)[1]
    assert end in after or after.endswith("\nMERGECRAFT_PROMPT_EOF"), text
    body = after.rsplit("MERGECRAFT_PROMPT_EOF", 1)[0]
    return body.rstrip("\n")


def _run_compose(
    tmp_path: Path,
    *,
    env: dict[str, str],
) -> str:
    output = tmp_path / "github_output"
    output.write_text("", encoding="utf-8")
    script_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "GITHUB_OUTPUT": str(output),
        "HOME": str(tmp_path),
    }
    script_env.update(env)
    completed = subprocess.run(
        ["bash", "-c", _compose_script()],
        check=False,
        capture_output=True,
        text=True,
        env=script_env,
    )
    assert completed.returncode == 0, (
        f"compose script failed ({completed.returncode}): "
        f"stdout={completed.stdout!r} stderr={completed.stderr!r}"
    )
    return _prompt_from_github_output(output)


class TestDispatchResolveStep:
    """The dispatch job must resolve an open PR for the ref without failing closed."""

    def test_resolve_step_is_dispatch_only(self) -> None:
        step = _step(_RESOLVE_STEP)
        assert step.get("if") == "github.event_name == 'workflow_dispatch'"
        assert step.get("id") == "dispatch_pr"

    def test_resolve_step_lists_open_prs_for_the_head_ref(self) -> None:
        run = _step(_RESOLVE_STEP).get("run")
        assert isinstance(run, str)
        assert "gh pr list" in run
        assert "--state open" in run
        assert "github.ref_name" in run
        assert "number=" in run

    def test_resolve_step_does_not_fail_the_job_on_empty_match(self) -> None:
        run = _step(_RESOLVE_STEP).get("run")
        assert isinstance(run, str)
        assert '.number // ""' in run or ".number // empty" in run


class TestComposePromptShape:
    """Both events build the prompt from one script, not two event branches."""

    def test_compose_script_does_not_branch_on_event_name(self) -> None:
        script = _compose_script()
        assert "EVENT_NAME" not in script
        assert "pull_request_target" not in script

    def test_compose_keeps_the_dispatch_prompt_override(self) -> None:
        env = _step(_COMPOSE_STEP).get("env")
        assert isinstance(env, dict)
        assert env.get("DISPATCH_PROMPT") == "${{ inputs.prompt }}"
        assert "DISPATCH_PROMPT" in _compose_script()

    def test_compose_reads_the_resolved_dispatch_pr_number(self) -> None:
        env = _step(_COMPOSE_STEP).get("env")
        assert isinstance(env, dict)
        pr_number = env.get("PR_NUMBER")
        assert isinstance(pr_number, str)
        assert "steps.dispatch_pr.outputs.number" in pr_number
        assert "github.event.pull_request.number" in pr_number

    def test_shared_path_names_checkout_pr(self) -> None:
        script = _compose_script()
        assert _CHECKOUT_PR in script
        assert script.count(_CHECKOUT_PR) == 1

    def test_shared_path_wires_ci_context(self) -> None:
        script = _compose_script()
        assert "CI_STATE" in script
        assert "mergecraft_get_check_suite_logs" in script


class TestComposePromptBehaviour:
    """Execute the real compose script — the YAML is the code under test."""

    def test_dispatch_without_prompt_names_the_pr_number(self, tmp_path: Path) -> None:
        prompt = _run_compose(
            tmp_path,
            env={
                "PR_NUMBER": "529",
                "BASE_REF": "pre-0.0.1",
                "CI_STATE": "skipped",
                "CI_FAILED_COUNT": "0",
                "CI_FAILED_NAMES": "",
                "CI_CHECK_SUITE_ID": "",
            },
        )
        assert "Review pull request #529." in prompt
        assert _CHECKOUT_PR in prompt
        assert "origin/pre-0.0.1:path" in prompt
        assert "wait state: skipped" in prompt

    def test_pull_request_target_uses_the_same_shape(self, tmp_path: Path) -> None:
        dispatch = _run_compose(
            tmp_path,
            env={
                "PR_NUMBER": "529",
                "BASE_REF": "pre-0.0.1",
                "CI_STATE": "complete",
                "CI_FAILED_COUNT": "0",
                "CI_FAILED_NAMES": "",
                "CI_CHECK_SUITE_ID": "",
            },
        )
        target = _run_compose(
            tmp_path,
            env={
                "PR_NUMBER": "529",
                "BASE_REF": "pre-0.0.1",
                "CI_STATE": "complete",
                "CI_FAILED_COUNT": "0",
                "CI_FAILED_NAMES": "",
                "CI_CHECK_SUITE_ID": "",
            },
        )
        assert dispatch == target
        assert "CI has finished green" in target

    def test_explicit_prompt_input_passes_through_unchanged(self, tmp_path: Path) -> None:
        override = "Review only the security findings on #12."
        prompt = _run_compose(
            tmp_path,
            env={
                "DISPATCH_PROMPT": override,
                "PR_NUMBER": "529",
                "BASE_REF": "pre-0.0.1",
                "CI_STATE": "complete",
                "CI_FAILED_COUNT": "2",
                "CI_FAILED_NAMES": "Verify (lint)",
                "CI_CHECK_SUITE_ID": "99",
            },
        )
        assert prompt == override
        assert _CHECKOUT_PR not in prompt

    def test_missing_pr_number_falls_back_to_the_bare_string(self, tmp_path: Path) -> None:
        prompt = _run_compose(
            tmp_path,
            env={
                "PR_NUMBER": "",
                "BASE_REF": "",
                "CI_STATE": "skipped",
                "CI_FAILED_COUNT": "0",
                "CI_FAILED_NAMES": "",
                "CI_CHECK_SUITE_ID": "",
            },
        )
        assert prompt == _BARE_FALLBACK
        assert _CHECKOUT_PR not in prompt

    def test_failed_ci_clause_is_attached_when_a_pr_is_resolved(self, tmp_path: Path) -> None:
        prompt = _run_compose(
            tmp_path,
            env={
                "PR_NUMBER": "529",
                "BASE_REF": "main",
                "CI_STATE": "complete",
                "CI_FAILED_COUNT": "1",
                "CI_FAILED_NAMES": "Verify (typecheck)",
                "CI_CHECK_SUITE_ID": "12345",
            },
        )
        assert "Review pull request #529." in prompt
        assert "1 job(s) FAILED (Verify (typecheck))" in prompt
        assert "check_suite_id 12345" in prompt


@pytest.mark.parametrize("name", [_RESOLVE_STEP, _COMPOSE_STEP])
def test_required_review_steps_exist(name: str) -> None:
    _step(name)
