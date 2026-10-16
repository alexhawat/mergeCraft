"""OpenCode harness receives Zen credentials without leaking to logs."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from tests.agents.conftest import make_agent_run_context

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

from mergecraft.agents import opencode as opencode_module
from mergecraft.agents.opencode import (
    OPENCODE_AUTH_ENV,
    _opencode_data_home,
    _setup_opencode_auth,
)
from mergecraft.security.opencode_auth import build_opencode_zen_auth_json
from mergecraft.utils.secrets import build_agent_env


class _FakePw:
    """Stand-in ``pwd.struct_passwd`` for the simulated privilege drop."""

    pw_name = "mergecraft"
    pw_uid = 1001
    pw_gid = 1001
    pw_dir = "/home/mergecraft"


def _capture_chowns(monkeypatch: MonkeyPatch) -> list[tuple[str, int, int]]:
    """Replace ``os.chown`` with a recorder so no real ownership changes happen."""
    chowns: list[tuple[str, int, int]] = []

    def _fake_chown(path: object, uid: int, gid: int, **_kwargs: object) -> None:
        chowns.append((str(path), uid, gid))

    monkeypatch.setattr(opencode_module.os, "chown", _fake_chown)
    return chowns


def test_setup_opencode_auth_writes_isolated_auth_json(tmp_path: Path) -> None:
    ctx = make_agent_run_context(tmp_path, resolved_model="opencode/gpt")
    data_home = tmp_path / "xdg"
    secret = build_opencode_zen_auth_json("unit-test-zen-key")
    _setup_opencode_auth(ctx, data_home=data_home, credential_env={OPENCODE_AUTH_ENV: secret})
    auth_path = data_home / "opencode" / "auth.json"
    assert auth_path.is_file()
    parsed = json.loads(auth_path.read_text(encoding="utf-8"))
    assert parsed["opencode"]["key"] == "unit-test-zen-key"
    assert auth_path.stat().st_mode & 0o777 == 0o600


def test_build_agent_env_reinjects_opencode_api_key_from_auth_json(
    monkeypatch: MonkeyPatch,
) -> None:
    secret = build_opencode_zen_auth_json("reinjected-key")
    monkeypatch.setenv(OPENCODE_AUTH_ENV, secret)
    env = build_agent_env("opencode", model="opencode/gpt")
    assert env["OPENCODE_API_KEY"] == "reinjected-key"
    assert env[OPENCODE_AUTH_ENV] == secret


def test_opencode_data_home_is_under_run_tmpdir(tmp_path: Path) -> None:
    ctx = make_agent_run_context(tmp_path, resolved_model="opencode/gpt")
    assert _opencode_data_home(ctx) == Path(ctx.tmpdir) / "opencode-xdg-data"


def test_setup_opencode_auth_hands_xdg_tree_to_agent_user(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Root-created XDG tree must be chowned or the dropped CLI cannot write logs."""
    monkeypatch.setattr(opencode_module.os, "getuid", lambda: 0)
    monkeypatch.delenv("MERGECRAFT_AGENT_USER", raising=False)
    fake_pwd = MagicMock()
    fake_pwd.getpwnam.return_value = _FakePw()
    monkeypatch.setitem(sys.modules, "pwd", fake_pwd)
    chowns = _capture_chowns(monkeypatch)

    ctx = make_agent_run_context(tmp_path, resolved_model="opencode/gpt")
    data_home = tmp_path / "xdg"
    secret = build_opencode_zen_auth_json("unit-test-zen-key")
    _setup_opencode_auth(ctx, data_home=data_home, credential_env={OPENCODE_AUTH_ENV: secret})

    chowned = {path for path, uid, gid in chowns if (uid, gid) == (1001, 1001)}
    assert str(data_home) in chowned
    assert str(data_home / "opencode") in chowned
    auth_path = data_home / "opencode" / "auth.json"
    assert str(auth_path) in chowned
    # The credential stays owner-readable only — the chown must not widen it.
    assert auth_path.stat().st_mode & 0o777 == 0o600


def test_setup_opencode_auth_does_not_chown_when_not_root(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Outside the action image no privilege drop applies, so chown is a no-op."""
    monkeypatch.setattr(opencode_module.os, "getuid", lambda: 501)
    chowns = _capture_chowns(monkeypatch)

    ctx = make_agent_run_context(tmp_path, resolved_model="opencode/gpt")
    data_home = tmp_path / "xdg"
    secret = build_opencode_zen_auth_json("unit-test-zen-key")
    _setup_opencode_auth(ctx, data_home=data_home, credential_env={OPENCODE_AUTH_ENV: secret})

    assert chowns == []
    assert (data_home / "opencode" / "auth.json").is_file()
