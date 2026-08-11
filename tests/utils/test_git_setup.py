"""Tests for git identity / askpass setup."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from mergecraft.utils import git_setup as git_setup_mod
from mergecraft.utils.git_setup import (
    _is_under_forbidden_temp,
    _safe_temp_parent,
    cleanup_temp_directory,
    create_temp_directory,
    register_created_path,
    setup_git,
    wipe_runner_leak_surface,
    write_askpass_script,
)

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


def test_askpass_returns_x_access_token_for_username(tmp_path: Path) -> None:
    """Username prompt → ``x-access-token``; password prompt → the token.

    Invoked via ``sh <path>`` because W2/D2 keeps the askpass file at ``0o600``
    (non-executable); the contract under test is content/output, not ``+x``.
    """
    script = write_askpass_script(str(tmp_path), "ghs_secrettoken")
    mode = stat.S_IMODE(Path(script).stat().st_mode)
    assert mode == 0o600, f"askpass must stay non-executable ({mode:o})"

    user = subprocess.run(
        ["sh", script, "Username for 'https://github.com': "],
        capture_output=True,
        text=True,
        check=True,
    )
    password = subprocess.run(
        ["sh", script, "Password for 'https://x-access-token@github.com': "],
        capture_output=True,
        text=True,
        check=True,
    )

    assert user.stdout.strip() == "x-access-token"
    assert password.stdout.strip() == "ghs_secrettoken"
    # The token must never be emitted for the username prompt (the old bug that
    # produced https://<token>:<token>@ and intermittent "invalid credentials").
    assert "ghs_secrettoken" not in user.stdout


def test_register_created_path_feeds_scoped_wipe(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Direct ``register_created_path`` contract — wipe removes only registered paths.

    Fails if the registry is deleted: the owned file survives and the assert turns red.
    """
    owned = tmp_path / "owned-leak.sh"
    owned.write_text("#!/bin/sh\necho secret\n", encoding="utf-8")
    foreign = tmp_path / "foreign.sh"
    foreign.write_text("#!/bin/sh\necho other\n", encoding="utf-8")
    register_created_path(str(owned))
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))

    wipe_runner_leak_surface()

    assert not owned.exists()
    assert foreign.exists(), "unregistered path must survive ownership-scoped wipe"


def test_cleanup_temp_directory_removes_askpass_and_tmpdir(
    monkeypatch: MonkeyPatch,
) -> None:
    """Direct ``cleanup_temp_directory`` — askpass overwritten/gone and tmpdir rmtree'd."""
    staging = _safe_staging_root("cleanup")
    runner = staging / "runner-temp"
    runner.mkdir()
    monkeypatch.setenv("RUNNER_TEMP", str(runner))
    monkeypatch.delenv("MERGECRAFT_TEMP_PARENT", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    os.environ.pop("MERGECRAFT_TEMP_DIR", None)

    try:
        created = create_temp_directory()
        askpass = write_askpass_script(created, "ghs_cleanup_token")
        assert Path(created).is_dir()
        assert Path(askpass).is_file()

        cleanup_temp_directory()

        assert not Path(created).exists(), "cleanup_temp_directory left the run tmpdir"
        assert not Path(askpass).exists(), "cleanup_temp_directory left the askpass file"
        # MERGECRAFT_TEMP_DIR may still name the removed path; the dir must be gone.
    finally:
        leftover = os.environ.pop("MERGECRAFT_TEMP_DIR", None)
        if leftover:
            shutil.rmtree(leftover, ignore_errors=True)
        shutil.rmtree(staging, ignore_errors=True)


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


def test_is_under_forbidden_temp_returns_false_on_resolve_oserror(
    monkeypatch: MonkeyPatch,
) -> None:
    """``Path.resolve`` OSError must not raise — treat as not-forbidden."""

    class BoomPath(type(Path())):  # type: ignore[misc]
        def resolve(self, strict: bool = False):
            raise OSError("boom")

    monkeypatch.setattr(git_setup_mod, "Path", BoomPath)
    assert _is_under_forbidden_temp(BoomPath("/tmp/x")) is False


def test_safe_temp_parent_returns_none_when_cache_mkdir_fails(
    monkeypatch: MonkeyPatch,
) -> None:
    """Cache mkdir OSError → no safe parent (caller falls back to system tmp)."""
    monkeypatch.delenv("MERGECRAFT_TEMP_PARENT", raising=False)
    monkeypatch.delenv("RUNNER_TEMP", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", "/tmp/mergecraft-cache-mkdir-fail")

    def boom_mkdir(self: Path, *args: object, **kwargs: object) -> None:
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "mkdir", boom_mkdir)
    assert _safe_temp_parent() is None


def test_safe_temp_parent_rejects_forbidden_xdg_cache(monkeypatch: MonkeyPatch) -> None:
    """XDG cache under /tmp is Codex-forbidden — treat as no safe parent."""
    monkeypatch.delenv("MERGECRAFT_TEMP_PARENT", raising=False)
    monkeypatch.delenv("RUNNER_TEMP", raising=False)
    forbidden_cache = Path("/tmp") / f"mergecraft-xdg-{os.getpid()}"
    monkeypatch.setenv("XDG_CACHE_HOME", str(forbidden_cache))
    try:
        assert _safe_temp_parent() is None
    finally:
        shutil.rmtree(forbidden_cache, ignore_errors=True)


def test_register_created_path_falls_back_when_resolve_fails(
    monkeypatch: MonkeyPatch,
) -> None:
    """Unresolvable paths are still registered (raw string) for wipe scoping."""
    git_setup_mod._created_paths.clear()

    class BoomPath(type(Path())):  # type: ignore[misc]
        def resolve(self, strict: bool = False):
            raise OSError("boom")

    monkeypatch.setattr(git_setup_mod, "Path", BoomPath)
    register_created_path("/no/such/owned-path")
    assert "/no/such/owned-path" in git_setup_mod._created_paths
    git_setup_mod._created_paths.discard("/no/such/owned-path")


def test_cleanup_temp_directory_noop_without_target(monkeypatch: MonkeyPatch) -> None:
    """No ``_temp_dir`` / ``MERGECRAFT_TEMP_DIR`` → cleanup is a no-op."""
    monkeypatch.setattr(git_setup_mod, "_temp_dir", None)
    monkeypatch.delenv("MERGECRAFT_TEMP_DIR", raising=False)
    cleanup_temp_directory()  # must not raise


def test_secure_overwrite_swallows_write_oserror(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Overwrite best-effort: write OSError must not escape cleanup."""
    target = tmp_path / "askpass.sh"
    target.write_text("secret\n", encoding="utf-8")

    class BoomFile:
        def write(self, _data: bytes) -> int:
            raise OSError("readonly")

        def flush(self) -> None:
            return None

        def __enter__(self) -> BoomFile:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(Path, "open", lambda self, *a, **k: BoomFile())
    git_setup_mod._secure_overwrite_file(target)  # must not raise


def test_setup_git_sets_bot_identity_when_email_missing(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Empty ``user.email`` → install mergeCraft bot identity locally."""
    from mergecraft.mcp.tool_state import init_tool_state
    from mergecraft.utils.git_setup import MERGECRAFT_BOT_EMAIL, MERGECRAFT_BOT_NAME

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    # Isolate from the developer's global identity.
    subprocess.run(
        ["git", "config", "--local", "--unset-all", "user.email"],
        cwd=repo,
        check=False,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "--local", "--unset-all", "user.name"],
        cwd=repo,
        check=False,
        capture_output=True,
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "empty-global-gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
    monkeypatch.chdir(repo)
    state = init_tool_state(owner="acme", name="demo", dir=str(repo))
    temp = tmp_path / "mc-temp"
    temp.mkdir()
    setup_git(
        git_token="ghs_token",
        owner="acme",
        name="demo",
        tool_state=state,
        shell="restricted",
        tmpdir=str(temp),
    )
    email = subprocess.check_output(
        ["git", "config", "--local", "--get", "user.email"], cwd=repo, text=True
    ).strip()
    name = subprocess.check_output(
        ["git", "config", "--local", "--get", "user.name"], cwd=repo, text=True
    ).strip()
    assert email == MERGECRAFT_BOT_EMAIL
    assert name == MERGECRAFT_BOT_NAME


def test_setup_git_skips_identity_when_user_email_already_set(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Existing non-Actions email is preserved (no overwrite to bot defaults)."""
    from mergecraft.mcp.tool_state import init_tool_state

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "dev@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Dev"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    monkeypatch.chdir(repo)
    state = init_tool_state(owner="acme", name="demo", dir=str(repo))
    temp = tmp_path / "mc-temp"
    temp.mkdir()
    setup_git(
        git_token="ghs_token",
        owner="acme",
        name="demo",
        tool_state=state,
        shell="restricted",
        tmpdir=str(temp),
    )
    email = subprocess.check_output(
        ["git", "config", "--get", "user.email"], cwd=repo, text=True
    ).strip()
    assert email == "dev@example.com"


def test_setup_git_falls_back_to_primary_repo_state(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """``require_repo_state`` miss → ``primary_repo_state`` still configures push_url."""
    from mergecraft.mcp.tool_state import init_tool_state

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    monkeypatch.chdir(repo)
    state = init_tool_state(owner="acme", name="demo", dir=str(repo))
    temp = tmp_path / "mc-temp"
    temp.mkdir()
    # Ask for a different owner/name so require_repo_state raises RuntimeError.
    setup_git(
        git_token="ghs_token",
        owner="other",
        name="elsewhere",
        tool_state=state,
        shell="disabled",
        tmpdir=str(temp),
    )
    assert state.repos  # primary still present
    primary = next(iter(state.repos.values()))
    assert primary.push_url == "https://github.com/other/elsewhere.git"


def test_wipe_preserves_active_temp_and_github_file_commands(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Active run temp + GITHUB_* file-command paths survive scoped wipe."""
    active = tmp_path / "active-temp"
    active.mkdir()
    nested = active / "nested.sh"
    nested.write_text("keep\n", encoding="utf-8")
    owned_outside = tmp_path / "owned-outside.sh"
    owned_outside.write_text("wipe-me\n", encoding="utf-8")
    gh_out = tmp_path / "github_output"
    gh_out.write_text("x=1\n", encoding="utf-8")

    git_setup_mod._created_paths.clear()
    git_setup_mod._temp_dir = str(active)
    register_created_path(str(nested))
    register_created_path(str(owned_outside))
    register_created_path(str(gh_out))
    monkeypatch.setenv("MERGECRAFT_TEMP_DIR", str(active))
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_out))

    wipe_runner_leak_surface()

    assert active.exists()
    assert nested.exists(), "paths under active temp must be preserved"
    assert gh_out.exists(), "GITHUB_OUTPUT must be preserved"
    assert not owned_outside.exists()
    git_setup_mod._temp_dir = None
    git_setup_mod._created_paths.clear()


def test_wipe_swallows_resolve_oserror_on_preserve_env(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Preserve-set still records the raw path when resolve fails."""
    owned = tmp_path / "owned.sh"
    owned.write_text("x\n", encoding="utf-8")
    git_setup_mod._created_paths.clear()
    register_created_path(str(owned))
    monkeypatch.setenv("GITHUB_ENV", str(tmp_path / "missing-env-file"))

    real_resolve = Path.resolve

    def flaky_resolve(self: Path, strict: bool = False) -> Path:
        if "missing-env-file" in str(self):
            raise OSError("gone")
        return real_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", flaky_resolve)
    wipe_runner_leak_surface()
    assert not owned.exists()
    git_setup_mod._created_paths.clear()


def test_prepare_temp_dir_for_agent_noop_when_not_root(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """Non-root hosts skip the agent-user chown path."""
    monkeypatch.setattr(os, "getuid", lambda: 1000)
    git_setup_mod._prepare_temp_dir_for_agent(str(tmp_path))  # must not raise


def test_prepare_temp_dir_for_agent_chowns_when_root(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """Root path: chmod/chown the temp tree for the dropped-UID agent."""
    monkeypatch.setattr(os, "getuid", lambda: 0)
    pw = MagicMock()
    pw.pw_uid = 1234
    pw.pw_gid = 1234
    fake_pwd = MagicMock()
    fake_pwd.getpwnam.return_value = pw
    monkeypatch.setitem(__import__("sys").modules, "pwd", fake_pwd)
    monkeypatch.setattr("mergecraft.utils.privilege.agent_user_name", lambda: "mergecraft")
    chown_calls: list[tuple[str, int, int]] = []

    def fake_chown(path: str, uid: int, gid: int) -> None:
        chown_calls.append((path, uid, gid))

    monkeypatch.setattr(os, "chown", fake_chown)
    monkeypatch.setattr(os, "chmod", lambda *_a, **_k: None)
    git_setup_mod._prepare_temp_dir_for_agent(str(tmp_path))
    assert chown_calls == [(str(tmp_path), 1234, 1234)]


def test_write_askpass_chowns_when_root(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """Root retains ownership of the credentials dir + askpass file."""
    monkeypatch.setattr(os, "getuid", lambda: 0)
    chown_targets: list[str] = []

    def fake_chown(path: str | int | bytes, uid: int, gid: int) -> None:
        chown_targets.append(str(path))

    monkeypatch.setattr(os, "chown", fake_chown)
    askpass = write_askpass_script(str(tmp_path), "ghs_root_token")
    assert askpass in chown_targets or str(Path(askpass).parent) in chown_targets
    assert Path(askpass).is_file()
