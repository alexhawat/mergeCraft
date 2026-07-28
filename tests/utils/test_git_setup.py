"""Tests for git identity / askpass setup."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from mergecraft.utils.git_setup import write_askpass_script

if TYPE_CHECKING:
    from pathlib import Path


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
