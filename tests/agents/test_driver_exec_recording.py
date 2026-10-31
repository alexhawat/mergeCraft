"""Each driver records its native exec calls on the run's trajectory (#858).

The shared choke is pinned in ``tests/evidence/test_driver_exec_recording.py``.
These tests drive the three drivers' real stream consumers with a fixture stream
that runs a command, sees it fail, and runs it again. They assert on the run's
``ToolState`` — the thing the evidence packet is built from — not on a helper, so
a driver that parses the event but never calls the recorder stays red.

Recording is evidence only: every test also asserts the review result is the same
as it would have been without a recorder.
"""

from __future__ import annotations

import importlib
import json
from typing import TYPE_CHECKING, Any

from tests.agents.conftest import make_agent_run_context

from mergecraft.agents._stream_consumer import StreamSpanAccumulator
from mergecraft.evidence.trajectory import build_trajectory_record

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from mergecraft.agents.shared import AgentRunContext


def _lines(*events: dict[str, Any]) -> str:
    return "".join(json.dumps(event) + "\n" for event in events)


def _shell_rows(ctx: AgentRunContext) -> list[Any]:
    return [call for call in ctx.tool_state.tool_calls if call.tool == "shell"]


class _Text:
    def __init__(self, text: str = "") -> None:
        self._text = text

    def read(self) -> str:
        return self._text

    def __iter__(self) -> Any:
        return iter(self._text.splitlines(keepends=True))

    def readline(self) -> str:
        return ""


class _Proc:
    def __init__(self, stdout: str, returncode: int = 0) -> None:
        self.stdout = stdout.splitlines(keepends=True)
        self.stderr: Any = _Text()
        self.returncode = returncode
        self.pid = 777_001

    def poll(self) -> int:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode


class _NoopGroup:
    def __init__(self, *_a: object, **_k: object) -> None: ...

    def __enter__(self) -> None: ...

    def __exit__(self, *_a: object) -> bool:
        return False


def _patch_process(monkeypatch: pytest.MonkeyPatch, module: Any, proc: _Proc) -> None:
    monkeypatch.setattr(module, "spawn_agent_cli", lambda *_a, **_k: proc)
    monkeypatch.setattr(module, "track_process_group", _NoopGroup)
    monkeypatch.setattr(module, "wait_or_kill_process_group", lambda p, timeout: p.wait())


# ── Codex ────────────────────────────────────────────────────────────────────


def _codex_exec(command: str, exit_code: int, output: str, *, status: str = "completed") -> dict:
    return {
        "type": "item.completed",
        "item": {
            "id": f"item_{abs(hash((command, exit_code))) % 10_000}",
            "type": "command_execution",
            "command": command,
            "aggregated_output": output,
            "exit_code": exit_code,
            "status": status,
        },
    }


def _run_codex(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *events: dict[str, Any]) -> tuple:
    from mergecraft.agents import codex as codex_module

    ctx = make_agent_run_context(tmp_path, resolved_model=None)
    _patch_process(monkeypatch, codex_module, _Proc(_lines(*events)))
    result = codex_module._run_codex_once(
        cli="/usr/bin/codex", prompt="", ctx=ctx, mcp_config="unused"
    )
    return ctx, result


def test_codex_records_a_failing_then_passing_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, result = _run_codex(
        tmp_path,
        monkeypatch,
        _codex_exec("pytest -q", 1, "1 failed"),
        _codex_exec("pytest -q", 0, "1 passed"),
        {"type": "message.completed", "message": {"content": "done"}},
    )

    rows = _shell_rows(ctx)
    assert [row.outcome_ok for row in rows] == [False, True]
    assert rows[0].signature == rows[1].signature
    assert build_trajectory_record(ctx.tool_state).unresolved_errors == []
    assert result.success is True
    assert result.output == "done"


def test_codex_records_an_environment_failure_with_its_class(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _ = _run_codex(
        tmp_path,
        monkeypatch,
        _codex_exec("git fetch origin", 128, "bwrap: No permissions to create a new namespace"),
    )

    (row,) = _shell_rows(ctx)
    assert row.ok is False
    assert row.failure_class == "environment"


def test_codex_records_a_declined_command_as_a_policy_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    event = _codex_exec("rm -rf build", 0, "", status="declined")
    del event["item"]["exit_code"]
    ctx, _ = _run_codex(tmp_path, monkeypatch, event)

    (row,) = _shell_rows(ctx)
    assert row.ok is False
    assert row.failure_class == "policy"


def test_codex_recording_failure_never_changes_the_review_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.evidence import trajectory

    def _explode(*_a: object, **_k: object) -> None:
        raise RuntimeError("recorder bug")

    monkeypatch.setattr(trajectory, "record_tool_call", _explode)
    ctx, result = _run_codex(
        tmp_path,
        monkeypatch,
        _codex_exec("pytest -q", 1, "1 failed"),
        {"type": "message.completed", "message": {"content": "still reviewed"}},
    )

    assert result.success is True
    assert result.output == "still reviewed"
    assert _shell_rows(ctx) == []


# ── Claude ───────────────────────────────────────────────────────────────────


def _claude_bash_use(tool_id: str, command: str) -> dict[str, Any]:
    return {
        "type": "content_block_start",
        "index": 0,
        "content_block": {
            "type": "tool_use",
            "id": tool_id,
            "name": "Bash",
            "input": {"command": command},
        },
    }


def _claude_tool_result(tool_id: str, content: str, *, is_error: bool) -> dict[str, Any]:
    return {"type": "tool_result", "tool_use_id": tool_id, "content": content, "is_error": is_error}


def _drive_claude(events: list[dict[str, Any]], ctx: AgentRunContext) -> None:
    from mergecraft.agents.claude import _claude_stream_event_handler

    handler, close_all = _claude_stream_event_handler(
        tracer=None,
        parent_span_id=None,
        model_id="claude-sonnet-5",
        tool_state=ctx.tool_state,
    )
    accumulator = StreamSpanAccumulator(agent_name="claude")
    for event in events:
        handler(accumulator, event)
    close_all()


def test_claude_records_a_failing_then_passing_bash_command(tmp_path: Path) -> None:
    ctx = make_agent_run_context(tmp_path, resolved_model=None)

    _drive_claude(
        [
            _claude_bash_use("t1", "pytest -q"),
            _claude_tool_result("t1", "Exit code 1\n1 failed", is_error=True),
            _claude_bash_use("t2", "pytest -q"),
            _claude_tool_result("t2", "1 passed", is_error=False),
        ],
        ctx,
    )

    rows = _shell_rows(ctx)
    assert [row.outcome_ok for row in rows] == [False, True]
    assert rows[0].signature == rows[1].signature
    assert build_trajectory_record(ctx.tool_state).unresolved_errors == []


def test_claude_records_the_stream_json_user_message_shape(tmp_path: Path) -> None:
    """Real ``--output-format stream-json`` carries tool_use / tool_result in messages."""
    ctx = make_agent_run_context(tmp_path, resolved_model=None)

    _drive_claude(
        [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "t9",
                            "name": "Bash",
                            "input": {"command": "make lint"},
                        }
                    ]
                },
            },
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "t9",
                            "content": "Exit code 2\nE501",
                            "is_error": True,
                        }
                    ]
                },
            },
        ],
        ctx,
    )

    (row,) = _shell_rows(ctx)
    assert row.command == "make lint"
    assert row.outcome_ok is False


def test_claude_ignores_non_exec_tools_and_unmatched_results(tmp_path: Path) -> None:
    ctx = make_agent_run_context(tmp_path, resolved_model=None)

    _drive_claude(
        [
            {
                "type": "content_block_start",
                "content_block": {
                    "type": "tool_use",
                    "id": "r1",
                    "name": "Read",
                    "input": {"file_path": "src/a.py"},
                },
            },
            _claude_tool_result("r1", "text", is_error=False),
            _claude_tool_result("never-started", "orphan", is_error=True),
        ],
        ctx,
    )

    assert _shell_rows(ctx) == []


def test_claude_environment_failure_carries_its_class(tmp_path: Path) -> None:
    ctx = make_agent_run_context(tmp_path, resolved_model=None)

    _drive_claude(
        [
            _claude_bash_use("t1", "git push"),
            _claude_tool_result(
                "t1", "Exit code 128\nfatal: Authentication failed for 'x'", is_error=True
            ),
        ],
        ctx,
    )

    (row,) = _shell_rows(ctx)
    assert row.ok is False
    assert row.failure_class == "environment"


def test_claude_full_run_wires_the_recorder_into_the_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The seam: ``_run_claude_once`` hands the run's state to its stream handler."""
    claude_module = importlib.import_module("mergecraft.agents.claude")
    ctx = make_agent_run_context(tmp_path, resolved_model="anthropic/claude-sonnet-5")
    stream = _lines(
        _claude_bash_use("t1", "pytest -q"),
        _claude_tool_result("t1", "Exit code 1\n1 failed", is_error=True),
        {"type": "result", "result": "done", "usage": {}},
    )
    _patch_process(monkeypatch, claude_module, _Proc(stream))

    result = claude_module._run_claude_once(
        cli="/usr/bin/claude", prompt="review", ctx=ctx, mcp_config=str(tmp_path / "mcp.json")
    )

    assert result.success is True
    (row,) = _shell_rows(ctx)
    assert row.outcome_ok is False


# ── OpenCode ─────────────────────────────────────────────────────────────────


def _opencode_bash(command: str, *, exit_code: int | None, status: str, output: str) -> dict:
    state: dict[str, Any] = {
        "status": status,
        "input": {"command": command},
        "output": output,
        "metadata": {} if exit_code is None else {"exit": exit_code},
    }
    return {
        "type": "tool_use",
        "sessionID": "ses_1",
        "part": {"type": "tool", "tool": "bash", "callID": "c1", "state": state},
    }


def test_opencode_cli_stream_records_a_failing_then_passing_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.agents import opencode as oc

    ctx = make_agent_run_context(tmp_path, resolved_model=None)
    stream = _lines(
        _opencode_bash("pytest -q", exit_code=1, status="completed", output="1 failed"),
        _opencode_bash("pytest -q", exit_code=0, status="completed", output="1 passed"),
        {"type": "text", "sessionID": "ses_1", "part": {"text": "done"}},
    )
    monkeypatch.setattr(oc, "spawn_agent_cli", lambda *_a, **_k: _Proc(stream))
    monkeypatch.setattr(oc, "track_process_group", _NoopGroup)
    monkeypatch.setattr(oc, "wait_or_kill_process_group", lambda p, timeout: p.wait())

    result = oc._run_opencode_cli_streaming(cmd=["opencode"], ctx=ctx, env={})

    assert result.success is True
    assert [row.outcome_ok for row in _shell_rows(ctx)] == [False, True]
    assert build_trajectory_record(ctx.tool_state).unresolved_errors == []


def test_opencode_cli_stream_records_a_tool_error_without_an_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.agents import opencode as oc

    ctx = make_agent_run_context(tmp_path, resolved_model=None)
    stream = _lines(
        _opencode_bash("cargo test", exit_code=None, status="error", output="spawn failed"),
    )
    monkeypatch.setattr(oc, "spawn_agent_cli", lambda *_a, **_k: _Proc(stream))
    monkeypatch.setattr(oc, "track_process_group", _NoopGroup)
    monkeypatch.setattr(oc, "wait_or_kill_process_group", lambda p, timeout: p.wait())

    oc._run_opencode_cli_streaming(cmd=["opencode"], ctx=ctx, env={})

    (row,) = _shell_rows(ctx)
    assert row.outcome_ok is False


def test_opencode_session_handler_ignores_non_bash_tools(tmp_path: Path) -> None:
    from mergecraft.agents import opencode as oc

    ctx = make_agent_run_context(tmp_path, resolved_model=None)
    handle = oc._session_event_handler({}, tool_state=ctx.tool_state)
    accumulator = StreamSpanAccumulator(agent_name="opencode")

    handle(
        accumulator,
        {
            "type": "tool_use",
            "part": {"tool": "read", "state": {"status": "completed", "input": {"filePath": "a"}}},
        },
    )

    assert _shell_rows(ctx) == []


async def test_opencode_http_turn_records_the_bash_parts_of_the_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx

    from mergecraft.agents import opencode as oc

    ctx = make_agent_run_context(tmp_path, resolved_model=None)
    body = {
        "info": {},
        "text": "done",
        "parts": [
            {"type": "text", "text": "running"},
            {
                "type": "tool",
                "tool": "bash",
                "state": {
                    "status": "completed",
                    "input": {"command": "make test"},
                    "output": "boom",
                    "metadata": {"exit": 2},
                },
            },
        ],
    }

    class _Resp:
        status_code = 200
        text = ""
        content = b"{}"

        def json(self) -> dict[str, Any]:
            return body

    class _Client:
        def __init__(self, *_a: object, **_k: object) -> None: ...

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *_a: object) -> bool:
            return False

        async def post(self, *_a: object, **_k: object) -> _Resp:
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    monkeypatch.setattr(oc, "instrument_httpx", lambda _client, tracer=None: None)

    result = await oc._prompt_session_http(
        base_url="http://127.0.0.1:1",
        session_id="s1",
        text="hi",
        model=None,
        tool_state=ctx.tool_state,
    )

    assert result.success is True
    (row,) = _shell_rows(ctx)
    assert row.command == "make test"
    assert row.outcome_ok is False
