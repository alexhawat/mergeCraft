"""Tests for git identity / askpass setup."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from mergecraft.utils.git_setup import (
    _is_under_forbidden_temp,
    create_temp_directory,
    write_askpass_script,
)

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


def test_askpass_returns_x_access_token_for_username(tmp_path: Path) -> None:
    """Username prompt → ``x-access-token``; password prompt → the token."""
    script = write_askpass_script(str(tmp_path), "ghs_secrettoken")

    user = subprocess.run(
        [script, "Username for 'https://github.com': "],
        capture_output=True,
        text=True,
        check=True,
    )
    password = subprocess.run(
        [script, "Password for 'https://x-access-token@github.com': "],
        capture_output=True,
        text=True,
        check=True,
    )

    assert user.stdout.strip() == "x-access-token"
    assert password.stdout.strip() == "ghs_secrettoken"
    # The token must never be emitted for the username prompt (the old bug that
    # produced https://<token>:<token>@ and intermittent "invalid credentials").
    assert "ghs_secrettoken" not in user.stdout


def test_create_temp_directory_prefers_runner_temp_over_tmp(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Codex PATH aliases need CODEX_HOME outside /tmp — prefer RUNNER_TEMP."""
    runner = tmp_path / "runner-temp"
    runner.mkdir()
    monkeypatch.setenv("RUNNER_TEMP", str(runner))
    monkeypatch.delenv("MERGECRAFT_TEMP_PARENT", raising=False)
    monkeypatch.delenv("MERGECRAFT_TEMP_DIR", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)

    created = create_temp_directory()
    assert created.startswith(str(runner))
    assert not _is_under_forbidden_temp(Path(created))
    assert os.environ["MERGECRAFT_TEMP_DIR"] == created
