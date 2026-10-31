"""#1073 — a refused tool call records ``ok=False, failure_class="refused"``.

A guard (read-only allowlist, path confinement, config-flag or mode guard)
stops the call *before it runs*. ``mcp/shared.py::execute`` converts every
exception into a tool error *result* so the agent can read the refusal — which
used to make ``mcp/rpc.py`` record ``ok=True, error=null`` on the trajectory.
The typed ``ToolRefusedError`` now tags the result, and the RPC layer records
the refusal honestly while the agent-visible wire shape is unchanged.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.server import MCP_ENDPOINT, create_mcp_app
from mergecraft.mcp.shared import (
    EMPTY_SCHEMA,
    ToolClass,
    ToolRefusedError,
    ToolResult,
    ToolSpec,
    execute,
    tool,
)
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

_REQ_ID = 41


async def _refusing_body(params: Mapping[str, Any]) -> ToolResult:
    raise ToolRefusedError(
        "invalid git subcommand: 'gc' — not available through this tool (read-only allowlist)"
    )


async def _failing_body(params: Mapping[str, Any]) -> ToolResult:
    raise ValueError("backend exploded")


async def test_execute_tags_a_typed_refusal_as_refused() -> None:
    """The typed refusal survives ``execute``'s error-result conversion."""
    handler = execute(_refusing_body, "git")

    result = await handler({})

    assert result.is_error is True
    assert result.refused is True
    assert "read-only allowlist" in result.content[0]["text"]


async def test_execute_does_not_tag_an_ordinary_tool_error() -> None:
    """A tool that fails *while running* is not a refusal — it stays untagged."""
    handler = execute(_failing_body, "git")

    result = await handler({})

    assert result.is_error is True
    assert result.refused is False


async def test_the_mutating_mode_guard_marks_its_refusals() -> None:
    """``guard_mutating_tool`` stops the call before the body — that is a refusal."""

    async def _body(params: Mapping[str, Any]) -> ToolResult:  # pragma: no cover
        raise AssertionError("the body must not run when the guard refuses")

    spec = tool(
        name="probe_mutation",
        description="mutating probe",
        input_schema=EMPTY_SCHEMA,
        execute=_body,
        tool_class=ToolClass.REPOSITORY_MUTATION,
        mutates=True,
    )

    result = await spec.execute({})

    assert result.is_error is True
    assert result.refused is True
    assert "review-only" in result.content[0]["text"]


def _ctx(tmp_path: Path) -> ToolContext:
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    return ToolContext(
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


def _refusing_app(
    ctx: ToolContext, body: Callable[[Mapping[str, Any]], Any]
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    spec = ToolSpec(
        name="git",
        description="refusing probe",
        input_schema=EMPTY_SCHEMA,
        execute=execute(body, "git"),
        tool_class=ToolClass.REPOSITORY_READ,
    )
    client = TestClient(create_mcp_app([spec], ctx))

    def _call(arguments: dict[str, Any]) -> dict[str, Any]:
        response = client.post(
            MCP_ENDPOINT,
            json={
                "jsonrpc": "2.0",
                "id": _REQ_ID,
                "method": "tools/call",
                "params": {"name": "git", "arguments": arguments},
            },
        )
        assert response.status_code == 200
        result: dict[str, Any] = response.json()
        return result

    return _call


def test_a_refusal_records_ok_false_with_the_refused_failure_class(tmp_path: Path) -> None:
    """End to end through the JSON-RPC door: the trajectory tells the truth."""
    ctx = _ctx(tmp_path)
    call = _refusing_app(ctx, _refusing_body)

    body = call({})

    # The agent-visible shape is unchanged: an ordinary tool error result.
    assert body["result"]["isError"] is True
    assert "read-only allowlist" in body["result"]["content"][0]["text"]
    calls = ctx.tool_state.tool_calls
    assert len(calls) == 1, calls
    row = calls[0]
    assert row.tool == "git"
    assert row.ok is False
    assert row.failure_class == "refused"
    assert row.error is not None
    assert "read-only allowlist" in row.error
    assert not row.error.startswith("Error: "), "the wire prefix is not the reason"
    assert row.outcome_ok is None, "a refused call never ran — there is no outcome"


def test_an_ordinary_tool_error_still_records_ok_true(tmp_path: Path) -> None:
    """Green guard: only refusals move; other tool errors keep today's record."""
    ctx = _ctx(tmp_path)
    call = _refusing_app(ctx, _failing_body)

    body = call({})

    assert body["result"]["isError"] is True
    calls = ctx.tool_state.tool_calls
    assert len(calls) == 1, calls
    assert calls[0].ok is True
    assert calls[0].failure_class == "unknown"
    assert calls[0].error is None


async def test_the_git_allowlist_refusal_is_tagged(tmp_path: Path) -> None:
    """A verb off the read-only allowlist is refused before git ever runs."""
    from mergecraft.mcp.git import git_tool

    result = await git_tool(_ctx(tmp_path)).execute({"command": "gc"})

    assert result.is_error is True
    assert result.refused is True
    assert "read-only allowlist" in result.content[0]["text"]


async def test_the_git_path_confinement_refusal_is_tagged(tmp_path: Path) -> None:
    """Path confinement is the same honest signal, not a phantom success."""
    from mergecraft.mcp.git import git_tool

    result = await git_tool(_ctx(tmp_path)).execute(
        {"command": "grep", "args": ["--", "/some/repo/dir"]}
    )

    assert result.is_error is True
    assert result.refused is True
