"""Tests for git identity / askpass setup."""

from __future__ import annotations

import os
import shutil
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


def _safe_staging_root(label: str) -> Path:
    """Stage outside pytest's /tmp tree so Codex-forbidden-root checks apply."""
    root = Path.home() / ".cache" / "mergecraft-test" / f"{label}-{os.getpid()}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_create_temp_directory_prefers_runner_temp_over_tmp(
    monkeypatch: MonkeyPatch,
) -> None:
    """Codex PATH aliases need CODEX_HOME outside /tmp — prefer RUNNER_TEMP."""
    staging = _safe_staging_root("runner")
    runner = staging / "runner-temp"
    runner.mkdir()
    monkeypatch.setenv("RUNNER_TEMP", str(runner))
    monkeypatch.delenv("MERGECRAFT_TEMP_PARENT", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    # Do not monkeypatch MERGECRAFT_TEMP_DIR: create_temp_directory writes
    # os.environ directly, and a later setenv undo would re-leak the value.
    os.environ.pop("MERGECRAFT_TEMP_DIR", None)

    try:
        created = create_temp_directory()
        assert created.startswith(str(runner))
        assert not _is_under_forbidden_temp(Path(created))
        assert os.environ["MERGECRAFT_TEMP_DIR"] == created
    finally:
        os.environ.pop("MERGECRAFT_TEMP_DIR", None)
        shutil.rmtree(staging, ignore_errors=True)


def test_create_temp_directory_skips_forbidden_runner_temp(
    monkeypatch: MonkeyPatch,
) -> None:
    """RUNNER_TEMP under /tmp is rejected; fall back to XDG cache."""
    # Stage under a real forbidden root (pytest's tmp_path may be /var/folders).
    forbidden_root = Path("/tmp") / f"mergecraft-test-forbidden-{os.getpid()}"
    runner = forbidden_root / "runner-temp"
    runner.mkdir(parents=True)
    assert _is_under_forbidden_temp(runner)
    cache_home = _safe_staging_root("xdg")
    monkeypatch.setenv("RUNNER_TEMP", str(runner))
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_home))
    monkeypatch.delenv("MERGECRAFT_TEMP_PARENT", raising=False)
    os.environ.pop("MERGECRAFT_TEMP_DIR", None)

    try:
        created = create_temp_directory()
        assert created.startswith(str(cache_home / "mergecraft" / "tmp"))
        assert not created.startswith(str(runner))
        assert not _is_under_forbidden_temp(Path(created))
        assert os.environ["MERGECRAFT_TEMP_DIR"] == created
    finally:
        os.environ.pop("MERGECRAFT_TEMP_DIR", None)
        shutil.rmtree(forbidden_root, ignore_errors=True)
        shutil.rmtree(cache_home, ignore_errors=True)
