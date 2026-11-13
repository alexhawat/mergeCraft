"""#285 / D13: harness deny-list names must match documented CLI MCP names.

``format_mcp_tool_ref`` is the in-repo spelling. The fixture
``tests/agents/fixtures/harness_mcp_cli_names.json`` records the CLI name each
harness documents for mergeCraft MCP tools.

Every harness — Claude, OpenCode, Gemini and Codex — must render the documented
``create_pull_request_review`` MCP tool name in its deny surfaces. Gemini's ``excludeTools``
must carry ``mcp_mergecraft_create_pull_request_review`` (not the bare ``create_pull_request_review``), and
Codex's subagent instructions must name ``mergecraft_create_pull_request_review``. These pins
are plain failures, not xfails: a driver that drifts back to a bare spelling
must turn the suite red.

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


def test_harness_mcp_cli_name_fixture_exists() -> None:
    """D13: a checked-in fixture records the CLI name for ``create_pull_request_review``."""
    assert _FIXTURE.is_file(), (
        "W8 must add tests/agents/fixtures/harness_mcp_cli_names.json "
        "mapping each AgentId to the documented CLI MCP tool name"
    )


@pytest.mark.parametrize("agent_id", get_args(AgentId))
def test_format_mcp_tool_ref_matches_documented_cli_name(agent_id: AgentId) -> None:
    """Rendered deny-list spelling equals the documented CLI name fixture."""
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    expected = payload[agent_id]["create_pull_request_review"]
    assert format_mcp_tool_ref(agent_id, "create_pull_request_review") == expected


def test_claude_disallowed_tools_use_documented_create_pull_request_review_name(
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
    documented = json.loads(_FIXTURE.read_text(encoding="utf-8"))["claude"][
        "create_pull_request_review"
    ]
    disallowed = agents[REVIEWER_AGENT_NAME]["disallowedTools"]
    assert format_mcp_tool_ref("claude", "create_pull_request_review") in disallowed
    assert documented in disallowed
    assert "create_pull_request_review" in subagent_denied_tool_names(ctx)


def test_opencode_permission_deny_uses_documented_create_pull_request_review_name(
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
    documented = json.loads(_FIXTURE.read_text(encoding="utf-8"))["opencode"][
        "create_pull_request_review"
    ]
    assert permission[format_mcp_tool_ref("opencode", "create_pull_request_review")] == "deny"
    assert permission[documented] == "deny"


def test_gemini_exclude_tools_uses_documented_create_pull_request_review_name(
    tmp_path: Path,
) -> None:
    from mergecraft.agents import gemini
    from mergecraft.types import MERGECRAFT_MCP_NAME

    ctx = replace(
        make_agent_run_context(tmp_path, resolved_model=None),
        subagent_denied_tools=("create_pull_request_review",),
    )
    config_path = Path(gemini.write_mcp_config(ctx))
    settings = json.loads(config_path.read_text(encoding="utf-8"))
    excluded = settings["mcpServers"][MERGECRAFT_MCP_NAME]["excludeTools"]
    documented = json.loads(_FIXTURE.read_text(encoding="utf-8"))["gemini"][
        "create_pull_request_review"
    ]
    assert format_mcp_tool_ref("gemini", "create_pull_request_review") in excluded
    assert documented in excluded


def test_codex_subagent_instructions_use_documented_create_pull_request_review_name() -> None:
    from mergecraft.agents import codex

    documented = json.loads(_FIXTURE.read_text(encoding="utf-8"))["codex"][
        "create_pull_request_review"
    ]
    instructions = codex._build_subagent_instructions()
    preamble = codex._codex_mcp_tool_preamble()
    blob = f"{preamble}\n{instructions}"
    assert format_mcp_tool_ref("codex", "create_pull_request_review") in blob
    assert documented in blob
