"""#282 / D14: Action dispatch must wire role MCP URLs, not orchestrator ``/mcp``.

``start_mcp_http_server`` still returns ``http://127.0.0.1:<port>/mcp``
(``mcp/server.py``). ``_prepare_agent_dispatch`` copies that URL onto
``AgentRunContext.mcp_server_url``, so the primary reviewer session is the
orchestrator surface. W12 rewrites (or role-maps) that URL per D14:

- reviewer / judge / classifier → ``/mcp/reviewer``
- verifier → ``/mcp/verifier``
- orchestrator (if any) → ``/mcp``

``x-mergecraft-agent-id`` is tracing-only and must not be the routing key.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from tests.agents.conftest import make_agent_run_context
from tests.support.run_main_harness import FakeAgent, run_main_for_test

from mergecraft.agents.shared import AgentResult
from mergecraft.mcp.server import MCP_ENDPOINT, MCP_REVIEWER_ENDPOINT, MCP_VERIFIER_ENDPOINT

if TYPE_CHECKING:
    import pytest


def _assert_role_path(url: str, expected_path: str) -> None:
    parsed = urlparse(url)
    assert parsed.scheme == "http", url
    assert parsed.hostname == "127.0.0.1", url
    assert parsed.path == expected_path, url
    assert not parsed.path.endswith(MCP_ENDPOINT) or expected_path == MCP_ENDPOINT, url


async def test_primary_reviewer_dispatch_url_ends_with_reviewer_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """W11.1: primary reviewer ``AgentRunContext.mcp_server_url`` is ``/mcp/reviewer``."""
    captured: list[str] = []

    class _RecordingAgent(FakeAgent):
        async def run(self, ctx: Any) -> AgentResult:
            captured.append(ctx.mcp_server_url)
            return await super().run(ctx)

    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        agent=_RecordingAgent(),
        event_name="workflow_dispatch",
        event_payload={"action": "workflow_dispatch"},
    )
    assert rec.result is not None
    assert rec.result.success, f"run failed: {rec.result}"
    assert captured, "agent ran without an MCP URL"
    url = captured[0]
    _assert_role_path(url, MCP_REVIEWER_ENDPOINT)
    assert url.endswith("/mcp/reviewer")
    assert not url.endswith("/mcp")


def test_verifier_mcp_entry_ends_with_verifier_endpoint(tmp_path: Path) -> None:
    """W11.1 / W12: ``write_mcp_config`` always writes a /mcp/verifier entry for subagents.

    ``write_mcp_config`` runs once in the orchestrator (agent_id="claude", not in a
    verifier span). It always writes both server entries so verifier subagents
    inherit the correct /mcp/verifier URL without a second config write:
      - ``MERGECRAFT_MCP_NAME``         → /mcp/reviewer  (primary reviewer surface)
      - ``MERGECRAFT_VERIFIER_MCP_NAME`` → /mcp/verifier  (verifier subagent surface)
    No ``agent_run_span`` fake is needed — this tests the production call path.
    """
    from mergecraft.agents.claude import write_mcp_config
    from mergecraft.types import MERGECRAFT_MCP_NAME, MERGECRAFT_VERIFIER_MCP_NAME

    ctx = make_agent_run_context(tmp_path, resolved_model="anthropic/claude-sonnet")
    ctx.mcp_server_url = "http://127.0.0.1:3764/mcp"

    config_path = Path(write_mcp_config(ctx))  # no fake span — production path

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    # Primary reviewer entry always points to /mcp/reviewer.
    reviewer_url = payload["mcpServers"][MERGECRAFT_MCP_NAME]["url"]
    _assert_role_path(str(reviewer_url), MCP_REVIEWER_ENDPOINT)
    assert str(reviewer_url).endswith("/mcp/reviewer")
    assert not str(reviewer_url).endswith("/mcp")
    # Verifier subagent entry always points to /mcp/verifier.
    verifier_url = payload["mcpServers"][MERGECRAFT_VERIFIER_MCP_NAME]["url"]
    _assert_role_path(str(verifier_url), MCP_VERIFIER_ENDPOINT)
    assert str(verifier_url).endswith("/mcp/verifier")
    assert not str(verifier_url).endswith("/mcp")
