"""Agent drivers create credential-bearing files owner-only at creation.

Each file below is created through ``os.open`` with mode ``0600``, so it never
exists with the umask's wider default, not even between the write and a later
``chmod``. The spy records every ``os.open`` that creates a file; the assertions
need a ``0600`` creation in the destination directory and a final ``0600`` mode.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest
from tests.agents.conftest import make_agent_run_context

from mergecraft.agents import claude, codex
from mergecraft.agents import opencode as oc
from mergecraft.security.opencode_auth import build_opencode_zen_auth_json

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")

_CODEX_AUTH = json.dumps({"tokens": {"access_token": "codex-placeholder-not-a-credential"}})


@pytest.fixture
def creations(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Path, int]]:
    """Record (path, mode) for every ``os.open`` that may create a file."""
    seen: list[tuple[Path, int]] = []
    real_open = os.open

    def _open(path: str | os.PathLike[str], flags: int, mode: int = 0o777, **kw: object) -> int:
        if flags & os.O_CREAT:
            seen.append((Path(os.fspath(path)), mode))
        return real_open(path, flags, mode, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "open", _open)
    old_umask = os.umask(0)
    yield seen
    os.umask(old_umask)


def _assert_created_private(path: Path, creations: list[tuple[Path, int]]) -> None:
    assert path.is_file()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    in_dir = [mode for created, mode in creations if created.parent == path.parent]
    assert in_dir, f"{path.name} was not created through os.open"
    assert all(mode == 0o600 for mode in in_dir)


def test_codex_auth_file_is_owner_only_at_creation(
    tmp_path: Path, creations: list[tuple[Path, int]]
) -> None:
    ctx = make_agent_run_context(tmp_path, resolved_model=None)
    codex_home = tmp_path / "codex-home"

    codex._setup_codex_auth(
        ctx, codex_home=codex_home, credential_env={codex.CODEX_AUTH_ENV: _CODEX_AUTH}
    )

    _assert_created_private(codex_home / "auth.json", creations)


def test_opencode_auth_file_is_owner_only_at_creation(
    tmp_path: Path, creations: list[tuple[Path, int]]
) -> None:
    ctx = make_agent_run_context(tmp_path, resolved_model=None)
    data_home = tmp_path / "opencode-xdg-data"

    oc._setup_opencode_auth(
        ctx,
        data_home=data_home,
        credential_env={oc.OPENCODE_AUTH_ENV: build_opencode_zen_auth_json("zen-placeholder")},
    )

    _assert_created_private(data_home / "opencode" / "auth.json", creations)


def test_claude_mcp_config_is_owner_only_at_creation(
    tmp_path: Path, creations: list[tuple[Path, int]]
) -> None:
    ctx = make_agent_run_context(tmp_path, resolved_model=None)
    ctx.mcp_auth_token = "per-run-placeholder"

    path = Path(claude.write_mcp_config(ctx))

    _assert_created_private(path, creations)
