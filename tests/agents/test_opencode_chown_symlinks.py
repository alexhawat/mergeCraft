"""F42 — handing the opencode XDG tree to the agent never follows a symlink out of it."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from mergecraft.agents import opencode

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX ownership semantics")


def test_symlink_pointing_outside_the_tree_is_never_chmoded_or_followed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path / "outside" / "host-secret"
    outside.parent.mkdir()
    outside.write_text("do not touch", encoding="utf-8")

    data_home = tmp_path / "xdg"
    (data_home / "opencode").mkdir(parents=True)
    (data_home / "opencode" / "auth.json").write_text("{}", encoding="utf-8")
    (data_home / "opencode" / "escape").symlink_to(outside)
    (data_home / "linked-dir").symlink_to(outside.parent, target_is_directory=True)

    chown_calls: list[tuple[str, dict[str, Any]]] = []
    chmod_calls: list[str] = []

    def _chown(path: object, uid: int, gid: int, **kwargs: Any) -> None:
        chown_calls.append((str(path), kwargs))

    def _chmod(path: object, mode: int, **kwargs: Any) -> None:
        chmod_calls.append(str(path))

    monkeypatch.setattr(os, "getuid", lambda: 0)
    monkeypatch.setattr(os, "chown", _chown)
    monkeypatch.setattr(os, "chmod", _chmod)
    monkeypatch.setattr(
        "pwd.getpwnam",
        lambda name: SimpleNamespace(pw_uid=4242, pw_gid=4242),
    )
    monkeypatch.setattr("mergecraft.utils.privilege.agent_user_name", lambda: "mergecraft-agent")

    opencode._hand_xdg_data_home_to_agent(data_home)

    touched = {p for p, _kw in chown_calls} | set(chmod_calls)
    assert str(outside) not in touched, "a link target outside the tree must never be touched"
    assert str(outside.parent) not in touched
    assert str(data_home / "opencode" / "auth.json") in {p for p, _ in chown_calls}
    # Every chown call that names a path inside the tree passes follow_symlinks=False.
    assert chown_calls
    assert all(kw.get("follow_symlinks") is False for _p, kw in chown_calls)
    # Symlinks are re-owned as links, and never chmoded.
    assert str(data_home / "opencode" / "escape") not in chmod_calls
    assert str(data_home / "linked-dir") not in chmod_calls
    # The walk must not descend a symlinked directory and re-own its contents.
    assert not any(p.startswith(str(data_home / "linked-dir") + os.sep) for p, _ in chown_calls)
