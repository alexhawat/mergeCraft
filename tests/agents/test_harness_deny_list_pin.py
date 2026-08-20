"""#285 / D13: harness deny-list names must match documented CLI MCP names.

``format_mcp_tool_ref`` is the in-repo spelling. The fixture
``tests/agents/fixtures/harness_mcp_cli_names.json`` records the CLI name each
harness documents for mergeCraft MCP tools.

Gemini ``excludeTools`` and Codex subagent instructions still disagree with
that spelling (bare names / omitted ``push_branch``). Those two pins stay
xfail until a later batch may edit ``gemini.py`` / ``codex.py`` (D6 forbids
them in Batch M).

Do not spawn a live provider CLI. Do not edit ``tests/agents/test_verifier.py``.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import get_args

import pytest
from tests.agents.conftest import make_agent_run_context
from tests.agents.test_harness_render import (
    _DEFAULT_MODELS_YAML,
    _load_registry,
    _stub_slug_runnability,
    _tool_ctx,
    _write_config,
)

from mergecraft.agents.gates import subagent_denied_tool_names
from mergecraft.types import REVIEWER_AGENT_NAME, AgentId, format_mcp_tool_ref

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "harness_mcp_cli_names.json"
_XFAIL_GEMINI_DRIVER = pytest.mark.xfail(
    reason=(
        "D6 Batch M: gemini.py excludeTools still stores bare tool names; "
        "do not edit the driver here"
    ),
    strict=False,
)
_XFAIL_CODEX_DRIVER = pytest.mark.xfail(
    reason=(
        "D6 Batch M: codex.py subagent instructions omit mergecraft_push_branch; "
        "do not edit the driver here"
    ),
    strict=False,
)


def test_harness_mcp_cli_name_fixture_exists() -> None:
    """D13: a checked-in fixture records the CLI name for ``push_branch``."""
    assert _FIXTURE.is_file(), (
        "W8 must add tests/agents/fixtures/harness_mcp_cli_names.json "
        "mapping each AgentId to the documented CLI MCP tool name"
    )


@pytest.mark.parametrize("agent_id", get_args(AgentId))
def test_format_mcp_tool_ref_matches_documented_cli_name(agent_id: AgentId) -> None:
    """Rendered deny-list spelling equals the documented CLI name fixture."""
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    expected = payload[agent_id]["push_branch"]
    assert format_mcp_tool_ref(agent_id, "push_branch") == expected


def test_claude_disallowed_tools_use_documented_push_branch_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.agents.harness_render import default_subagent_selection, render_agents

    _stub_slug_runnability(monkeypatch)
    _write_config(tmp_path, _DEFAULT_MODELS_YAML)
    ctx = _tool_ctx(tmp_path)
    result = render_agents(
        _load_registry(tmp_path),
        selected=default_subagent_selection(_load_registry(tmp_path)),
        harness="claude",
        ctx=ctx,
    )
    agents = json.loads(result.payload)
    documented = json.loads(_FIXTURE.read_text(encoding="utf-8"))["claude"]["push_branch"]
    disallowed = agents[REVIEWER_AGENT_NAME]["disallowedTools"]
    assert format_mcp_tool_ref("claude", "push_branch") in disallowed
    assert documented in disallowed
    assert "push_branch" in subagent_denied_tool_names(ctx)


def test_opencode_permission_deny_uses_documented_push_branch_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.agents.harness_render import default_subagent_selection, render_agents

    _stub_slug_runnability(monkeypatch)
    _write_config(tmp_path, _DEFAULT_MODELS_YAML)
    ctx = _tool_ctx(tmp_path)
    result = render_agents(
        _load_registry(tmp_path),
        selected=default_subagent_selection(_load_registry(tmp_path)),
        harness="opencode",
        ctx=ctx,
    )
    permission = result.payload["agent"][REVIEWER_AGENT_NAME]["permission"]
    documented = json.loads(_FIXTURE.read_text(encoding="utf-8"))["opencode"]["push_branch"]
    assert permission[format_mcp_tool_ref("opencode", "push_branch")] == "deny"
    assert permission[documented] == "deny"


@_XFAIL_GEMINI_DRIVER
def test_gemini_exclude_tools_uses_documented_push_branch_name(tmp_path: Path) -> None:
    from mergecraft.agents import gemini
    from mergecraft.types import MERGECRAFT_MCP_NAME

    ctx = replace(
        make_agent_run_context(tmp_path, resolved_model=None),
        subagent_denied_tools=("push_branch",),
    )
    config_path = Path(gemini.write_mcp_config(ctx))
    settings = json.loads(config_path.read_text(encoding="utf-8"))
    excluded = settings["mcpServers"][MERGECRAFT_MCP_NAME]["excludeTools"]
    documented = json.loads(_FIXTURE.read_text(encoding="utf-8"))["gemini"]["push_branch"]
    assert format_mcp_tool_ref("gemini", "push_branch") in excluded
    assert documented in excluded


@_XFAIL_CODEX_DRIVER
def test_codex_subagent_instructions_use_documented_push_branch_name() -> None:
    from mergecraft.agents import codex

    documented = json.loads(_FIXTURE.read_text(encoding="utf-8"))["codex"]["push_branch"]
    instructions = codex._build_subagent_instructions()
    preamble = codex._codex_mcp_tool_preamble()
    blob = f"{preamble}\n{instructions}"
    assert format_mcp_tool_ref("codex", "push_branch") in blob
    assert documented in blob
