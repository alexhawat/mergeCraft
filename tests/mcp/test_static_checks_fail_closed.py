"""Untrusted static checks fail closed when isolation is missing, whatever ``shell`` says (#887)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from mergecraft.analyzers import sandbox as sandbox_mod
from mergecraft.mcp import shell as shell_mod
from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.static_checks import run_static_checks_tool
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.review_checks import StaticCheck, StaticCheckConfig, run_checks
from mergecraft.utils.github import GitHubClient


def _ctx(tmp_path: Path, *, shell: str, tier: str) -> ToolContext:
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="unknown"),
            shell=shell,  # type: ignore[arg-type]
        ),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_server_url="",
        tmpdir=str(tmp_path),
        static_checks=[StaticCheckConfig(name="lint", command="python -c 'pass'")],
        static_checks_enabled=True,
        trust_tier=tier,  # type: ignore[arg-type]
    )


def _no_isolation_caps() -> sandbox_mod.SandboxCapabilities:
    return sandbox_mod.SandboxCapabilities(
        pid_namespace=False,
        network_namespace=False,
        read_only_bind=False,
        tmpfs=False,
        cgroup_memory=False,
        rlimit_nproc=False,
        pid_namespace_method="none",
        user_namespace=False,
        unavailable_reasons=["pid namespace unavailable (unshare failed)"],
    )


@pytest.mark.parametrize("shell", ["restricted", "enabled", "disabled"])
@pytest.mark.asyncio
async def test_untrusted_gates_never_launch_a_subprocess_without_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shell: str
) -> None:
    monkeypatch.setattr(sandbox_mod, "probe_capabilities", _no_isolation_caps)
    shell_mod._reset_shell_detection_globals()
    launched: list[list[str]] = []

    def _forbidden(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        launched.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", _forbidden)

    ctx = _ctx(tmp_path, shell=shell, tier="untrusted")
    result = await run_static_checks_tool(ctx).execute({})
    payload = json.loads(result.content[0]["text"])

    assert launched == []
    assert payload["ran"] is False
    assert [check["status"] for check in payload["checks"]] == ["declared-but-cannot-run"]
    assert "isolation" in payload["checks"][0]["output"].casefold()


def test_run_checks_refuses_an_untrusted_gate_without_a_sandbox_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defence in depth: the executor itself will not run a PR-controlled gate bare."""
    launched: list[list[str]] = []

    def _forbidden(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        launched.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", _forbidden)
    check = StaticCheck(name="lint", argv=("python", "-c", "pass"))

    outcomes = run_checks([check], root=tmp_path, tier="untrusted", sandbox_context=None)

    assert launched == []
    assert [outcome.status for outcome in outcomes] == ["declared-but-cannot-run"]
    assert "isolation" in outcomes[0].output.casefold()
