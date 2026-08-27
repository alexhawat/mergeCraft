"""Agent drivers chown their config directories before the privilege drop (#194).

``write_mcp_config()`` (all three drivers) and Codex's ``_setup_codex_auth()``
run inside the still-root action entrypoint and create a fresh directory
(``$CODEX_HOME`` / ``.gemini`` / ``.claude``) to hold MCP config, instructions,
and auth files. Directory/file ownership follows the *creating* process's
uid, not the parent tmpdir's owner — so even though the parent run tmpdir is
already agent-owned (``git_setup._prepare_temp_dir_for_agent``), a plain
``mkdir()`` by this still-root code leaves the newly created subdirectory
root-owned. The later ``setpriv``-dropped agent CLI subprocess then fails
with ``EACCES``/``Permission denied`` the first time it needs to write into
that same directory (observed in production as Codex's ``os error 13``
writing PATH-alias helpers under ``$CODEX_HOME``).

These tests drive each function with root simulated (monkeypatched
``os.getuid``/``pwd.getpwnam``, matching
``tests/agents/test_privilege_drop_home_wiring.py``'s pattern for the sibling
``$HOME`` bug) and assert ``prepare_workspace_for_agent`` — the same chown
helper ``main.py`` already used for the checkout workspace — actually runs
against the directory each function just wrote into, as the *last* step.

Claude's and Gemini's ``write_mcp_config()`` each have a single write point,
so each chows inline, and this file covers them directly. Codex has two
separate write points (``_setup_codex_auth()`` and ``write_mcp_config()``,
both called from ``_build_env()``) and the real fix centralizes a single
chown in that caller, after both have run, rather than chowning inline in
each — so Codex's coverage lives in
``test_privilege_drop_home_wiring.py::test_build_env_chowns_codex_home_under_privilege_drop``
instead of here.
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from tests.agents.conftest import make_agent_run_context

from mergecraft.utils import privilege as privilege_module

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

claude_module = importlib.import_module("mergecraft.agents.claude")
gemini_module = importlib.import_module("mergecraft.agents.gemini")
codex_module = importlib.import_module("mergecraft.agents.codex")


class _FakePw:
    pw_name = "mergecraft"
    pw_uid = 1001
    pw_gid = 1001
    pw_dir = "/home/mergecraft"


def _simulate_root_privilege_drop(monkeypatch: MonkeyPatch) -> list[list[str]]:
    """Simulate the action-image root path and capture every ``chown`` argv.

    Mirrors ``test_privilege_drop_home_wiring._simulate_root_privilege_drop``:
    ``os.getuid`` reports root and ``pwd.getpwnam`` resolves the agent user.
    Returns the list ``prepare_workspace_for_agent``'s ``subprocess.run``
    calls land in, so callers can assert on the chowned path.
    """
    monkeypatch.setattr(privilege_module.os, "getuid", lambda: 0)
    monkeypatch.setattr(privilege_module, "_in_action_image", lambda: True)
    monkeypatch.setattr(privilege_module, "_setpriv_supports_bounding_set", lambda: True)
    fake_pwd = MagicMock()
    fake_pwd.getpwnam.return_value = _FakePw()
    monkeypatch.setitem(sys.modules, "pwd", fake_pwd)
    monkeypatch.delenv("MERGECRAFT_AGENT_USER", raising=False)

    calls: list[list[str]] = []

    def _fake_run(cmd: list[str], **_kwargs: object) -> object:
        calls.append(cmd)
        return MagicMock(returncode=0)

    monkeypatch.setattr(privilege_module.subprocess, "run", _fake_run)
    return calls


def test_claude_write_mcp_config_chowns_config_dir_under_privilege_drop(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    calls = _simulate_root_privilege_drop(monkeypatch)

    ctx = make_agent_run_context(tmp_path, resolved_model="claude-sonnet")
    claude_module.write_mcp_config(ctx)

    config_dir = tmp_path / ".claude"
    assert calls, "prepare_workspace_for_agent must chown the newly created config dir"
    chown_call = next(c for c in calls if c[0] == "find")
    assert "chown" in chown_call
    assert chown_call[1] == str(config_dir)
    assert chown_call[-3] == "1001:1001"


def test_gemini_write_mcp_config_chowns_gemini_home_under_privilege_drop(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    calls = _simulate_root_privilege_drop(monkeypatch)

    ctx = make_agent_run_context(tmp_path, resolved_model="gemini-2.5-pro")
    gemini_module.write_mcp_config(ctx)

    gemini_home = tmp_path / ".gemini"
    assert calls, "prepare_workspace_for_agent must chown the newly created gemini home"
    chown_call = next(c for c in calls if c[0] == "find")
    assert "chown" in chown_call
    assert chown_call[1] == str(gemini_home)


def test_write_mcp_config_does_not_chown_when_not_root(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """No privilege drop applies outside the action image — chown is a no-op."""
    monkeypatch.setattr(privilege_module.os, "getuid", lambda: 501)

    calls: list[list[str]] = []

    def _fake_run(cmd: list[str], **_kwargs: object) -> object:
        calls.append(cmd)
        return MagicMock(returncode=0)

    monkeypatch.setattr(privilege_module.subprocess, "run", _fake_run)

    ctx = make_agent_run_context(tmp_path, resolved_model="claude-sonnet")
    claude_module.write_mcp_config(ctx)

    assert calls == []
