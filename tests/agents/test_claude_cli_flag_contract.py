"""The claude CLI refuses ``--print --output-format=stream-json`` without ``--verbose``.

Reproduced against claude-code 2.1.251::

    $ claude --print --output-format stream-json
    Error: When using --print, --output-format=stream-json requires --verbose

The CLI exits 1 before emitting a single event, so the driver saw an empty
stream and the run read as "produced no events". The flag had never been
passed, which means the Claude backstop had never worked; run 33260176539
(PR #562) is the first one to say so out loud, because the zero-event
diagnostics landed first and surfaced the stderr.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from mergecraft.agents.claude import _run_claude_once
from mergecraft.agents.shared import AgentRunContext, ResolvedInstructions
from mergecraft.mcp.context import PayloadEvent, ResolvedPayload
from mergecraft.mcp.tool_state import init_tool_state

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _run_ctx(tmp_path: Path) -> AgentRunContext:
    return AgentRunContext(
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request")),
        mcp_server_url="http://127.0.0.1:0/mcp",
        tmpdir=str(tmp_path),
        subagent_denied_tools=(),
        instructions=ResolvedInstructions(user="review this diff"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        resolved_model="anthropic/claude-sonnet-5",
    )


class _EmptyProcess:
    def __init__(self) -> None:
        self.stdout = iter(())
        self.stderr = _Reader("")
        self.pid = 4242

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def poll(self) -> int:
        return 0

    def kill(self) -> None:  # pragma: no cover - not reached
        return None


class _Reader:
    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text


def _noop_ctx(*_a: Any, **_k: Any) -> Any:
    from contextlib import nullcontext

    return nullcontext()


def _captured_argv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Run the driver against a stub CLI and return the argv it actually built."""
    module = importlib.import_module("mergecraft.agents.claude")
    seen: list[list[str]] = []

    def _spawn(cmd: list[str], **_k: Any) -> _EmptyProcess:
        seen.append(list(cmd))
        return _EmptyProcess()

    monkeypatch.setattr(module, "spawn_agent_cli", _spawn)
    monkeypatch.setattr(module, "track_process_group", _noop_ctx)
    monkeypatch.setattr(module, "wait_or_kill_process_group", lambda proc, timeout: proc.wait())

    _run_claude_once(
        cli="/usr/bin/claude",
        prompt="review this diff",
        ctx=_run_ctx(tmp_path),
        mcp_config=str(tmp_path / "mcp.json"),
    )
    assert seen, "driver never spawned the CLI"
    return seen[0]


def test_stream_json_invocation_passes_verbose(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without this flag the CLI exits 1 and the backstop is dead on arrival."""
    argv = _captured_argv(tmp_path, monkeypatch)

    assert "--print" in argv
    assert "stream-json" in argv
    assert "--verbose" in argv, (
        "claude refuses --print with --output-format=stream-json unless --verbose "
        f"is present; argv was {argv!r}"
    )


def test_output_format_is_still_stream_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--verbose must be added beside stream-json, not instead of it."""
    argv = _captured_argv(tmp_path, monkeypatch)

    assert argv[argv.index("--output-format") + 1] == "stream-json"


def test_verbose_never_ships_without_the_flags_that_require_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The three flags are one contract: whenever the pair appears, so does --verbose."""
    argv = _captured_argv(tmp_path, monkeypatch)

    requires_verbose = "--print" in argv and "stream-json" in argv
    assert requires_verbose is ("--verbose" in argv)
