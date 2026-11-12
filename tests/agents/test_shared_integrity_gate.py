"""The read-only checkout integrity gate covers every local CLI harness (#1329).

It used to exist only in the OpenCode driver. It now runs in ``AgentImpl.run``
for Claude, Codex and Gemini (OpenCode keeps its own per-attempt gate). Each
case runs the real registered agent object with only its ``_run`` replaced by a
stand-in that does or does not touch the checkout.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.agents import claude as claude_module
from mergecraft.agents import codex as codex_module
from mergecraft.agents import gemini as gemini_module
from mergecraft.agents.shared import AgentResult, AgentRunContext, ResolvedInstructions
from mergecraft.mcp.context import PayloadEvent, ResolvedPayload
from mergecraft.mcp.tool_state import init_tool_state

if TYPE_CHECKING:
    from pathlib import Path

_AGENTS = {
    "claude": claude_module.claude,
    "codex": codex_module.codex,
    "gemini": gemini_module.gemini,
}


def _ctx(checkout: Path, tmpdir: Path) -> AgentRunContext:
    checkout.mkdir(parents=True, exist_ok=True)
    tmpdir.mkdir(parents=True, exist_ok=True)
    (checkout / "app.py").write_text("print('hi')\n", encoding="utf-8")
    return AgentRunContext(
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request")),
        mcp_server_url="",
        tmpdir=str(tmpdir),
        subagent_denied_tools=(),
        instructions=ResolvedInstructions(user="review"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(checkout)),
    )


def _with_run(name: str, run: Any) -> Any:
    return replace(_AGENTS[name], _run=run)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", sorted(_AGENTS), ids=sorted(_AGENTS))
async def test_a_checkout_modified_during_review_fails_closed(name: str, tmp_path: Path) -> None:
    checkout = tmp_path / "repo"
    ctx = _ctx(checkout, tmp_path / "run")

    async def _writes_the_checkout(_ctx: AgentRunContext) -> AgentResult:
        (checkout / "app.py").write_text("print('changed')\n", encoding="utf-8")
        return AgentResult(success=True, output="looks good")

    result = await _with_run(name, _writes_the_checkout).run(ctx)

    assert result.success is False
    assert "checkout integrity failure" in (result.error or "")


@pytest.mark.asyncio
@pytest.mark.parametrize("name", sorted(_AGENTS), ids=sorted(_AGENTS))
async def test_an_untouched_checkout_passes(name: str, tmp_path: Path) -> None:
    ctx = _ctx(tmp_path / "repo", tmp_path / "run")

    async def _reads_only(_ctx: AgentRunContext) -> AgentResult:
        return AgentResult(success=True, output="looks good")

    result = await _with_run(name, _reads_only).run(ctx)

    assert result.success is True
    assert ctx.tool_state.review_tree_baseline is not None


@pytest.mark.asyncio
async def test_the_gate_is_skipped_when_the_run_tmpdir_is_inside_the_checkout(
    tmp_path: Path,
) -> None:
    """The run's own config files would otherwise fail every review closed."""
    checkout = tmp_path / "repo"
    ctx = _ctx(checkout, checkout / ".tmp-run")

    async def _writes_run_config(run_ctx: AgentRunContext) -> AgentResult:
        (checkout / ".tmp-run" / "mcp.json").write_text("{}", encoding="utf-8")
        return AgentResult(success=True)

    result = await _with_run("claude", _writes_run_config).run(ctx)

    assert result.success is True


@pytest.mark.asyncio
async def test_an_unhashable_checkout_fails_the_attempt_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no baseline the read-only guarantee is unverified, so the agent never runs."""
    ctx = _ctx(tmp_path / "repo", tmp_path / "run")

    def _unreadable(_root: Path) -> str:
        raise PermissionError("tree is unreadable")

    monkeypatch.setattr("mergecraft.security.review_integrity.hash_tree", _unreadable)
    ran: list[bool] = []

    async def _reads_only(_ctx: AgentRunContext) -> AgentResult:
        ran.append(True)
        return AgentResult(success=True)

    result = await _with_run("codex", _reads_only).run(ctx)

    assert result.success is False
    assert "checkout integrity failure" in (result.error or "")
    assert ran == []
