"""Lane A AP1.1 — ``prepare_workspace_for_agent`` chown safety (D3)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import mergecraft.utils.privilege as privilege
from mergecraft.utils.privilege import prepare_workspace_for_agent


def _fake_agent_pwd(monkeypatch: pytest.MonkeyPatch, *, real_chown: bool = False) -> None:
    class _Pw:
        pw_uid = 10001
        pw_gid = 10001
        pw_name = "mergecraft"

    fake_pwd = MagicMock()
    fake_pwd.getpwnam.return_value = _Pw()
    monkeypatch.setitem(__import__("sys").modules, "pwd", fake_pwd)
    monkeypatch.setattr(privilege.os, "getuid", lambda: 0)
    monkeypatch.setenv("MERGECRAFT_AGENT_USER", "mergecraft")
    if real_chown:
        monkeypatch.setenv("MERGECRAFT_ALLOW_ROOT", "1")
    else:
        monkeypatch.setattr(privilege, "_in_action_image", lambda: True)
        monkeypatch.setattr(privilege, "_setpriv_supports_bounding_set", lambda: True)


def test_prepare_workspace_does_not_chown_dot_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "workspace"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    dot_git = repo / ".git"
    assert dot_git.exists()
    before_uid = dot_git.stat().st_uid

    _fake_agent_pwd(monkeypatch)

    prepare_workspace_for_agent(str(repo))

    after_uid = dot_git.stat().st_uid
    assert after_uid == before_uid, ".git must not be chowned to the agent user"


@pytest.mark.skipif(os.getuid() != 0, reason="requires root to chown workspace paths")
def test_prepare_workspace_does_not_chown_symlink_target_outside_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("keep-owner", encoding="utf-8")
    before_uid = secret.stat().st_uid

    repo = tmp_path / "workspace"
    repo.mkdir()
    (repo / "link").symlink_to(secret)

    _fake_agent_pwd(monkeypatch, real_chown=True)

    prepare_workspace_for_agent(str(repo))

    after_uid = secret.stat().st_uid
    assert after_uid == before_uid, "symlink target outside workspace must keep its owner"


def test_prepare_workspace_uses_chown_no_dereference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def _fake_run(cmd: list[str], **_kwargs: object) -> object:
        calls.append(list(cmd))
        return MagicMock(returncode=0)

    _fake_agent_pwd(monkeypatch)
    monkeypatch.setattr(privilege.subprocess, "run", _fake_run)

    prepare_workspace_for_agent(str(tmp_path))

    assert calls, "prepare_workspace_for_agent must invoke chown when root"
    chown_idx = calls[0].index("chown")
    assert calls[0][chown_idx + 1] == "-h", "chown must use -h to avoid following symlinks"
