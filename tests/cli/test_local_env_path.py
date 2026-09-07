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
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

_REAL_SUBPROCESS_RUN = subprocess.run


def _git_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "src" / "deep").mkdir(parents=True)
    _REAL_SUBPROCESS_RUN(
        ["git", "init", "--quiet", str(root)], check=True, capture_output=True, text=True
    )
    return root


@pytest.fixture(autouse=True)
def _isolate_from_ambient_repos(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Stop the walk-up at *tmp_path* so ``$TMPDIR``'s ancestry cannot leak in.

    The "outside a repository" cases assert that no root is found. That is only
    true while ``$TMPDIR`` happens to sit outside every checkout — an ambient
    property of the runner, not of the code under test. ``GIT_CEILING_DIRECTORIES``
    pins it.
    """
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.resolve()))
    monkeypatch.delenv("MERGECRAFT_ENV", raising=False)


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
    """The startup load and the writers must agree on one file (#221)."""
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
