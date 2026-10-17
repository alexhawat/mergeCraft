"""The IncrementalReview prompt names no tool the review session refuses.

A prompt step that tells the agent to call a tool the server refuses always fails:
the agent spends turns on refused calls and the work the instruction describes never
happens. The refused set is derived from the live guard (``guard_mutating_tool``) over
the real tool registry, so a later change to the review-session allowlist keeps this
test honest instead of leaving a stale hard-coded list behind.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from tests.support.tool_context import make_tool_context

from mergecraft.mcp.server import build_orchestrator_tools
from mergecraft.mcp.shared import guard_mutating_tool
from mergecraft.modes import compute_modes
from mergecraft.types import format_mcp_tool_ref

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.types import AgentId


def _refused_in_review_session(tmp_path: Path) -> set[str]:
    ctx = make_tool_context(tmp_path, trust_tier="trusted", signed_commits=True)
    refused: set[str] = set()
    for tool in build_orchestrator_tools(ctx):
        if not tool.mutates:
            continue
        try:
            guard_mutating_tool(tool.name, selected_mode="IncrementalReview")
        except Exception:
            refused.add(tool.name)
    return refused


def _prompt(mode_name: str, agent_id: AgentId) -> str:
    for mode in compute_modes(agent_id):
        if mode.name == mode_name:
            assert mode.prompt is not None
            return mode.prompt
    msg = f"mode {mode_name!r} missing"
    raise AssertionError(msg)


def _names(prompt: str, tool: str, agent_id: AgentId) -> bool:
    ref = format_mcp_tool_ref(agent_id, tool)
    boundary = r"(?<![A-Za-z0-9_]){}(?![A-Za-z0-9_])"
    return any(re.search(boundary.format(re.escape(token)), prompt) for token in (tool, ref))


def test_the_refused_set_includes_the_thread_tools_the_prompt_used_to_call(
    tmp_path: Path,
) -> None:
    """Guard against a vacuous test: the derived set must contain the two thread tools."""
    refused = _refused_in_review_session(tmp_path)
    assert {"reply_to_review_comment", "resolve_review_thread"} <= refused


@pytest.mark.parametrize("agent_id", ["claude", "opencode"])
def test_incremental_review_names_no_tool_the_review_session_refuses(
    tmp_path: Path, agent_id: AgentId
) -> None:
    refused = _refused_in_review_session(tmp_path)
    prompt = _prompt("IncrementalReview", agent_id)

    named = sorted(tool for tool in refused if _names(prompt, tool, agent_id))

    assert named == [], f"IncrementalReview tells the agent to use refused tools: {named}"


def test_incremental_review_says_the_run_retires_addressed_threads_itself() -> None:
    prompt = _prompt("IncrementalReview", "claude")

    assert "the run retires addressed threads itself" in prompt


def test_mergecraft_originated_matches_the_expected_publisher_rule() -> None:
    """Authorship is marker AND an expected publisher; the old bot-login test is gone."""
    prompt = _prompt("IncrementalReview", "claude")

    assert "author=mergecraft[bot]" not in prompt
    assert "expected" in prompt.lower() or "publishes as" in prompt.lower()
    assert "github-actions[bot]" in prompt
