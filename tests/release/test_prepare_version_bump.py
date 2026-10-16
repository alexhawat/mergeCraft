"""RED — a prepared release branch keeps ``server.json`` in step with the package version.

A ``craft prepare`` run bumps the package version. ``server.json`` advertises a
PyPI package version for the MCP Registry, and ``make mcp-server-json-check``
compares the two. With no ``preReleaseCommand`` defined, Craft's automatic bump
edits ``pyproject.toml`` alone: the committed manifest goes stale, and the
prepared branch fails its own drift gate before it can reach a single target.

This module pins the fix:

1. ``.craft.yml`` names ``bash scripts/bump-version.sh`` as ``preReleaseCommand``
   and keeps ``postReleaseCommand`` (test 1), and the named script exists.
2. That script, invoked the way Craft invokes a pre-release command —
   positionally, ``bash scripts/bump-version.sh <oldVersion> <newVersion>`` —
   sets ``[project].version``, ``server.json``'s ``version`` and
   ``server.json``'s ``packages[0].version`` to the new version (test 2).
3. Its ``server.json`` output is byte-identical to
   ``scripts/gen_mcp_server_json.render_server_json()`` rendered for the new
   version, so the manifest the branch commits is the manifest the drift gate
   regenerates (test 4).
4. It touches nothing else: no ``uv.lock``, no ``CHANGELOG.md``, no
   ``docs/mcp-tools.md`` (test 5), and it keeps non-ASCII text unescaped the way
   the generator does (test 6).
5. A missing or empty new version exits non-zero and leaves both files
   untouched (test 7), and a ``server.json`` that lost a version field fails
   loudly instead of being silently repaired (test 8).
6. It runs in the environment the Release workflow's ``prepare`` job has: no
   ``VIRTUAL_ENV`` and no project environment on ``PATH`` (test 3), which the
   script's own bootstrap-free shape backs (test 9).

RED by design. ``scripts/bump-version.sh`` does not exist and ``.craft.yml``
names no ``preReleaseCommand``, so every test here fails until the
implementation wave lands. These pins are deliberately marker-free — no
``xfail``: ``xfail_strict = true`` is configured in ``pyproject.toml``, so a
marker that later passes would fail the suite. The implementation wave makes
these real passes.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.ci.workflow_support import REPO_ROOT
from tests.docs.support import load_script_module

_CRAFT_CONFIG = ".craft.yml"
_BUMP_SCRIPT = "scripts/bump-version.sh"
_GENERATOR_SCRIPT = "scripts/gen_mcp_server_json.py"
_PYPROJECT = "pyproject.toml"
_SERVER_JSON = "server.json"

# The locked prepare command and the post-release hook it sits beside.
_PRE_RELEASE_COMMAND = "bash scripts/bump-version.sh"
_POST_RELEASE_COMMAND = "bash scripts/post-release.sh"

# Versions from the recorded dry run: the branch's version and a candidate.
_OLD_VERSION = "0.1.0a1"
_NEW_VERSION = "9.9.9a9"
# Craft passes ``0.0.0`` when it has no old version to report.
_EMPTY_OLD_VERSION = "0.0.0"

# The inputs a prepare run rewrites, plus the files it must leave alone: the
# lockfile, the changelog Craft writes itself, and the generator's sibling page.
_PREPARE_INPUTS = (_PYPROJECT, _SERVER_JSON)
_WATCHED_SIBLINGS = ("uv.lock", "CHANGELOG.md", "docs/mcp-tools.md")


def _craft_config() -> dict[str, Any]:
    """Parse ``.craft.yml`` as a mapping."""
    data = yaml.safe_load((REPO_ROOT / _CRAFT_CONFIG).read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{_CRAFT_CONFIG} must parse as a mapping"
    return data


def _prepare_tree(tmp_path: Path) -> Path:
    """Copy the prepare inputs into a throwaway repo root and return it.

    The script resolves the repository root from its own location, so the copy
    puts ``scripts/`` beside the files it edits, exactly as a real checkout does.
    """
    script = REPO_ROOT / _BUMP_SCRIPT
    assert script.is_file(), (
        f"{_BUMP_SCRIPT} does not exist: nothing rewrites {_SERVER_JSON} on a "
        f"prepared release branch yet"
    )
    root = tmp_path / "repo"
    for rel in (*_PREPARE_INPUTS, *_WATCHED_SIBLINGS, _BUMP_SCRIPT):
        source = REPO_ROOT / rel
        assert source.is_file(), f"missing repo file {rel}"
        destination = root / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return root


def _run_bump(
    root: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Invoke the prepare command as Craft invokes it: positionally, from the root."""
    return subprocess.run(
        ["bash", _BUMP_SCRIPT, *args],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _env_without_project_environment() -> dict[str, str]:
    """Return the prepare job's environment: no virtualenv, nothing to bootstrap."""
    env = {
        key: value for key, value in os.environ.items() if key not in {"VIRTUAL_ENV", "PYTHONPATH"}
    }
    env["PATH"] = os.pathsep.join(
        entry for entry in env.get("PATH", "").split(os.pathsep) if entry and ".venv" not in entry
    )
    return env


def _env_without_craft_versions() -> dict[str, str]:
    """Return ``os.environ`` with the version variables Craft exports removed."""
    env = dict(os.environ)
    env.pop("CRAFT_NEW_VERSION", None)
    env.pop("CRAFT_OLD_VERSION", None)
    return env


def _pyproject_version(root: Path) -> str:
    """Return ``[project].version`` from a copied ``pyproject.toml``."""
    data = tomllib.loads((root / _PYPROJECT).read_text(encoding="utf-8"))
    project = data.get("project")
    assert isinstance(project, dict), f"{_PYPROJECT} must carry a [project] table"
    version = project.get("version")
    assert isinstance(version, str), f"{_PYPROJECT} must carry [project].version"
    return version


def _committed_version() -> str:
    """Return the repo's own committed ``[project].version``.

    The drift gate compares the committed manifest against the committed
    version, never against whatever distribution happens to be *installed*.
    ``package_version()`` is ``lru_cache``d and reads the installed
    distribution, so a premise render must pin this value in instead of
    calling it: another module can leave that cache holding a different
    version for the rest of a full-suite run.
    """
    return _pyproject_version(REPO_ROOT)


def _server_json(root: Path) -> dict[str, Any]:
    """Return the copied ``server.json`` as a mapping."""
    data = json.loads((root / _SERVER_JSON).read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{_SERVER_JSON} must parse as a mapping"
    return data


def _write_server_json(root: Path, data: dict[str, Any]) -> None:
    """Write ``data`` back with the generator's own serialization."""
    (root / _SERVER_JSON).write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _uses_script_relative_root(text: str) -> bool:
    """Return whether a script derives its repository root from its own location."""
    return "dirname" in text and ("$0" in text or "BASH_SOURCE" in text)


def _snapshot(root: Path) -> dict[str, bytes]:
    """Return every file under *root*, keyed by repo-relative path."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _assert_bumped(root: Path, new_version: str) -> None:
    """Assert all three version fields moved to *new_version*."""
    assert _pyproject_version(root) == new_version
    data = _server_json(root)
    assert data.get("version") == new_version, data.get("version")
    packages = data.get("packages")
    assert isinstance(packages, list), data.get("packages")
    assert packages, data.get("packages")
    assert packages[0].get("version") == new_version, packages[0]


def _drop_top_level_version(data: dict[str, Any]) -> None:
    """Remove ``server.json``'s top-level ``version``."""
    del data["version"]


def _drop_package_version(data: dict[str, Any]) -> None:
    """Remove ``packages[0].version`` from ``server.json``."""
    del data["packages"][0]["version"]


def test_craft_yml_names_the_prepare_and_post_release_commands() -> None:
    """Happy: Craft runs our bump instead of its own, and publish still cleans up.

    Without ``preReleaseCommand``, Craft bumps ``pyproject.toml`` by direct edit
    and the prepared branch drifts. ``postReleaseCommand`` must survive the
    change.
    """
    config = _craft_config()
    assert config.get("preReleaseCommand") == _PRE_RELEASE_COMMAND
    assert config.get("postReleaseCommand") == _POST_RELEASE_COMMAND


def test_prepare_bump_sets_pyproject_and_both_server_json_versions(tmp_path: Path) -> None:
    """Happy: one prepare run moves all three advertised version fields."""
    root = _prepare_tree(tmp_path)
    completed = _run_bump(root, _OLD_VERSION, _NEW_VERSION)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    _assert_bumped(root, _NEW_VERSION)


def test_prepare_bump_runs_without_the_project_environment(tmp_path: Path) -> None:
    """Integration: the prepare job has no bootstrap, so the script must not need one.

    The Release workflow's ``prepare`` job checks the repository out and runs
    this command with no dependency install step: no virtualenv, nothing from
    the project on ``PATH``.
    """
    root = _prepare_tree(tmp_path)
    env = _env_without_project_environment()
    assert "VIRTUAL_ENV" not in env
    assert not any(".venv" in entry for entry in env["PATH"].split(os.pathsep))
    completed = _run_bump(root, _OLD_VERSION, _NEW_VERSION, env=env)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    _assert_bumped(root, _NEW_VERSION)


@pytest.mark.parametrize(
    "old_version",
    [_OLD_VERSION, _EMPTY_OLD_VERSION],
    ids=["old-version-from-branch", "empty-old-version-is-0.0.0"],
)
def test_prepare_bump_reads_positional_old_and_new_arguments(
    tmp_path: Path, old_version: str
) -> None:
    """Contract: Craft invokes the command positionally, with no version env required.

    ``bash scripts/bump-version.sh <oldVersion> <newVersion>``; an empty old
    version arrives as ``0.0.0``. Nothing here sets ``CRAFT_NEW_VERSION``, so an
    implementation that only reads the environment cannot pass.
    """
    root = _prepare_tree(tmp_path)
    completed = _run_bump(root, old_version, _NEW_VERSION, env=_env_without_craft_versions())
    assert completed.returncode == 0, (
        f"positional invocation `{_BUMP_SCRIPT} {old_version} {_NEW_VERSION}` "
        f"failed with CRAFT_* unset: {completed.stdout}{completed.stderr}"
    )
    _assert_bumped(root, _NEW_VERSION)


def test_prepare_bump_tolerates_craft_version_env_exports(tmp_path: Path) -> None:
    """Edge: Craft also exports the versions; the positional run must keep working."""
    root = _prepare_tree(tmp_path)
    env = dict(os.environ)
    env["CRAFT_NEW_VERSION"] = _NEW_VERSION
    env["CRAFT_OLD_VERSION"] = _OLD_VERSION
    completed = _run_bump(root, _OLD_VERSION, _NEW_VERSION, env=env)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    _assert_bumped(root, _NEW_VERSION)


def test_server_json_after_bump_is_byte_identical_to_the_generator_render(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Contract: the bumped manifest is exactly what the drift gate regenerates.

    ``make mcp-server-json-check`` renders ``server.json`` from
    ``scripts/gen_mcp_server_json.render_server_json()`` and compares bytes. If
    the bump writes anything else — different indentation, escaped non-ASCII, a
    missing trailing newline, a dropped key — the prepared branch fails its own
    gate, which is the failure this contract exists to prevent.
    """
    root = _prepare_tree(tmp_path)
    generator = load_script_module(_GENERATOR_SCRIPT)
    # Pin the version the generator renders for the premise. The committed
    # manifest is the generator's render *for the committed version*, and the
    # ambient ``package_version()`` (installed distribution, ``lru_cache``d)
    # is process state another module can poison for the rest of the run.
    monkeypatch.setattr(generator, "package_version", _committed_version)
    assert generator.render_server_json() == (REPO_ROOT / _SERVER_JSON).read_text(
        encoding="utf-8"
    ), "premise: the committed manifest is the generator's render for the committed version"

    completed = _run_bump(root, _OLD_VERSION, _NEW_VERSION)
    assert completed.returncode == 0, completed.stdout + completed.stderr

    monkeypatch.setattr(generator, "package_version", lambda: _NEW_VERSION)
    expected = generator.render_server_json()
    actual = (root / _SERVER_JSON).read_text(encoding="utf-8")
    assert actual == expected


def test_prepare_bump_touches_only_pyproject_and_server_json(tmp_path: Path) -> None:
    """Edge: nothing else in the checkout changes — no lockfile, changelog or docs page."""
    root = _prepare_tree(tmp_path)
    before = _snapshot(root)
    assert "uv.lock" in before, before.keys()
    assert "CHANGELOG.md" in before, before.keys()
    assert "docs/mcp-tools.md" in before, before.keys()

    completed = _run_bump(root, _OLD_VERSION, _NEW_VERSION)
    assert completed.returncode == 0, completed.stdout + completed.stderr

    after = _snapshot(root)
    changed = sorted(
        path for path in set(before) | set(after) if before.get(path) != after.get(path)
    )
    assert changed == [_PYPROJECT, _SERVER_JSON]


def test_prepare_bump_preserves_non_ascii_without_escaping(tmp_path: Path) -> None:
    """Edge: the manifest is written the way the generator writes it, non-ASCII intact."""
    root = _prepare_tree(tmp_path)
    data = _server_json(root)
    data["description"] = "Public mergeCraft MCP — six tools · café"
    _write_server_json(root, data)

    completed = _run_bump(root, _OLD_VERSION, _NEW_VERSION)
    assert completed.returncode == 0, completed.stdout + completed.stderr

    text = (root / _SERVER_JSON).read_text(encoding="utf-8")
    assert "—" in text, text
    assert "café" in text, text
    assert "\\u" not in text, "ensure_ascii must stay off, as in the generator"
    assert _server_json(root)["description"] == "Public mergeCraft MCP — six tools · café"


@pytest.mark.parametrize(
    "args",
    [(), (_OLD_VERSION, "")],
    ids=["no-arguments", "empty-new-version"],
)
def test_prepare_bump_refuses_a_missing_or_empty_new_version(
    tmp_path: Path, args: tuple[str, ...]
) -> None:
    """Error: a versionless invocation fails loudly and changes nothing.

    A prepare run that half-bumps the branch is worse than one that stops: the
    release branch would carry a version nobody chose.
    """
    root = _prepare_tree(tmp_path)
    before = {rel: (root / rel).read_bytes() for rel in _PREPARE_INPUTS}

    completed = _run_bump(root, *args, env=_env_without_craft_versions())
    assert completed.returncode != 0, (
        f"invocation with args={args!r} must exit non-zero: {completed.stdout}"
    )
    for rel, original in before.items():
        assert (root / rel).read_bytes() == original, f"{rel} changed on args={args!r}"


@pytest.mark.parametrize(
    "mutate",
    [_drop_top_level_version, _drop_package_version],
    ids=["top-level-version", "package-version"],
)
def test_prepare_bump_fails_loudly_when_server_json_drops_a_version_field(
    tmp_path: Path, mutate: Callable[[dict[str, Any]], None]
) -> None:
    """Error: a manifest missing a version field is reported, never silently repaired."""
    root = _prepare_tree(tmp_path)
    data = _server_json(root)
    mutate(data)
    _write_server_json(root, data)
    before = (root / _SERVER_JSON).read_bytes()

    completed = _run_bump(root, _OLD_VERSION, _NEW_VERSION)
    assert completed.returncode != 0, (
        "a manifest without both version fields must fail the prepare step: "
        f"{completed.stdout}{completed.stderr}"
    )
    assert (root / _SERVER_JSON).read_bytes() == before


def test_bump_script_stays_bootstrap_free() -> None:
    """Integration: the script is shell plus stdlib, with a script-relative root.

    ``scripts/post-release.sh`` is the shape to match: an SPDX header, strict
    shell, and a root derived from the script's own location so the command
    works from any checkout.
    """
    script = REPO_ROOT / _BUMP_SCRIPT
    assert script.is_file(), f"{_BUMP_SCRIPT} missing"
    text = script.read_text(encoding="utf-8")
    assert "SPDX-License-Identifier: MIT" in text
    assert "set -euo pipefail" in text
    assert _uses_script_relative_root(text), (
        "the root must come from the script's own location, as in post-release.sh"
    )
    assert "python3" in text, "the manifest rewrite uses the interpreter it can rely on"
    assert "uv run" not in text, "the prepare job has no bootstrap: do not shell out to uv"
    assert "import mergecraft" not in text, "no project import: the prepare job installs nothing"
    assert "from mergecraft" not in text, "no project import: the prepare job installs nothing"
