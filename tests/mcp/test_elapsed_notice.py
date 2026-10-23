"""⏱ elapsed notice on orchestrator ``tools/call`` results.

The review prompt says "by about minute N, stop exploring", but the agent has no
clock. Once a run passes 60% of its agent deadline, the orchestrator MCP route
appends a separate text part with minutes used and left; at 80% the wording
switches to "submit". ``content[0]`` stays the tool's own payload, and the
trajectory record and trace keep the un-noticed result.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.server import MCP_ENDPOINT, create_mcp_app
from mergecraft.mcp.shared import ToolClass, ToolResult, ToolSpec
from mergecraft.mcp.tool_call import with_elapsed_notice
from mergecraft.mcp.tool_state import ToolState, init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.modes._time_budget import (
    STOP_EXPLORING_FRACTION,
    SUBMIT_FRACTION,
    elapsed_notice,
    render_time_budget,
)
from mergecraft.utils.github import GitHubClient

_DEADLINE_S = 25 * 60.0
_PAYLOAD = {"ok": True, "items": [1, 2]}


def _state(tmp_path: Path, *, started: float | None, deadline_s: float | None) -> ToolState:
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    state.agent_started_monotonic = started
    state.agent_deadline_s = deadline_s
    return state


def _rpc() -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(_PAYLOAD)}]}


def _at(elapsed_s: float) -> float:
    """A clock reading ``elapsed_s`` after a dispatch at monotonic ``1000.0``."""
    return 1000.0 + elapsed_s


# ── wording ──────────────────────────────────────────────────────────────


def test_no_notice_below_the_stop_exploring_checkpoint() -> None:
    assert elapsed_notice(0, _DEADLINE_S) is None
    assert elapsed_notice(_DEADLINE_S * STOP_EXPLORING_FRACTION - 1, _DEADLINE_S) is None


def test_stop_exploring_notice_between_60_and_80_percent() -> None:
    assert elapsed_notice(16 * 60, _DEADLINE_S) == (
        "⏱ 16 of 25 min used, about 9 left: "
        "stop exploring and move to verification and drafting findings."
    )


def test_submit_notice_at_or_past_80_percent() -> None:
    assert elapsed_notice(_DEADLINE_S * SUBMIT_FRACTION, _DEADLINE_S) == (
        "⏱ 20 of 25 min used, about 5 left: submit the verdict now with what you have."
    )
    assert elapsed_notice(21 * 60 + 30, _DEADLINE_S) == (
        "⏱ 21 of 25 min used, about 4 left: submit the verdict now with what you have."
    )


def test_notice_never_reports_more_used_than_the_budget() -> None:
    notice = elapsed_notice(_DEADLINE_S + 120, _DEADLINE_S)
    assert notice is not None
    assert notice.startswith("⏱ 25 of 25 min used, about 0 left: submit")


def test_prompt_and_notice_share_the_checkpoints() -> None:
    """The ${TIME_BUDGET} line and the live notice read the same fractions."""
    rendered = render_time_budget(25)
    assert f"~{STOP_EXPLORING_FRACTION:.0%} of it" in rendered
    assert f"~{SUBMIT_FRACTION:.0%}" in rendered
    assert "tool results carry a ⏱ line" in rendered


# ── result shaping ───────────────────────────────────────────────────────


def test_result_unchanged_below_60_percent(tmp_path: Path) -> None:
    state = _state(tmp_path, started=1000.0, deadline_s=_DEADLINE_S)
    rpc = _rpc()
    assert with_elapsed_notice(rpc, state, now=lambda: _at(10 * 60)) is rpc


@pytest.mark.parametrize(
    ("elapsed_min", "expected_tail"),
    [
        (16, "stop exploring and move to verification and drafting findings."),
        (21, "submit the verdict now with what you have."),
    ],
)
def test_notice_is_a_trailing_text_part(
    tmp_path: Path, elapsed_min: int, expected_tail: str
) -> None:
    state = _state(tmp_path, started=1000.0, deadline_s=_DEADLINE_S)
    rpc = _rpc()
    out = with_elapsed_notice(rpc, state, now=lambda: _at(elapsed_min * 60))
    assert len(out["content"]) == 2
    assert json.loads(out["content"][0]["text"]) == _PAYLOAD
    assert out["content"][1]["type"] == "text"
    assert out["content"][1]["text"].startswith(f"⏱ {elapsed_min} of 25 min used")
    assert out["content"][1]["text"].endswith(expected_tail)
    # The input is untouched: the trajectory and trace hold this object.
    assert len(rpc["content"]) == 1


def test_no_notice_without_a_deadline(tmp_path: Path) -> None:
    state = _state(tmp_path, started=None, deadline_s=None)
    rpc = _rpc()
    assert with_elapsed_notice(rpc, state, now=lambda: _at(10_000)) is rpc


def test_no_notice_on_error_results(tmp_path: Path) -> None:
    state = _state(tmp_path, started=1000.0, deadline_s=_DEADLINE_S)
    rpc = {**_rpc(), "isError": True}
    assert with_elapsed_notice(rpc, state, now=lambda: _at(24 * 60)) is rpc


# ── end to end through the HTTP routes ───────────────────────────────────


class _Echo:
    async def execute(self, arguments: Mapping[str, Any]) -> ToolResult:
        return ToolResult(content=[{"type": "text", "text": json.dumps(_PAYLOAD)}])


def _client(tmp_path: Path, state: ToolState) -> TestClient:
    spec = ToolSpec(
        name="probe",
        description="Echo tool.",
        input_schema={"type": "object", "properties": {}},
        execute=_Echo().execute,
        tool_class=ToolClass.ANALYSIS,
    )
    ctx = ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request")),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
        trust_tier="trusted",
    )
    return TestClient(create_mcp_app([spec], ctx, role_tools={"reviewer": [spec]}))


def _call(client: TestClient, path: str) -> dict[str, Any]:
    response = client.post(
        path,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "probe", "arguments": {}},
        },
    )
    assert response.status_code == 200
    result: dict[str, Any] = response.json()["result"]
    return result


def test_orchestrator_route_appends_the_notice_and_trajectory_does_not(tmp_path: Path) -> None:
    # Dispatched 21 minutes ago against a 25-minute deadline — set via the
    # recorded start time, so the test never sleeps.
    state = _state(tmp_path, started=time.monotonic() - 21 * 60, deadline_s=_DEADLINE_S)
    client = _client(tmp_path, state)

    result = _call(client, MCP_ENDPOINT)

    assert json.loads(result["content"][0]["text"]) == _PAYLOAD
    assert result["content"][1]["text"].startswith("⏱ 21 of 25 min used, about 4 left: submit")
    assert len(state.tool_calls) == 1
    recorded = json.dumps(state.tool_calls, default=repr)
    assert "⏱" not in recorded


def test_subagent_route_gets_no_notice(tmp_path: Path) -> None:
    state = _state(tmp_path, started=time.monotonic() - 21 * 60, deadline_s=_DEADLINE_S)
    client = _client(tmp_path, state)

    result = _call(client, f"{MCP_ENDPOINT}/reviewer")

    assert len(result["content"]) == 1


def test_orchestrator_route_without_a_deadline_is_unchanged(tmp_path: Path) -> None:
    state = _state(tmp_path, started=None, deadline_s=None)
    client = _client(tmp_path, state)

    result = _call(client, MCP_ENDPOINT)

    assert result["content"] == [{"type": "text", "text": json.dumps(_PAYLOAD)}]
