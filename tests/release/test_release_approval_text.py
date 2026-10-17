"""Release output points at the real approval, and the dev bump is not a phantom (#1005).

Two release surfaces claimed more than they did:

* the publish gate told maintainers they could approve a release by labelling
  the publish issue, but no workflow reacts to that label or that issue — the
  only thing that publishes is ``craft publish`` run with publish credentials;
* ``post-release.sh`` rewrote ``pyproject.toml`` to a ``-dev`` version and never
  committed it. Committed, it would advertise a version that does not exist and
  fail the registry-manifest drift check on the next release.

The convention that replaces the edit: the version on ``main`` stays the last
released version until the next prepare.
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


def test_release_process_doc_states_the_version_convention() -> None:
    text = read_text("docs/release-process.md")
    assert "stays the last released version" in text


def _run_post_release(tmp_path: Path, *, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy(_SCRIPT, scripts / "post-release.sh")
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    return subprocess.run(
        ["bash", str(scripts / "post-release.sh")],
        cwd=tmp_path,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        check=False,
    )


def test_post_release_no_longer_edits_pyproject(tmp_path: Path) -> None:
    completed = _run_post_release(tmp_path, env={"CRAFT_NEW_VERSION": "0.1.0"})
    assert completed.returncode == 0, completed.stderr
    assert (tmp_path / "pyproject.toml").read_text(encoding="utf-8") == _PYPROJECT
    assert "-dev" not in (tmp_path / "pyproject.toml").read_text(encoding="utf-8")


def test_post_release_states_the_convention(tmp_path: Path) -> None:
    completed = _run_post_release(tmp_path, env={"CRAFT_NEW_VERSION": "0.1.0"})
    assert "stays the last released version" in completed.stdout


def test_post_release_still_requires_the_released_version(tmp_path: Path) -> None:
    env = {key: value for key, value in os.environ.items() if key != "CRAFT_NEW_VERSION"}
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy(_SCRIPT, scripts / "post-release.sh")
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    completed = subprocess.run(
        ["bash", str(scripts / "post-release.sh")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "CRAFT_NEW_VERSION" in completed.stderr


def test_craft_config_still_names_the_post_release_hook() -> None:
    assert "postReleaseCommand: bash scripts/post-release.sh" in read_text(".craft.yml")


def test_the_hook_script_no_longer_contains_the_dev_bump() -> None:
    text = read_text("scripts/post-release.sh")
    assert "perl -i" not in text
    assert "dev_version" not in text
