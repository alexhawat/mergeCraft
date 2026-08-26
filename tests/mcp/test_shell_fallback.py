"""Lane A AP1.2 — unsandboxed shell fallback policy (MCB-07 / D8)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from mergecraft.mcp import shell as shell_mod

pytestmark = pytest.mark.xfail(
    reason="green after AP3: fail-closed unsandboxed shell + wrapped fallback",
    strict=False,
)


def test_unsandboxed_shell_refuses_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MERGECRAFT_ALLOW_UNSANDBOXED_SHELL", raising=False)
    monkeypatch.setattr(shell_mod, "detect_sandbox_method", lambda: "none")
    with pytest.raises((RuntimeError, PermissionError, OSError)):
        shell_mod._spawn_shell(
            "echo ok",
            env={},
            cwd="/tmp",
            stdout=MagicMock(),
            stderr=MagicMock(),
            isolate_network=True,
        )


def test_allow_unsandboxed_env_var_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MERGECRAFT_ALLOW_UNSANDBOXED_SHELL", "1")
    monkeypatch.setattr(shell_mod, "detect_sandbox_method", lambda: "none")
    captured: list[list[str]] = []

    def _popen(argv: list[str], **_kwargs: Any) -> MagicMock:
        captured.append(argv)
        return MagicMock()

    monkeypatch.setattr(shell_mod.subprocess, "Popen", _popen)
    shell_mod._spawn_shell(
        "echo ok",
        env={},
        cwd="/tmp",
        stdout=MagicMock(),
        stderr=MagicMock(),
        isolate_network=False,
    )
    assert captured, "override must allow fallback spawn"


def test_fallback_branch_masks_container_sockets_when_it_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MERGECRAFT_ALLOW_UNSANDBOXED_SHELL", "1")
    monkeypatch.setattr(shell_mod, "detect_sandbox_method", lambda: "none")
    captured: list[str] = []

    def _popen(argv: list[str], **_kwargs: Any) -> MagicMock:
        captured.append(" ".join(argv))
        return MagicMock()

    monkeypatch.setattr(shell_mod.subprocess, "Popen", _popen)
    shell_mod._spawn_shell(
        "echo ok",
        env={},
        cwd="/tmp",
        stdout=MagicMock(),
        stderr=MagicMock(),
        isolate_network=False,
    )
    joined = captured[0]
    assert "docker.sock" in joined or "mount --bind /dev/null" in joined
