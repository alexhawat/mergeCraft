"""Shared ``.env`` path resolution — the two anchors and their pairing (D4).

``--cwd`` is documented as "Repository root." and the config layer takes it
literally, so :func:`local_env_path_for_cwd` must too or a command reads its
registry from one directory and writes credentials to another. Commands with
no ``--cwd`` have only the process working directory, so
:func:`local_env_path_for_process_cwd` walks up to the git root — that is the
subdirectory bug this module exists to fix.
"""

from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING

import pytest
import typer

from mergecraft.cli import app as cli_app
from mergecraft.cli.local_env import (
    local_env_path_for_cwd,
    local_env_path_for_process_cwd,
)
from mergecraft.cli.provider_cmd import _config_path, _env_path

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

_REAL_SUBPROCESS_RUN = subprocess.run

# Keys ``_load_local_env`` can write straight into ``os.environ`` from this
# module: the credential the startup load exports and the ``D``/``E``/``F``
# corpus. ``os.environ.setdefault`` bypasses ``monkeypatch``, so a key that was
# *absent* at ``monkeypatch.delenv`` time is never recorded for teardown and the
# value outlives the test.
_LOADER_WRITTEN_KEYS = ["MERGECRAFT_LOGFIRE_TOKEN", "D", "E", "F"]


def _git_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "src" / "deep").mkdir(parents=True)
    _REAL_SUBPROCESS_RUN(
        ["git", "init", "--quiet", str(root)], check=True, capture_output=True, text=True
    )
    return root


@pytest.fixture(autouse=True)
def _isolate_from_ambient_repos(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Stop ambient runner state leaking into the local-path cases.

    The "outside a repository" cases assert that no root is found. That is only
    true while ``$TMPDIR`` happens to sit outside every checkout — an ambient
    property of the runner, not of the code under test. ``GIT_CEILING_DIRECTORIES``
    pins it.

    This module covers *local* (non-Actions) resolution, so the explicit env
    override is cleared and the Actions flag is cleared too — E5 / TB-D14 makes
    the startup load skip a workspace ``.env`` inside Actions, and that path has
    its own module (``tests/cli/test_local_env_loader.py``).
    """
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.resolve()))
    monkeypatch.delenv("MERGECRAFT_ENV", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)


@pytest.fixture(autouse=True)
def _restore_keys_written_by_the_loader() -> Iterator[None]:
    """Undo the straight-``os.environ`` writes the startup load makes.

    ``_load_local_env`` populates ``os.environ`` directly, so a key that was
    absent when the per-test ``monkeypatch.delenv`` ran is not recorded for
    teardown. Snapshot here and restore: absent-before keys are deleted,
    present-before keys are put back.
    """
    before = {key: os.environ[key] for key in _LOADER_WRITTEN_KEYS if key in os.environ}
    try:
        yield
    finally:
        for key in _LOADER_WRITTEN_KEYS:
            if key in before:
                os.environ[key] = before[key]
            else:
                os.environ.pop(key, None)


# ── the ``--cwd`` anchor: literal, paired with the config path ───────────────


def test_cwd_anchor_is_literal_and_pairs_with_the_config_path(tmp_path: Path) -> None:
    """``--cwd`` names the directory; the ``.env`` and the registry follow it.

    Regression: anchoring the ``.env`` on the git root while ``_config_path``
    stayed literal made ``provider auth --cwd src/deep`` read the registry from
    the subdirectory and write the credential to the checkout root — #520 from
    the other side.
    """
    root = _git_repo(tmp_path)
    deep = root / "src" / "deep"

    assert local_env_path_for_cwd(deep) == deep / ".env"
    assert _env_path(deep) == deep / ".env"
    # The pairing invariant: both anchors name the same directory.
    assert _env_path(deep).parent == _config_path(deep).parent.parent


def test_cwd_anchor_does_not_bail_outside_a_repository(tmp_path: Path) -> None:
    """A ``--cwd`` that is not a checkout is still a directory the operator named.

    Regression: routing ``--cwd`` through the repo-root walk-up turned every
    ``provider``/``model``/``agents`` write against a plain directory into a
    configuration bail (exit 30).
    """
    plain = tmp_path / "not-a-repo"
    plain.mkdir()

    assert local_env_path_for_cwd(plain) == plain / ".env"
    assert _env_path(plain) == plain / ".env"


def test_cwd_anchor_yields_to_the_explicit_override(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    pinned = tmp_path / "custom.env"
    monkeypatch.setenv("MERGECRAFT_ENV", str(pinned))

    assert local_env_path_for_cwd(tmp_path / "anywhere") == pinned.resolve()


# ── the process-cwd anchor: walks up to the git root ─────────────────────────


def test_process_cwd_anchor_uses_the_repo_root_from_a_subdirectory(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    root = _git_repo(tmp_path)
    monkeypatch.chdir(root / "src" / "deep")

    assert local_env_path_for_process_cwd() == (root / ".env").resolve()
    # ``cwd=None`` callers share that anchor.
    assert _env_path() == (root / ".env").resolve()


def test_cli_loader_reads_repo_root_env_from_subdirectory(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """The startup load and the writers must agree on one file (#221).

    This pins the *non-Actions* load path: E5 / TB-D14 makes
    ``_load_local_env`` skip a workspace ``.env`` inside GitHub Actions. The
    autouse fixture clears ``GITHUB_ACTIONS`` so the assertion below states the
    local behaviour it means; the Actions path has its own module
    (``tests/cli/test_local_env_loader.py``).
    """
    root = _git_repo(tmp_path)
    (root / ".env").write_text("MERGECRAFT_LOGFIRE_TOKEN=tk-from-root-env\n", encoding="utf-8")
    monkeypatch.delenv("MERGECRAFT_LOGFIRE_TOKEN", raising=False)
    monkeypatch.chdir(root / "src" / "deep")

    cli_app._load_local_env()

    assert os.environ["MERGECRAFT_LOGFIRE_TOKEN"] == "tk-from-root-env"


def test_process_cwd_anchor_falls_back_for_the_startup_load(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)

    resolved = local_env_path_for_process_cwd(on_missing_repo="use-process-cwd")

    assert resolved == (outside / ".env").resolve()


def test_process_cwd_anchor_bails_for_writers_outside_a_repository(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)

    with pytest.raises(typer.Exit):
        local_env_path_for_process_cwd()


# ── the path anchor and the parser agree on one ``.env`` ────────────────────


def test_process_cwd_anchor_loads_a_corpus_from_the_repo_root(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """The file the subdirectory load finds is parsed like ``load_dotenv``."""
    root = _git_repo(tmp_path)
    (root / ".env").write_text("D=\"x y\"\nE='q'\nF=${D}\n", encoding="utf-8")
    for key in ("D", "E", "F"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(root / "src" / "deep")

    cli_app._load_local_env()

    assert os.environ["D"] == "x y"
    assert os.environ["E"] == "q"
    assert os.environ["F"] == "x y"


def test_explicit_env_path_loads_the_corpus(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """``MERGECRAFT_ENV`` names one file; its quoting means one thing."""
    explicit = tmp_path / "custom.env"
    explicit.write_text("D=\"x y\"\nE='q'\n", encoding="utf-8")
    for key in ("D", "E"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MERGECRAFT_ENV", str(explicit))

    cli_app._load_local_env()

    assert os.environ["D"] == "x y"
    assert os.environ["E"] == "q"
