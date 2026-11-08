"""Release publishing is a workflow, gated by the ``pypi`` environment.

Craft still prepares the release branch and closes the informational issue; the
Release workflow is the only publisher. PyPI uses Trusted Publishing (OIDC, no
token); the GitHub release, GHCR version tags and the merge-back PR follow in
the same job, after the environment's required reviewers approve it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import TYPE_CHECKING, Any

from tests.ci.workflow_support import REPO_ROOT, job, load_workflow, read_text

if TYPE_CHECKING:
    from pathlib import Path

_SCRIPT = REPO_ROOT / "scripts" / "post-release.sh"
_PYPROJECT = '[project]\nname = "mergecraft-action"\nversion = "0.1.0"\n'


def _publish_job() -> dict[str, Any]:
    return job(load_workflow("release.yml"), "publish")


def _publish_steps() -> list[dict[str, Any]]:
    return [step for step in _publish_job()["steps"] if isinstance(step, dict)]


def _publish_scripts() -> str:
    return "\n".join(str(step.get("run", "")) for step in _publish_steps())


def test_publish_waits_for_the_pypi_environment() -> None:
    publish = _publish_job()
    assert publish["environment"] == "pypi"
    permissions = publish.get("permissions") or {}
    assert permissions.get("id-token") == "write"
    assert permissions.get("contents") == "read"


def test_pypi_uses_trusted_publishing_not_a_long_lived_token() -> None:
    uploads = [
        step
        for step in _publish_steps()
        if str(step.get("uses", "")).startswith("pypa/gh-action-pypi-publish@")
    ]
    assert len(uploads) == 1, uploads
    text = read_text(".github/workflows/release.yml")
    assert "TWINE_PASSWORD" not in text
    assert "PYPI_TOKEN" not in text
    dumped = json.dumps(_publish_steps()).lower()
    assert "twine_password" not in dumped


def test_the_dist_is_verified_before_the_upload() -> None:
    names = [str(step.get("name")) for step in _publish_steps()]
    assert names.index("Download and verify the dist") < names.index("Publish to PyPI")
    assert "verify-dist" in _publish_scripts()


def test_publish_creates_the_release_retags_the_images_and_opens_the_merge_back() -> None:
    scripts = _publish_scripts()
    assert "gh release create" in scripts
    assert "imagetools create" in scripts
    assert "gh pr create --base main" in scripts


def test_publish_fails_closed_when_the_build_did_not_succeed() -> None:
    scripts = _publish_scripts()
    assert "concluded" in scripts
    assert "did not finish" in scripts


def test_the_publish_issue_is_informational_only() -> None:
    prepare = job(load_workflow("release.yml"), "prepare")
    closing = [
        step
        for step in prepare["steps"]
        if isinstance(step, dict) and step.get("name") == "Close the informational publish issue"
    ]
    assert len(closing) == 1
    run = str(closing[0].get("run", ""))
    assert "gh issue close" in run
    assert "pypi environment" in run
    assert "craft publish" not in run
    assert "${{" not in run


def test_prepare_has_the_issues_scope_the_close_needs() -> None:
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


def test_the_pypi_upload_is_resumable() -> None:
    uploads = [
        step
        for step in _publish_steps()
        if str(step.get("uses", "")).startswith("pypa/gh-action-pypi-publish@")
    ]
    assert len(uploads) == 1
    with_ = uploads[0].get("with") or {}
    assert with_.get("skip-existing") is True


def test_no_publish_run_text_expands_a_template() -> None:
    for step in _publish_steps():
        run = str(step.get("run", ""))
        assert "${{" not in run, f"{step.get('name')} interpolates a template into run:"


def test_the_registry_path_follows_the_repository() -> None:
    scripts = _publish_scripts()
    assert "GITHUB_REPOSITORY" in scripts
    assert "ghcr.io/alexhawat/mergecraft" not in scripts


def test_the_publish_job_bumps_the_next_development_version_first() -> None:
    names = [str(step.get("name")) for step in _publish_steps()]
    post = names.index("Bump to the next development version")
    merge = names.index("Open the merge-back PR")
    assert post < merge
    assert 'scripts/post-release.sh "" "$RELEASE_VERSION"' in _publish_scripts()
