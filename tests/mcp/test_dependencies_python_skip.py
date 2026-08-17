"""MCP dependency tools treat a Python policy skip as completed, not failed."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Literal

import pytest

from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.dependencies import _format_prep_results, start_installation
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.prep.types import PrepOptions, PrepResult
from mergecraft.utils.github import GitHubClient

_SKIP_ISSUE = (
    "skipped: python dependency installation can execute arbitrary code "
    "(setup.py, build backends, local path references), which is blocked "
    "when shell is disabled"
)
_PIP_FAIL = "pip install -r requirements.txt failed (exit 1)"


def _skip_result() -> PrepResult:
    return PrepResult(
        language="python",
        dependencies_installed=False,
        skipped=True,
        package_manager="uv",
        config_file="uv.lock",
        issues=[_SKIP_ISSUE],
    )


def _fail_result() -> PrepResult:
    return PrepResult(
        language="python",
        dependencies_installed=False,
        skipped=False,
        package_manager="pip",
        config_file="requirements.txt",
        issues=[_PIP_FAIL],
    )


def _tool_ctx(
    tmp_path: Path,
    *,
    shell: Literal["disabled", "restricted", "enabled"] = "disabled",
) -> ToolContext:
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="unknown"),
            shell=shell,
        ),
        github=GitHubClient(token="test-token"),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_server_url="",
        tmpdir=str(tmp_path),
    )


def test_format_prep_results_says_skipped_not_failed_for_python_skip() -> None:
    text = _format_prep_results([_skip_result()])
    assert "installation skipped" in text
    assert _SKIP_ISSUE in text
    assert "installation failed" not in text


def test_format_prep_results_still_reports_genuine_install_failure() -> None:
    text = _format_prep_results([_fail_result()])
    assert "installation failed" in text
    assert _PIP_FAIL in text
    assert "installation skipped" not in text


@pytest.mark.asyncio
async def test_start_installation_completes_on_python_policy_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Skip-only prep must land ``status="completed"``, not ``"failed"``."""
    skip = _skip_result()

    async def _fake_prep(options: PrepOptions) -> list[PrepResult]:
        assert options.ignore_scripts is True
        return [skip]

    monkeypatch.setattr("mergecraft.mcp.dependencies.run_prep_phase", _fake_prep)

    ctx = _tool_ctx(tmp_path, shell="disabled")
    start_installation(ctx)
    state = ctx.tool_state.dependency_installation
    assert state is not None
    assert state.promise is not None
    await state.promise
    await asyncio.sleep(0)

    assert state.status == "completed"
    assert state.results == [skip]


@pytest.mark.asyncio
async def test_start_installation_fails_on_genuine_install_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """W6.1 fail-closed: a real install failure still sets ``status="failed"``."""
    failed = _fail_result()

    async def _fake_prep(_options: PrepOptions) -> list[PrepResult]:
        return [failed]

    monkeypatch.setattr("mergecraft.mcp.dependencies.run_prep_phase", _fake_prep)

    ctx = _tool_ctx(tmp_path, shell="restricted")
    start_installation(ctx)
    state = ctx.tool_state.dependency_installation
    assert state is not None
    assert state.promise is not None
    await state.promise
    await asyncio.sleep(0)

    assert state.status == "failed"
    assert state.results == [failed]
