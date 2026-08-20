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
from typing import Any
from urllib.parse import urlparse

import pytest
from tests.agents.conftest import make_agent_run_context
from tests.support.run_main_harness import FakeAgent, run_main_for_test

from mergecraft.agents.shared import AgentResult
from mergecraft.mcp.server import MCP_ENDPOINT, MCP_REVIEWER_ENDPOINT, MCP_VERIFIER_ENDPOINT
from mergecraft.types import VERIFIER_AGENT_NAME

_XFAIL_W12 = pytest.mark.xfail(
    reason="green after W12: role MCP URL dispatch",
    strict=False,
)


def _assert_role_path(url: str, expected_path: str) -> None:
    parsed = urlparse(url)
    assert parsed.scheme == "http", url
    assert parsed.hostname == "127.0.0.1", url
    assert parsed.path == expected_path, url
    assert not parsed.path.endswith(MCP_ENDPOINT) or expected_path == MCP_ENDPOINT, url


@_XFAIL_W12
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


@_XFAIL_W12
def test_verifier_dispatch_url_ends_with_verifier_endpoint(tmp_path: Path) -> None:
    """W11.1: verifier harness MCP config is ``/mcp/verifier``, not orchestrator ``/mcp``.

    Codex/Claude ``write_mcp_config`` currently copies ``ctx.mcp_server_url``
    verbatim. W12 must hand the verifier the role path (rewrite inside
    ``write_mcp_config`` from the bound agent id, or a role map on the
    run context). ``x-mergecraft-agent-id`` is not the routing credential.
    """
    from mergecraft.agents.claude import write_mcp_config
    from mergecraft.tracing.signals import agent_run_span
    from mergecraft.types import MERGECRAFT_MCP_NAME

    ctx = make_agent_run_context(tmp_path, resolved_model="anthropic/claude-sonnet")
    ctx.mcp_server_url = "http://127.0.0.1:3764/mcp"

    with agent_run_span(None, agent_id=VERIFIER_AGENT_NAME, role="verifier"):
        config_path = Path(write_mcp_config(ctx))

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    url = payload["mcpServers"][MERGECRAFT_MCP_NAME]["url"]
    _assert_role_path(str(url), MCP_VERIFIER_ENDPOINT)
    assert str(url).endswith("/mcp/verifier")
    assert not str(url).endswith("/mcp")
