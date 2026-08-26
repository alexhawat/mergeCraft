"""W12.7 — network-namespace probe + ``unshare --net`` argv shaping (``#35``).

**Contract change (lane A / MCB-10):** when netns is unavailable the untrusted
shell capability is **absent** — mergeCraft must not silently drop ``--net`` and
continue. Inverted expectations below are ``xfail`` until **AP3** lands.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from unittest.mock import MagicMock

import pytest

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


@pytest.fixture(autouse=True)
def _reset_netns_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    shell_mod.reset_detection_cache()


def test_network_namespace_available_false_outside_ci(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W12.7 — non-CI hosts skip the probe and treat netns as unavailable (trunk)."""
    monkeypatch.delenv("CI", raising=False)
    assert network_namespace_available() is False


@pytest.mark.xfail(
    reason="green after AP3: probe capability instead of sensing CI",
    strict=False,
)
def test_network_namespace_available_true_when_unshare_net_succeeds_without_ci(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D5 — ``CI`` may hint but must not be the answer; probe ``unshare --net`` anyway."""
    monkeypatch.delenv("CI", raising=False)

    class _Result:
        returncode = 0

    monkeypatch.setattr(shell_mod.subprocess, "run", lambda *a, **k: _Result())
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
    monkeypatch.setattr(shell_mod, "network_namespace_available", lambda: True)
    assert "--net" in _unshare_argv(isolate_network=True)


@pytest.mark.xfail(
    reason="green after AP3: netns absence must not silently omit --net",
    strict=False,
)
def test_unshare_argv_skips_net_when_probe_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MCB-10 inversion — isolate_network with no netns must fail closed, not omit ``--net``."""
    monkeypatch.setattr(shell_mod, "network_namespace_available", lambda: False)
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


@pytest.mark.xfail(
    reason="green after AP3: untrusted shell absent when netns unavailable",
    strict=False,
)
def test_untrusted_shell_absent_when_netns_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D6 — missing netns removes the shell tool registration."""
    monkeypatch.setattr(shell_mod, "network_namespace_available", lambda: False)
    monkeypatch.setattr(shell_mod, "detect_sandbox_method", lambda: "unshare")
    names = {spec.name for spec in build_common_tools(_tool_ctx(tmp_path, trust_tier="untrusted"))}
    assert "shell" not in names
    assert "kill_background" not in names
