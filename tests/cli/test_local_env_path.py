"""Shared ``resolve_local_env_path`` resolution (D4)."""

from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING

import pytest
import typer

from mergecraft.cli import app as cli_app
from mergecraft.cli.local_env import resolve_local_env_path
from mergecraft.cli.provider_cmd import _env_path

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


def test_resolve_local_env_path_uses_repo_root_from_subdirectory(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    root = _git_repo(tmp_path)
    monkeypatch.delenv("MERGECRAFT_ENV", raising=False)
    monkeypatch.chdir(root / "src" / "deep")

    assert resolve_local_env_path() == (root / ".env").resolve()


def test_env_path_trusts_an_explicit_cwd_without_requiring_a_repo(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """``provider`` commands take ``--cwd`` explicitly; unlike the no-``--cwd``
    writers, they must not require *cwd* to be (inside) a git repository —
    that would break ``provider add`` in a plain config directory.
    """
    monkeypatch.delenv("MERGECRAFT_ENV", raising=False)
    target = tmp_path / "not-a-repo"
    target.mkdir()

    assert _env_path(target) == (target / ".env").resolve()


def test_cli_loader_reads_repo_root_env_from_subdirectory(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    root = _git_repo(tmp_path)
    env_path = root / ".env"
    env_path.write_text("MERGECRAFT_LOGFIRE_TOKEN=tk-from-root-env\n", encoding="utf-8")
    monkeypatch.delenv("MERGECRAFT_ENV", raising=False)
    monkeypatch.delenv("MERGECRAFT_LOGFIRE_TOKEN", raising=False)
    monkeypatch.chdir(root / "src" / "deep")

    saved = os.environ.get("MERGECRAFT_LOGFIRE_TOKEN")
    try:
        cli_app._load_local_env()
        assert os.environ["MERGECRAFT_LOGFIRE_TOKEN"] == "tk-from-root-env"
    finally:
        if saved is None:
            os.environ.pop("MERGECRAFT_LOGFIRE_TOKEN", None)
        else:
            os.environ["MERGECRAFT_LOGFIRE_TOKEN"] = saved


def test_resolve_local_env_path_without_repo_falls_back_for_load(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    env_path = outside / ".env"
    env_path.write_text("MERGECRAFT_LOGFIRE_TOKEN=standalone\n", encoding="utf-8")
    monkeypatch.delenv("MERGECRAFT_ENV", raising=False)
    monkeypatch.chdir(outside)

    assert resolve_local_env_path(require_repo=False) == env_path.resolve()


def test_resolve_local_env_path_bails_without_repo_for_writers(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.delenv("MERGECRAFT_ENV", raising=False)
    monkeypatch.chdir(outside)

    with pytest.raises(typer.Exit):
        resolve_local_env_path()
