"""OpenCode harness receives Zen credentials without leaking to logs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from tests.agents.conftest import make_agent_run_context

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

from mergecraft.agents.opencode import (
    OPENCODE_AUTH_ENV,
    _opencode_data_home,
    _setup_opencode_auth,
)
from mergecraft.security.opencode_auth import build_opencode_zen_auth_json
from mergecraft.utils.secrets import build_agent_env


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
