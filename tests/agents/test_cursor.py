"""Contract tests for the Cursor Cloud agent harness (issue #13 / D9 Phase A)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from tests.agents.conftest import make_agent_run_context

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch


def _load_cursor_module():
    try:
        from mergecraft.agents import cursor

        return cursor
    except ImportError as exc:
        pytest.fail(f"mergecraft.agents.cursor not implemented: {exc}")


@pytest.mark.asyncio
async def test_cursor_harness_launches_cloud_agent_and_parses_agent_result(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Mocked Cursor Cloud API + ``CURSOR_API_KEY`` → ``AgentResult`` with dashboard URL."""
    cursor_module = _load_cursor_module()
    monkeypatch.setenv("CURSOR_API_KEY", "cursor-test-key")

    calls: list[tuple[str, dict[str, Any]]] = []

    class _FakeCloudClient:
        def __init__(self, *, api_key: str) -> None:
            calls.append(("init", {"api_key": api_key}))

        async def create_cloud_agent(self, **payload: object) -> dict[str, str]:
            calls.append(("create_cloud_agent", dict(payload)))
            return {"id": "run-123", "dashboard_url": "https://cursor.example/agents/run-123"}

        async def get_run(self, run_id: str) -> dict[str, object]:
            calls.append(("get_run", {"run_id": run_id}))
            return {
                "id": run_id,
                "status": "completed",
                "result": "cursor cloud review complete",
                "usage": {"input_tokens": 60, "output_tokens": 30},
            }

        async def list_artifacts(self, run_id: str) -> list[dict[str, str]]:
            calls.append(("list_artifacts", {"run_id": run_id}))
            return []

    monkeypatch.setattr(cursor_module, "CursorCloudClient", _FakeCloudClient)

    ctx = make_agent_run_context(tmp_path, resolved_model="cursor/cloud-agent")

    result = await cursor_module._run_cursor_once(ctx=ctx)

    assert any(call[0] == "create_cloud_agent" for call in calls)
    assert result.success is True
    assert result.output is not None
    assert "cursor cloud review complete" in result.output
    assert result.usage is not None
    assert result.usage.agent == "cursor"
    dashboard = result.metadata.get("dashboard_url") or result.metadata.get("dashboardUrl")
    assert dashboard is not None
    assert "run-123" in str(dashboard)


@pytest.mark.asyncio
async def test_cursor_timeout_cancels_created_run(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    from unittest.mock import AsyncMock

    cursor = _load_cursor_module()
    monkeypatch.setenv("CURSOR_API_KEY", "cursor-test-key")
    client = AsyncMock()
    client.create_cloud_agent.return_value = {"id": "run-123"}
    monkeypatch.setattr(cursor, "CursorCloudClient", lambda **_kwargs: client)
    monkeypatch.setattr(
        cursor, "_poll_run_to_terminal", AsyncMock(side_effect=TimeoutError("expired"))
    )
    ctx = make_agent_run_context(tmp_path, resolved_model="cursor/cloud-agent")
    result = await cursor._run_cursor_once(ctx=ctx)
    assert not result.success
    client.cancel_run.assert_awaited_once_with("run-123")
