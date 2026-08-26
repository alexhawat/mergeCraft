"""Lane A AP1.4 — OpenCode review-mode permission narrowing (MCB-06 / D4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mergecraft.agents.opencode import build_security_config
from mergecraft.agents.shared import AgentRunContext
from mergecraft.mcp.tool_state import init_tool_state

pytestmark = pytest.mark.xfail(
    reason="green after AP5: review-mode permission block in opencode.py",
    strict=False,
)


def _ctx(tmp_path: Path) -> AgentRunContext:
    return AgentRunContext(
        payload={"shell": "restricted", "push": "restricted"},
        mcp_server_url="http://127.0.0.1:0/mcp",
        tmpdir=str(tmp_path),
        subagent_denied_tools=(),
        instructions="review",
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_auth_token="token",
    )


def _permissions(tmp_path: Path) -> dict[str, object]:
    raw = build_security_config(_ctx(tmp_path), "anthropic/claude-sonnet")
    config = json.loads(raw)
    perms = config.get("permission")
    assert isinstance(perms, dict)
    return perms


def test_review_mode_denies_webfetch(tmp_path: Path) -> None:
    assert _permissions(tmp_path).get("webfetch") == "deny"


def test_review_mode_denies_external_directory(tmp_path: Path) -> None:
    assert _permissions(tmp_path).get("external_directory") == "deny"


def test_review_mode_denies_edit(tmp_path: Path) -> None:
    assert _permissions(tmp_path).get("edit") == "deny"


def test_review_mode_read_is_allowlisted_to_the_checkout(tmp_path: Path) -> None:
    read = _permissions(tmp_path).get("read")
    assert read != {"*": "allow"}
    assert isinstance(read, dict)
    assert any(str(tmp_path) in str(v) or v == "allow" for v in read.values())


def test_bash_stays_denied(tmp_path: Path) -> None:
    assert _permissions(tmp_path).get("bash") == "deny"
