"""Lane A AP1.3 — git invariant controls in every shell branch (MCB-25 / D10)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from mergecraft.mcp import shell as shell_mod

pytestmark = pytest.mark.xfail(
    reason="green after AP4: read-only .git bind + git binary unavailable in namespace",
    strict=False,
)


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


def test_unsandboxed_branch_skips_namespace_mounts(monkeypatch: pytest.MonkeyPatch) -> None:
    joined = _joined_argv(monkeypatch, method="none")
    assert joined == "bash -c echo ok"
