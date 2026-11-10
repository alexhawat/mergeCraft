"""A consumer review job must not conclude success when no review ran (#1292).

The hardened template (and its copies) gate every enforcing step on
``HAS_AUTH``. On a fork PR — secrets withheld — or a repo with no provider
credential, ``HAS_AUTH`` is false, so before this fix the only step that ran
printed a notice and the job went green: a required ``mergeCraft review`` check
passed with nothing reviewed. The skip-report step now fails by default, with a
``SKIPPED_REVIEW: pass`` opt-out.

These tests run that step's ``run:`` script as shell, with the job's own
``SKIPPED_REVIEW`` default, the way the runner does.

The minimal template and the ``mergecraft init`` scaffold have no ``HAS_AUTH``
gate: their single action step always runs, and the action fails when no chain
entry has a credential (``no runnable model slug in chain``, pinned by
``tests/utils/test_cov_agent_resolve_paths.py``). The last tests here keep that
shape, so a gate added later cannot reintroduce a green no-review job.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from mergecraft.cli.init_cmd import _workflow_template
from tests.ci.workflow_support import REPO_ROOT, job

_HAS_AUTH_FALSE_GATE = "env.HAS_AUTH != 'true'"
_HAS_AUTH_TRUE_GATE = "env.HAS_AUTH == 'true'"

_GATED_TEMPLATES = (
    "scripts/example_workflows/hardened.yml.tpl",
    "examples/workflows/mergecraft-hardened.yml",
    "docs/artifacts/dogfood-mergecraft.yml",
)


def _load(relative: str) -> dict[str, Any]:
    loaded = yaml.safe_load((REPO_ROOT / relative).read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), relative
    return loaded


def _review_job(relative: str) -> dict[str, Any]:
    return job(_load(relative), "review")


def _skip_step(review: dict[str, Any]) -> dict[str, Any]:
    steps = [
        step
        for step in review["steps"]
        if isinstance(step, dict) and _HAS_AUTH_FALSE_GATE in str(step.get("if", ""))
    ]
    assert len(steps) == 1, f"expected one step that runs when HAS_AUTH is false: {steps}"
    return steps[0]


def _run_skip_step(
    relative: str, tmp_path: Path, *, same_repo: bool, skipped_review: str | None = None
) -> subprocess.CompletedProcess[str]:
    review = _review_job(relative)
    script = _skip_step(review)["run"]
    assert "${{" not in script, "the script must read env vars, not expression interpolation"
    default = review["env"]["SKIPPED_REVIEW"]
    env = {
        "PATH": "/usr/bin:/bin",
        "IS_SAME_REPO": "true" if same_repo else "false",
        "SKIPPED_REVIEW": default if skipped_review is None else skipped_review,
    }
    script_path = tmp_path / "skip.sh"
    script_path.write_text(script, encoding="utf-8")
    return subprocess.run(
        ["bash", "-e", str(script_path)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("relative", _GATED_TEMPLATES)
def test_default_is_fail(relative: str) -> None:
    assert _review_job(relative)["env"]["SKIPPED_REVIEW"] == "fail"


@pytest.mark.parametrize("relative", _GATED_TEMPLATES)
@pytest.mark.parametrize("same_repo", [True, False], ids=["no-credential", "fork-pr"])
def test_no_review_fails_the_job_by_default(relative: str, same_repo: bool, tmp_path: Path) -> None:
    result = _run_skip_step(relative, tmp_path, same_repo=same_repo)
    assert result.returncode != 0, result.stdout
    assert "::error title=mergeCraft skipped::" in result.stdout
    expected = "Fork PR" if not same_repo else "No provider credential"
    assert expected in result.stdout


@pytest.mark.parametrize("relative", _GATED_TEMPLATES)
def test_pass_opt_out_passes_with_a_warning(relative: str, tmp_path: Path) -> None:
    result = _run_skip_step(relative, tmp_path, same_repo=False, skipped_review="pass")
    assert result.returncode == 0, result.stdout
    assert "::warning title=mergeCraft skipped::" in result.stdout


@pytest.mark.parametrize("relative", _GATED_TEMPLATES)
def test_unknown_value_fails_closed(relative: str, tmp_path: Path) -> None:
    result = _run_skip_step(relative, tmp_path, same_repo=True, skipped_review="neutral")
    assert result.returncode != 0, result.stdout


@pytest.mark.parametrize("relative", _GATED_TEMPLATES)
def test_review_and_gate_steps_stay_gated_on_has_auth(relative: str) -> None:
    """Premise: the skip step is the only enforcing step left when HAS_AUTH is false."""
    by_name = {step.get("name"): step for step in _review_job(relative)["steps"]}
    for name in ("mergeCraft PR review", "Fail when mergeCraft would not approve"):
        assert _HAS_AUTH_TRUE_GATE in by_name[name]["if"], name


def _single_action_step(doc: dict[str, Any]) -> dict[str, Any]:
    jobs = doc["jobs"]
    assert list(jobs) == ["mergecraft"], list(jobs)
    steps = [
        s for s in jobs["mergecraft"]["steps"] if "alexhawat/mergeCraft@" in str(s.get("uses"))
    ]
    assert len(steps) == 1, steps
    return steps[0]


@pytest.mark.parametrize(
    "source",
    ["init", "examples/workflows/mergecraft.yml"],
)
def test_ungated_templates_always_run_the_action(source: str) -> None:
    """No credential gate and no ``continue-on-error``: the action's own failure is the job's."""
    text = (
        _workflow_template()
        if source == "init"
        else (REPO_ROOT / source).read_text(encoding="utf-8")
    )
    doc = yaml.safe_load(text)
    assert "HAS_AUTH" not in text
    step = _single_action_step(doc)
    assert "if" not in step
    assert not step.get("continue-on-error", False)
    assert "secrets." not in str(doc["jobs"]["mergecraft"].get("if", ""))
