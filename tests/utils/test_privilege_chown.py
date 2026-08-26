"""Lane A AP1.1 — ``prepare_workspace_for_agent`` must not chown ``.git`` (D3)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import mergecraft.utils.privilege as privilege
from mergecraft.utils.privilege import prepare_workspace_for_agent


@pytest.mark.xfail(
    reason="green after AP2: prune .git from recursive chown",
    strict=False,
)
def test_prepare_workspace_does_not_chown_dot_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "workspace"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    dot_git = repo / ".git"
    assert dot_git.exists()
    before_uid = dot_git.stat().st_uid

    class _Pw:
        pw_uid = 10001
        pw_gid = 10001
        pw_name = "mergecraft"

    fake_pwd = MagicMock()
    fake_pwd.getpwnam.return_value = _Pw()
    monkeypatch.setitem(__import__("sys").modules, "pwd", fake_pwd)
    monkeypatch.setattr(privilege.os, "getuid", lambda: 0)
    monkeypatch.setenv("MERGECRAFT_AGENT_USER", "mergecraft")

    prepare_workspace_for_agent(str(repo))

    after_uid = dot_git.stat().st_uid
    assert after_uid == before_uid, ".git must not be chowned to the agent user"
