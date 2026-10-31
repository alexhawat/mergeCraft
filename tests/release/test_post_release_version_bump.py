"""The post-release bump keeps the tree installable and the gates green.

``craft publish`` runs ``postReleaseCommand`` (``bash scripts/post-release.sh``)
after the targets publish. The older shape bumped ``pyproject.toml`` alone —
the same defect the prepare step had (see ``test_prepare_version_bump``): the
next commit left ``uv lock --check`` and ``make mcp-server-json-check`` red.

This module pins:

1. ``.craft.yml`` keeps ``postReleaseCommand`` pointed at the script (test 1).
2. The dev version is a canonical PEP 440 successor: ``0.1.0a3`` ->
   ``0.1.0a4.dev0`` (likewise ``b`` and ``rc``), and ``0.1.0`` ->
   ``0.1.1.dev0`` (test 2). The previous ``-dev`` suffix is not canonical PEP
   440 and sorts *above* the final release it follows.
3. ``pyproject.toml``, both ``server.json`` version fields and ``uv.lock``'s
   ``mergecraft-action`` block all carry the dev version (test 3), so the required
   ``lockcheck`` and ``mcp-server-json-check`` contexts stay green.
4. It reuses ``scripts/bump-version.sh`` rather than duplicating the rewrite
   (test 4), so one place knows which files carry the version.
5. A missing or empty released version (test 5), or a version that is not
   canonical (test 6), exits non-zero and changes nothing.
6. Craft's real call shape is pinned: an empty first argument, the version
   second, and only ``CRAFT_RELEASED_VERSION`` exported.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.ci.workflow_support import REPO_ROOT

_CRAFT_CONFIG = ".craft.yml"
_BUMP_SCRIPT = "scripts/bump-version.sh"
_POST_RELEASE_SCRIPT = "scripts/post-release.sh"
_POST_RELEASE_COMMAND = "bash scripts/post-release.sh"
_PYPROJECT = "pyproject.toml"
_SERVER_JSON = "server.json"
_UV_LOCK = "uv.lock"
_VERSIONED_FILES = (_PYPROJECT, _SERVER_JSON, _UV_LOCK)


def _craft_config() -> dict[str, Any]:
    data = yaml.safe_load((REPO_ROOT / _CRAFT_CONFIG).read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{_CRAFT_CONFIG} must parse as a mapping"
    return data


def _prepare_tree(tmp_path: Path) -> Path:
    """Copy the versioned files and both scripts into a throwaway repo root."""
    root = tmp_path / "repo"
    for rel in (*_VERSIONED_FILES, _BUMP_SCRIPT, _POST_RELEASE_SCRIPT):
        source = REPO_ROOT / rel
        assert source.is_file(), f"missing repo file {rel}"
        destination = root / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return root


def _run_post_release(
    root: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", _POST_RELEASE_SCRIPT, *args],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _env_with(released: str) -> dict[str, str]:
    env = dict(os.environ)
    env["CRAFT_NEW_VERSION"] = released
    return env


def _env_as_craft(released: str) -> dict[str, str]:
    """The environment Craft really passes: its allowlist plus CRAFT_RELEASED_VERSION.

    ``buildReleaseCommandEnv`` keeps PATH/HOME/USER/GIT_COMMITTER_NAME/
    GIT_AUTHOR_NAME/EMAIL, every ``GITHUB_*``/``RUNNER_*`` variable and the
    extras Craft sets — ``CRAFT_RELEASED_VERSION`` — and drops the rest.
    ``CRAFT_NEW_VERSION`` is not among them (pinned Craft ``3f2abdc5``,
    ``src/commands/publish.ts``).
    """
    allowlist = ("PATH", "HOME", "USER", "EMAIL")
    env = {key: os.environ[key] for key in allowlist if key in os.environ}
    env.update({k: v for k, v in os.environ.items() if k.startswith(("GITHUB_", "RUNNER_"))})
    env["CRAFT_RELEASED_VERSION"] = released
    return env


def _env_without_craft_versions() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("CRAFT_NEW_VERSION", None)
    env.pop("CRAFT_OLD_VERSION", None)
    return env


def _pyproject_version(root: Path) -> str:
    data = tomllib.loads((root / _PYPROJECT).read_text(encoding="utf-8"))
    project = data.get("project")
    assert isinstance(project, dict), f"{_PYPROJECT} must carry a [project] table"
    version = project.get("version")
    assert isinstance(version, str), f"{_PYPROJECT} must carry [project].version"
    return version


def _server_json(root: Path) -> dict[str, Any]:
    data = json.loads((root / _SERVER_JSON).read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{_SERVER_JSON} must parse as a mapping"
    return data


def _uv_lock_version(root: Path) -> str:
    text = (root / _UV_LOCK).read_text(encoding="utf-8")
    match = re.search(r'\[\[package\]\]\nname = "mergecraft-action"\nversion = "([^"]*)"', text)
    assert match is not None, f"{_UV_LOCK} must record the mergecraft-action package block"
    return match.group(1)


def _assert_bumped(root: Path, version: str) -> None:
    """Assert every place the version lives carries *version*."""
    assert _pyproject_version(root) == version
    data = _server_json(root)
    assert data.get("version") == version, data.get("version")
    packages = data.get("packages")
    assert isinstance(packages, list), data.get("packages")
    assert packages, data.get("packages")
    assert packages[0].get("version") == version, packages[0]
    assert _uv_lock_version(root) == version


def test_craft_yml_keeps_the_post_release_command() -> None:
    """Happy: publishing still runs our script as the cleanup hook."""
    assert _craft_config().get("postReleaseCommand") == _POST_RELEASE_COMMAND


@pytest.mark.parametrize(
    ("released", "dev"),
    [
        ("0.1.0a3", "0.1.0a4.dev0"),
        ("0.1.0b2", "0.1.0b3.dev0"),
        ("0.1.0rc1", "0.1.0rc2.dev0"),
        ("0.1.0", "0.1.1.dev0"),
        ("1.2.3", "1.2.4.dev0"),
    ],
)
def test_post_release_uses_canonical_pep440_dev_versions(
    tmp_path: Path, released: str, dev: str
) -> None:
    """Contract: the successor is a canonical PEP 440 development release."""
    root = _prepare_tree(tmp_path)
    completed = _run_post_release(root, env=_env_with(released))
    assert completed.returncode == 0, completed.stdout + completed.stderr
    _assert_bumped(root, dev)


def test_post_release_updates_all_three_versioned_files(tmp_path: Path) -> None:
    """Happy: one post-release run moves pyproject, both manifest fields and the lock."""
    root = _prepare_tree(tmp_path)
    completed = _run_post_release(root, env=_env_with("0.1.0a3"))
    assert completed.returncode == 0, completed.stdout + completed.stderr
    _assert_bumped(root, "0.1.0a4.dev0")


def test_post_release_accepts_a_positional_version(tmp_path: Path) -> None:
    """Edge: a positional released version works when CRAFT_NEW_VERSION is unset."""
    root = _prepare_tree(tmp_path)
    completed = _run_post_release(root, "0.1.0a3", env=_env_without_craft_versions())
    assert completed.returncode == 0, completed.stdout + completed.stderr
    _assert_bumped(root, "0.1.0a4.dev0")


def test_post_release_reads_crafts_second_argument(tmp_path: Path) -> None:
    """Contract: Craft's exact call — `post-release.sh '' <version>` — bumps.

    Craft always passes an empty first argument and the version second, with only
    ``CRAFT_RELEASED_VERSION`` exported, so a script that reads ``$1`` (or
    ``CRAFT_NEW_VERSION``) fails the publish after the targets are live.
    """
    root = _prepare_tree(tmp_path)
    completed = _run_post_release(root, "", "0.1.0a3", env=_env_as_craft("0.1.0a3"))
    assert completed.returncode == 0, completed.stdout + completed.stderr
    _assert_bumped(root, "0.1.0a4.dev0")


def test_post_release_reads_craft_released_version_env(tmp_path: Path) -> None:
    """Contract: CRAFT_RELEASED_VERSION alone is enough when $2 is absent."""
    root = _prepare_tree(tmp_path)
    env = _env_as_craft("0.1.0a3")
    assert "CRAFT_NEW_VERSION" not in env
    completed = _run_post_release(root, "", env=env)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    _assert_bumped(root, "0.1.0a4.dev0")


def test_post_release_reuses_the_prepare_script() -> None:
    """Integration: one place performs the rewrite, so the files cannot drift apart."""
    text = (REPO_ROOT / _POST_RELEASE_SCRIPT).read_text(encoding="utf-8")
    assert "bump-version.sh" in text, "post-release.sh must delegate to bump-version.sh"
    assert "perl -i" not in text, "the manifest/lock rewrite belongs to bump-version.sh"
    assert "SPDX-License-Identifier: MIT" in text
    assert "set -euo pipefail" in text


@pytest.mark.parametrize("args", [(), ("",)], ids=["missing-env", "empty-argument"])
def test_post_release_refuses_a_missing_released_version(
    tmp_path: Path, args: tuple[str, ...]
) -> None:
    """Error: without a released version the hook fails loudly and changes nothing."""
    root = _prepare_tree(tmp_path)
    before = {rel: (root / rel).read_bytes() for rel in _VERSIONED_FILES}

    completed = _run_post_release(root, *args, env=_env_without_craft_versions())
    assert completed.returncode != 0, completed.stdout
    for rel, original in before.items():
        assert (root / rel).read_bytes() == original, f"{rel} changed on args={args!r}"


@pytest.mark.parametrize(
    "released",
    ["not-a-version", "0.1", "0.1.0-rc1", "0.1.0a", "v0.1.0"],
    ids=["words", "two-components", "hyphen-suffix", "missing-number", "v-prefix"],
)
def test_post_release_refuses_a_non_canonical_version(tmp_path: Path, released: str) -> None:
    """Error: a version that is not canonical PEP 440 stops the hook, nothing written."""
    root = _prepare_tree(tmp_path)
    before = {rel: (root / rel).read_bytes() for rel in _VERSIONED_FILES}

    completed = _run_post_release(root, env=_env_with(released))
    assert completed.returncode != 0, (
        f"a non-canonical released version ({released!r}) must fail the hook: {completed.stdout}"
    )
    for rel, original in before.items():
        assert (root / rel).read_bytes() == original, f"{rel} changed on {released!r}"
