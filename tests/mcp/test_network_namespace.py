"""W12.7 — network-namespace probe + ``unshare --net`` argv shaping (``#35``).

**Contract change (lane A / MCB-10):** when netns is unavailable the untrusted
shell capability is **absent** — mergeCraft must not silently drop ``--net`` and
continue. Inverted expectations below are ``xfail`` until **AP3** lands.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Literal
from unittest.mock import MagicMock

import pytest

from mergecraft.analyzers import sandbox as sandbox_mod
from mergecraft.mcp import shell as shell_mod
from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.server import build_common_tools
from mergecraft.mcp.shell import _spawn_shell, _unshare_argv, network_namespace_available
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

TrustTier = Literal["trusted", "untrusted"]


def _no_backend_caps() -> sandbox_mod.SandboxCapabilities:
    return sandbox_mod.SandboxCapabilities(
        pid_namespace=False,
        network_namespace=False,
        read_only_bind=False,
        tmpfs=False,
        cgroup_memory=False,
        rlimit_nproc=True,
        pid_namespace_method="none",
    )


@pytest.fixture(autouse=True)
def _reset_netns_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    shell_mod.reset_detection_cache()


def test_network_namespace_available_false_when_probe_reports_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D5 — netns follows the capability probe, not ``CI``."""
    from mergecraft.analyzers import sandbox as sandbox_mod

    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(
        sandbox_mod,
        "probe_capabilities",
        lambda: sandbox_mod.SandboxCapabilities(
            pid_namespace=True,
            network_namespace=False,
            read_only_bind=True,
            tmpfs=True,
            cgroup_memory=False,
            rlimit_nproc=True,
            pid_namespace_method="unshare",
        ),
    )
    shell_mod._reset_shell_detection_globals()
    assert network_namespace_available() is False


def test_network_namespace_available_true_when_unshare_net_succeeds_without_ci(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D5 — ``CI`` may hint but must not be the answer; probe ``unshare --net`` anyway."""
    from mergecraft.analyzers import sandbox as sandbox_mod

    monkeypatch.delenv("CI", raising=False)

    monkeypatch.setattr(
        sandbox_mod,
        "probe_capabilities",
        lambda: sandbox_mod.SandboxCapabilities(
            pid_namespace=True,
            network_namespace=True,
            read_only_bind=True,
            tmpfs=True,
            cgroup_memory=False,
            rlimit_nproc=True,
            pid_namespace_method="unshare",
        ),
    )
    shell_mod._reset_shell_detection_globals()
    assert network_namespace_available() is True


def test_network_namespace_available_false_when_unshare_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W12.7 — ``OSError`` from missing ``unshare`` caches unavailable."""
    monkeypatch.setenv("CI", "true")

    def _boom(*_a: object, **_k: object) -> object:
        raise OSError("unshare not found")

    monkeypatch.setattr(shell_mod.subprocess, "run", _boom)
    assert network_namespace_available() is False


def test_unshare_argv_omits_net_when_isolation_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W12.7 — trusted / non-isolate path never appends ``--net``."""
    monkeypatch.setattr(shell_mod, "network_namespace_available", lambda: True)
    argv = _unshare_argv(isolate_network=False)
    assert argv[:4] == ["unshare", "--pid", "--fork", "--mount-proc"]
    assert "--net" not in argv


def test_unshare_argv_adds_net_when_available_and_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W12.7 — untrusted shell adds ``--net`` only when the probe says ok."""
    monkeypatch.setattr(shell_mod, "_network_namespace_available", lambda: True)
    assert "--net" in _unshare_argv(isolate_network=True)


def test_unshare_argv_skips_net_when_probe_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MCB-10 inversion — isolate_network with no netns must fail closed, not omit ``--net``."""
    # H2 treats Darwin sandbox-exec as a real backend; force the no-backend
    # path (same as tests/mcp/test_shell_sandbox_honesty.py) so this sibling
    # still proves the raise on stock macOS.
    monkeypatch.setattr(shell_mod, "_detected_sandbox", None)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sandbox_mod, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(sandbox_mod, "probe_capabilities", _no_backend_caps)
    monkeypatch.setattr(shell_mod, "_network_namespace_available", lambda: False)
    with pytest.raises((RuntimeError, PermissionError, OSError)):
        _spawn_shell(
            "echo ok",
            env={},
            cwd="/tmp",
            stdout=MagicMock(),
            stderr=MagicMock(),
            isolate_network=True,
        )


def _tool_ctx(
    tmp_path: Path,
    *,
    trust_tier: TrustTier = "untrusted",
) -> ToolContext:
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="unknown"),
            shell="restricted",
        ),
        github=GitHubClient(token="test-token"),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_server_url="",
        tmpdir=str(tmp_path),
        trust_tier=trust_tier,
    )


def test_untrusted_shell_absent_when_netns_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D6 — missing netns removes the shell tool registration."""
    import mergecraft.mcp.server as server_mod

    monkeypatch.setattr(server_mod, "network_namespace_available", lambda: False)
    monkeypatch.setattr(server_mod, "detect_sandbox_method", lambda: "unshare")
    names = {spec.name for spec in build_common_tools(_tool_ctx(tmp_path, trust_tier="untrusted"))}
    assert "shell" not in names
    assert "kill_background" not in names
