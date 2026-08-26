"""Lane A AP1.3 — git invariant controls in every shell branch (MCB-25 / D10)."""

from __future__ import annotations

import subprocess
import sys
from typing import Any
from unittest.mock import MagicMock

import pytest

from mergecraft.mcp import shell as shell_mod


def _joined_argv(monkeypatch: pytest.MonkeyPatch, *, method: str) -> str:
    monkeypatch.setattr(shell_mod, "detect_sandbox_method", lambda: method)
    monkeypatch.setattr(shell_mod, "network_namespace_available", lambda: True)
    if method == "none":
        monkeypatch.setenv("MERGECRAFT_ALLOW_UNSANDBOXED_SHELL", "1")
    captured: list[str] = []

    def _popen(argv: list[str], **_kwargs: Any) -> MagicMock:
        captured.extend(argv)
        return MagicMock()

    monkeypatch.setattr(shell_mod.subprocess, "Popen", _popen)
    shell_mod._spawn_shell(
        "echo ok",
        env={},
        cwd="/tmp",
        stdout=MagicMock(),
        stderr=MagicMock(),
        isolate_network=True,
    )
    return " ".join(captured)


@pytest.mark.parametrize("method", ["unshare", "sudo-unshare"])
def test_git_dir_is_read_only_in_sandboxed_branches(
    monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    joined = _joined_argv(monkeypatch, method=method)
    assert "remount,bind,ro" in joined
    assert ".git" in joined


@pytest.mark.parametrize("method", ["unshare", "sudo-unshare"])
def test_git_binary_unavailable_in_untrusted_namespace(
    monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    joined = _joined_argv(monkeypatch, method=method)
    assert "chmod 000" in joined or "unavailable" in joined or "/dev/null" in joined


def test_git_binary_hide_skips_path_dirs_without_git(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PATH dirs lacking git must not abort the hide loop (MCB-25)."""
    joined = _joined_argv(monkeypatch, method="unshare")
    assert 'if [ -x "$_dir/git" ]; then mount --bind /dev/null "$_dir/git" || exit 1; fi' in joined
    assert '[ -x "$_dir/git" ] && mount --bind /dev/null "$_dir/git" || exit 1' not in joined
    assert (
        'if [ -n "$_g" ] && [ -x "$_g" ]; then mount --bind /dev/null "$_g" || exit 1; fi' in joined
    )


def test_git_exec_path_and_git_core_binaries_are_masked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    joined = _joined_argv(monkeypatch, method="unshare")
    assert "git --exec-path" in joined
    assert '"/git"' in joined or '"/git-*"' in joined or "/git-core/git" in joined
    assert "/usr/lib/git-core/git" in joined


@pytest.mark.skipif(sys.platform != "linux", reason="live namespace mounts require Linux")
def test_git_core_binary_is_unavailable_in_live_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Debian action images expose git via ``/usr/lib/git-core`` outside PATH."""
    from mergecraft.mcp import shell as shell_mod

    monkeypatch.setattr(shell_mod, "detect_sandbox_method", lambda: "unshare")
    monkeypatch.setattr(shell_mod, "network_namespace_available", lambda: True)
    captured: list[str] = []

    real_popen = subprocess.Popen

    def _popen(argv: list[str], **_kwargs: Any) -> object:
        captured.extend(argv)
        # Run the wrapped bash -c for real to prove git-core is masked.
        return real_popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    monkeypatch.setattr(shell_mod.subprocess, "Popen", _popen)
    proc = shell_mod._spawn_shell(
        "for _g in /usr/lib/git-core/git /usr/lib/git-core/git-upload-pack; do "
        'if [ -x "$_g" ]; then "$_g" --version >/dev/null 2>&1 && echo "EXEC:$_g"; fi; '
        "done; echo DONE",
        env={},
        cwd="/tmp",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        isolate_network=True,
    )
    stdout, _stderr = proc.communicate(timeout=30)
    text = stdout.decode("utf-8", errors="replace")
    assert "EXEC:" not in text, text
    assert "DONE" in text


def test_unsandboxed_branch_skips_namespace_mounts(monkeypatch: pytest.MonkeyPatch) -> None:
    joined = _joined_argv(monkeypatch, method="none")
    assert joined == "bash -c echo ok"
