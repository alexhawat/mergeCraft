"""Release output points at the real approval, and the version bump is a real bump (#1005).

The publish gate used to tell maintainers they could approve a release by
labelling the publish issue. No workflow reacts to that label or that issue: the
only thing that publishes is ``craft publish`` run with publish credentials.

``scripts/post-release.sh`` is Craft's ``postReleaseCommand``. It rewrites the
versioned files — ``pyproject.toml``, both ``server.json`` version fields and
``uv.lock`` — to the next development version through ``scripts/bump-version.sh``,
so the successor the tree advertises is one it actually installs. That rewrite and
Craft's real call shape are pinned in ``test_post_release_version_bump``; this
module keeps the release surfaces around it honest.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import TYPE_CHECKING

from tests.ci.workflow_support import REPO_ROOT, job, load_workflow, read_text

if TYPE_CHECKING:
    from pathlib import Path

_SCRIPT = REPO_ROOT / "scripts" / "post-release.sh"
_PYPROJECT = '[project]\nname = "merge-craft"\nversion = "0.1.0"\n'


def _publish_gate_text() -> str:
    gate = job(load_workflow("release.yml"), "publish")
    return "\n".join(str(step.get("run", "")) for step in gate["steps"] if isinstance(step, dict))


def test_publish_gate_names_the_publish_command() -> None:
    text = _publish_gate_text()
    assert "craft publish ${{ needs.prepare.outputs.version }}" in text
    assert "publish credentials" in text.lower()


def test_publish_gate_does_not_promise_a_label_approval() -> None:
    lowered = _publish_gate_text().lower()
    assert "label" not in lowered
    assert "publish issue" not in lowered
    assert "approve" not in lowered


def test_prepare_closes_the_informational_publish_issue() -> None:
    """Craft opens a publish-request issue nobody can approve, so prepare closes it (#1005)."""
    prepare = job(load_workflow("release.yml"), "prepare")
    steps = [step for step in prepare["steps"] if isinstance(step, dict)]
    closing = [
        step for step in steps if step.get("name") == "Close the informational publish issue"
    ]
    assert len(closing) == 1, [step.get("name") for step in steps]
    step = closing[0]

    assert step.get("if") == "${{ steps.craft.outputs.issue_url != '' }}"
    env = step.get("env") or {}
    assert env.get("GH_TOKEN") == "${{ github.token }}"
    assert env.get("ISSUE_URL") == "${{ steps.craft.outputs.issue_url }}"
    assert env.get("RELEASED_VERSION") == "${{ steps.craft.outputs.version }}"

    run = str(step.get("run", ""))
    assert "gh issue close" in run
    assert 'gh issue close "${ISSUE_URL}" --reason "not planned"' in run
    assert "craft publish ${RELEASED_VERSION}" in run
    # zizmor's template-injection rule: the URL and version arrive through env:,
    # never interpolated into the shell text.
    assert "${{" not in run


def test_the_publish_issue_url_reaches_the_publish_gate() -> None:
    workflow = load_workflow("release.yml")
    assert workflow["jobs"]["prepare"]["outputs"]["issue_url"] == (
        "${{ steps.craft.outputs.issue_url }}"
    )
    gate = _publish_gate_text().lower()
    assert "informational" in gate
    assert "craft publish" in gate


def test_prepare_has_the_issues_scope_the_close_needs() -> None:
    """The close step runs in the prepare job, which already holds `issues: write`."""
    prepare = job(load_workflow("release.yml"), "prepare")
    assert prepare["permissions"]["issues"] == "write"


def _run_post_release(
    tmp_path: Path, *args: str, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy(_SCRIPT, scripts / "post-release.sh")
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    return subprocess.run(
        ["bash", str(scripts / "post-release.sh"), *args],
        cwd=tmp_path,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        check=False,
    )


def test_post_release_refuses_a_call_with_no_released_version(tmp_path: Path) -> None:
    """Craft always passes one; a manual run without it must stop before writing."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("CRAFT_")}
    completed = _run_post_release(tmp_path, env=env)

    assert completed.returncode != 0
    assert "a released version is required" in completed.stderr
    assert (tmp_path / "pyproject.toml").read_text(encoding="utf-8") == _PYPROJECT


def test_craft_config_still_names_the_post_release_hook() -> None:
    assert "postReleaseCommand: bash scripts/post-release.sh" in read_text(".craft.yml")
