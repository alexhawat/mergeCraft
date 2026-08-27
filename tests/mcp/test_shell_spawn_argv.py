"""Lane A AP1.3 — sudo argv must not carry secret values (MCB-08 / D9)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from mergecraft.mcp import shell as shell_mod
from mergecraft.utils.secrets import PROVIDER_KEY_ENV_VARS

_CANARY = "CANARY_PROVIDER_SECRET_VALUE_AP1"


@pytest.fixture(autouse=True)
def _sandbox_sudo_unshare(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shell_mod, "detect_sandbox_method", lambda: "sudo-unshare")
    monkeypatch.setattr(shell_mod, "network_namespace_available", lambda: False)
    shell_mod.reset_detection_cache()


def _env_with_canaries() -> dict[str, str]:
    return {name: _CANARY for name in PROVIDER_KEY_ENV_VARS}


def _capture_argv(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    captured: list[str] = []

    def _popen(argv: list[str], **_kwargs: Any) -> MagicMock:
        captured.extend(argv)
        return MagicMock()

    monkeypatch.setattr(shell_mod.subprocess, "Popen", _popen)
    return captured


@pytest.mark.parametrize(
    "isolate_network",
    [
        False,
        True,
    ],
    ids=["pid_only", "pid_and_net"],
)
def test_no_provider_key_value_appears_in_any_branch_argv(
    monkeypatch: pytest.MonkeyPatch, isolate_network: bool
) -> None:
    # The netns probe is a property of the host, not of argv construction:
    # macOS has no network namespaces and GitHub's runners fail
    # ``unshare --net`` too, so without this stub the isolate_network=True case
    # raises in shell.py:307 before reaching the assertion below. Stubbing it
    # makes the branch reachable and the result host-independent -- which is
    # what let the previous xfail(strict=False) sit here silently either way.
    monkeypatch.setattr(shell_mod, "_network_namespace_available", lambda: True)
    for method in ("unshare", "sudo-unshare", "none"):
        monkeypatch.setenv("MERGECRAFT_ALLOW_UNSANDBOXED_SHELL", "1")
        if method == "unshare":
            monkeypatch.setattr(shell_mod, "detect_sandbox_method", lambda: "unshare")
        elif method == "sudo-unshare":
            monkeypatch.setattr(shell_mod, "detect_sandbox_method", lambda: "sudo-unshare")
        else:
            monkeypatch.setattr(shell_mod, "detect_sandbox_method", lambda: "none")
        captured = _capture_argv(monkeypatch)
        shell_mod._spawn_shell(
            "echo ok",
            env=_env_with_canaries(),
            cwd="/tmp",
            stdout=MagicMock(),
            stderr=MagicMock(),
            isolate_network=isolate_network,
        )
        joined = " ".join(captured)
        assert _CANARY not in joined, f"secret leaked in argv for method={method}"


def test_sudo_branch_uses_preserve_env_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _capture_argv(monkeypatch)
    env = {"ANTHROPIC_API_KEY": "sekret", "PATH": "/usr/bin"}
    shell_mod._spawn_shell(
        "echo ok",
        env=env,
        cwd="/tmp",
        stdout=MagicMock(),
        stderr=MagicMock(),
    )
    assert any(arg.startswith("--preserve-env=") for arg in captured)
    assert not any("=sekret" in arg for arg in captured)
