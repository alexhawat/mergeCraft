"""Tests for the run_static_checks tool: availability reporting and shell gating."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.server import build_common_tools
from mergecraft.mcp.static_checks import run_static_checks_tool
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.review_checks import StaticCheckConfig
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path


def _ctx(
    tmp_path: Path,
    *,
    shell: str = "restricted",
    static_checks: list[StaticCheckConfig] | None = None,
    enabled: bool = True,
) -> ToolContext:
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
        static_checks=static_checks or [],
        static_checks_enabled=enabled,
    )


async def _run(ctx: ToolContext, **params: Any) -> dict[str, Any]:
    result = await run_static_checks_tool(ctx).execute(params)
    return json.loads(result.content[0]["text"])


@pytest.mark.asyncio
async def test_reports_not_run_when_repo_declares_no_gate(tmp_path: Path) -> None:
    payload = await _run(_ctx(tmp_path))
    assert payload["ran"] is False
    assert "declares no mechanical gate" in payload["reason"]
    assert payload["checks"] == []


@pytest.mark.asyncio
async def test_reports_not_run_when_every_gate_is_unavailable(tmp_path: Path) -> None:
    """A repo can declare a gate this environment cannot run; that is not a finding."""
    ctx = _ctx(
        tmp_path,
        static_checks=[StaticCheckConfig(name="lint", command="mergecraft-no-such-binary")],
    )
    payload = await _run(ctx)
    assert payload["ran"] is False
    assert "unavailable" in payload["reason"]
    assert payload["checks"][0]["status"] == "unavailable"
    assert payload["checks"][0]["exitCode"] is None


@pytest.mark.asyncio
async def test_failing_gate_is_reported_as_ran_and_not_passed(tmp_path: Path) -> None:
    ctx = _ctx(
        tmp_path,
        static_checks=[StaticCheckConfig(name="lint", command="python -c 'raise SystemExit(1)'")],
    )
    payload = await _run(ctx)
    assert payload["ran"] is True
    assert payload["allPassed"] is False
    assert payload["checks"][0]["status"] == "failed"


@pytest.mark.asyncio
async def test_unavailable_gate_does_not_sink_a_passing_one(tmp_path: Path) -> None:
    ctx = _ctx(
        tmp_path,
        static_checks=[
            StaticCheckConfig(name="missing", command="mergecraft-no-such-binary"),
            StaticCheckConfig(name="ok", command="python -c 'pass'"),
        ],
    )
    payload = await _run(ctx)
    assert payload["ran"] is True
    assert payload["allPassed"] is True
    assert [c["status"] for c in payload["checks"]] == ["unavailable", "passed"]


def test_tool_is_withheld_when_static_checks_disabled(tmp_path: Path) -> None:
    """`shell: disabled` must not leave a path to running repo-declared commands."""
    names = {t.name for t in build_common_tools(_ctx(tmp_path, shell="disabled", enabled=False))}
    assert "run_static_checks" not in names
    names = {t.name for t in build_common_tools(_ctx(tmp_path, enabled=True))}
    assert "run_static_checks" in names


@pytest.mark.asyncio
async def test_static_checks_declared_but_cannot_run_when_shell_disabled(
    tmp_path: Path,
) -> None:
    """Configured staticChecks with shell disabled must report explicitly, not omit silently."""
    ctx = _ctx(
        tmp_path,
        shell="disabled",
        static_checks=[StaticCheckConfig(name="lint", command="python -c 'pass'")],
        enabled=True,
    )
    payload = await _run(ctx)
    assert payload["ran"] is False
    reason = str(payload.get("reason", "")).lower()
    checks = payload.get("checks") or []
    status_values = {str(check.get("status", "")).lower() for check in checks}
    assert "declared but cannot run" in reason or "declared-but-cannot-run" in status_values
    assert checks, "configured gates must appear as explicit unavailable rows"
