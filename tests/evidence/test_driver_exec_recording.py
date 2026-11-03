"""Driver-native exec calls reach the trajectory with their real outcome (#858).

The trajectory only saw the MCP ``tools/call`` door. The Codex, Claude and
OpenCode drivers run shell commands natively, so a failing command never became a
row: 387 harvested packets held no ``shell`` rows and no ``outcome_ok`` at all,
which left four of the auditor's eight checks structurally unable to fire.

``record_driver_exec`` is the shared choke the drivers call. It records the
command as a ``shell`` row, stamps ``outcome_ok`` from the exit code and a
``failure_class`` from the typed signals the driver has, and **never** fails the
tool call it describes.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, ClassVar

import pytest

from mergecraft.evidence import trajectory
from mergecraft.evidence.trajectory import build_trajectory_record, record_tool_call
from mergecraft.evidence.trajectory_audit import audit_trajectory
from mergecraft.mcp.rpc import dispatch_mcp_rpc
from mergecraft.mcp.tool_state import init_tool_state
from tests.support.tool_context import make_tool_context

_CANARY = "sk-canary-driver-exec-0123456789abcdef0123456789"


def record_driver_exec(*args: Any, **kwargs: Any) -> Any:
    return trajectory.record_driver_exec(*args, **kwargs)


def classify_failure_at_execute(*args: Any, **kwargs: Any) -> Any:
    return trajectory.classify_failure_at_execute(*args, **kwargs)


def _state() -> Any:
    return init_tool_state(owner="acme", name="demo", dir="/tmp/demo")


def _rule_ids(state: Any) -> set[str]:
    return {f.rule_id for f in audit_trajectory(build_trajectory_record(state))}


@pytest.mark.parametrize(
    "wrapped",
    [
        "/bin/bash -lc 'pytest -q'",
        "bash -c 'pytest -q'",
        "/usr/bin/zsh -lc 'pytest -q'",
        "sh -c 'pytest -q'",
    ],
)
def test_a_driver_shell_wrapper_is_unwrapped_to_the_command_it_runs(wrapped: str) -> None:
    """Codex hands the shell ``bash -lc '<command>'``; the MCP tool is handed ``<command>``."""
    state = _state()

    row = record_driver_exec(state, command=wrapped, exit_code=1, output="1 failed")
    mcp = record_tool_call(
        state, tool="shell", arguments={"command": "pytest -q"}, ok=True, outcome_ok=True
    )

    assert row is not None
    assert row.command == "pytest -q"
    assert row.intent == "verify"
    assert row.signature == mcp.signature
    assert build_trajectory_record(state).unresolved_errors == []


def test_a_failing_command_records_an_unsuccessful_outcome() -> None:
    state = _state()

    row = record_driver_exec(state, command="pytest -q", exit_code=1, output="1 failed")

    assert row is not None
    assert row.tool == "shell"
    assert row.command == "pytest -q"
    assert row.outcome_ok is False
    assert row.intent == "verify"
    assert state.tool_calls == [row]


def test_a_later_passing_run_of_the_same_signature_resolves_it() -> None:
    state = _state()

    first = record_driver_exec(state, command="pytest -q", exit_code=1, output="1 failed")
    second = record_driver_exec(state, command="pytest -q", exit_code=0, output="1 passed")

    assert first is not None
    assert second is not None
    assert first.signature == second.signature
    assert second.outcome_ok is True
    record = build_trajectory_record(state)
    assert record.unresolved_errors == []
    assert record.fixes_after_failures == 1
    assert "unresolved-failure" not in _rule_ids(state)


def test_a_failing_command_that_never_passes_is_an_unresolved_failure() -> None:
    state = _state()

    record_driver_exec(state, command="pytest -q", exit_code=1, output="1 failed")

    assert "unresolved-failure" in _rule_ids(state)


def test_a_passing_mcp_shell_call_resolves_a_failed_driver_native_one() -> None:
    """Both doors write the same ``shell`` signature, so the rows resolve each other."""
    state = _state()

    record_driver_exec(state, command="pytest -q", exit_code=1, output="1 failed")
    record_tool_call(
        state,
        tool="shell",
        arguments={"command": "pytest -q"},
        ok=True,
        outcome_ok=True,
    )

    assert build_trajectory_record(state).unresolved_errors == []


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("bwrap: No permissions to create a new namespace", "environment"),
        ("newuidmap: write to uid_map failed: Operation not permitted", "environment"),
        ("fatal: Authentication failed for 'https://github.com/acme/demo.git/'", "environment"),
        ("curl: (56) Recv failure: Connection reset by peer", "transient"),
        ("ssh: connect to host github.com port 22: Connection timed out", "transient"),
        ("error: RPC failed; HTTP 503 curl 22 The requested URL returned error: 503", "transient"),
    ],
    ids=["bwrap", "newuidmap", "auth", "reset", "ssh-timeout", "http-503"],
)
def test_environment_and_transient_failures_get_a_named_class(output: str, expected: str) -> None:
    state = _state()

    row = record_driver_exec(state, command="git fetch origin", exit_code=128, output=output)

    assert row is not None
    assert row.ok is False
    assert row.outcome_ok is False
    assert row.failure_class == expected
    assert row.error


def test_a_plain_non_zero_exit_stays_an_ordinary_failed_outcome() -> None:
    """Same shape as the MCP shell tool: the call ran, the command failed."""
    state = _state()

    row = record_driver_exec(state, command="make lint", exit_code=2, output="E501 line too long")

    assert row is not None
    assert row.ok is True
    assert row.outcome_ok is False
    assert row.failure_class == "unknown"


def test_test_output_that_mentions_a_status_code_is_not_a_transient_failure() -> None:
    """A failing test named ``test_502_handling`` is a test failure, not a flaky network."""
    state = _state()

    row = record_driver_exec(
        state,
        command="pytest tests/test_gateway.py",
        exit_code=1,
        output="FAILED tests/test_gateway.py::test_502_handling - assert 502 == 200",
    )

    assert row is not None
    assert row.ok is True
    assert row.failure_class == "unknown"


def test_a_timed_out_command_is_a_transient_failure() -> None:
    state = _state()

    row = record_driver_exec(state, command="npm test", timed_out=True)

    assert row is not None
    assert row.ok is False
    assert row.outcome_ok is False
    assert row.failure_class == "transient"


def test_an_ignored_environment_failure_fires_the_auditor() -> None:
    state = _state()

    record_driver_exec(
        state,
        command="git fetch origin",
        exit_code=128,
        output="fatal: Authentication failed",
    )

    assert "ignored-tool-error" in _rule_ids(state)


def test_an_identical_retry_after_a_transient_failure_fires_stale_assumption() -> None:
    state = _state()
    for _ in range(2):
        record_driver_exec(
            state,
            command="npm ci",
            exit_code=1,
            output="npm ERR! network Connection reset by peer",
        )

    assert "stale-assumption-after-failure" in _rule_ids(state)


def test_a_driver_reported_failure_without_an_exit_code_is_a_failed_outcome() -> None:
    state = _state()

    row = record_driver_exec(state, command="cargo test", failed=True, output="boom")

    assert row is not None
    assert row.outcome_ok is False


def test_a_call_with_no_outcome_signal_does_not_invent_one() -> None:
    state = _state()

    row = record_driver_exec(state, command="ls src")

    assert row is not None
    assert row.outcome_ok is None


@pytest.mark.parametrize(
    "command",
    [
        "rg -n x src/",
        "grep -rn todo src/",
        "git diff --quiet",
        "diff -u a b",
        "cmp -s a b",
        "test -f pyproject.toml",
    ],
    ids=["rg-no-match", "grep-no-match", "git-diff-quiet", "diff", "cmp", "test"],
)
def test_a_question_answering_exit_one_claims_nothing(command: str) -> None:
    """These exit 1 by design; recording that as failure is Critical noise (#885)."""
    state = _state()

    row = record_driver_exec(state, command=command, exit_code=1, output="")

    assert row is not None
    assert row.outcome_ok is None
    assert row.failure_class == "unknown"
    assert "unresolved-failure" not in _rule_ids(state)


@pytest.mark.parametrize(
    "command", ["pytest -q", "make test", "ruff check src"], ids=["pytest", "make", "ruff"]
)
def test_a_verify_intent_exit_one_is_still_a_failure(command: str) -> None:
    """The rule is the command's intent, not the exit code alone."""
    state = _state()

    row = record_driver_exec(state, command=command, exit_code=1, output="1 failed")

    assert row is not None
    assert row.intent == "verify"
    assert row.outcome_ok is False
    assert "unresolved-failure" in _rule_ids(state)


def test_the_command_and_output_are_redacted_before_they_are_stored() -> None:
    state = _state()

    row = record_driver_exec(
        state,
        command=f"curl -H 'Authorization: Bearer {_CANARY}' https://x.invalid",
        exit_code=7,
        output=f"curl: (7) Failed to connect; token={_CANARY} connection reset by peer",
    )

    assert row is not None
    blob = (row.command or "") + (row.error or "")
    assert _CANARY not in blob


def test_a_declined_or_policy_blocked_command_is_a_policy_failure() -> None:
    state = _state()

    row = record_driver_exec(state, command="rm -rf /", declined=True)

    assert row is not None
    assert row.ok is False
    assert row.failure_class == "policy"


# ── recording never fails a tool call ────────────────────────────────────────


@pytest.mark.parametrize("state", [None, object(), "not-a-state"], ids=["none", "bare", "str"])
def test_recording_on_something_that_is_not_a_tool_state_is_a_no_op(state: Any) -> None:
    assert record_driver_exec(state, command="ls", exit_code=0) is None


@pytest.mark.parametrize("command", [None, "", 42, b"ls"], ids=["none", "empty", "int", "bytes"])
def test_a_command_that_is_not_text_is_ignored(command: Any) -> None:
    state = _state()

    assert record_driver_exec(state, command=command, exit_code=1) is None
    assert state.tool_calls == []


def test_a_failure_inside_the_recorder_is_swallowed_and_logged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _explode(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("recorder bug")

    monkeypatch.setattr(trajectory, "record_tool_call", _explode)

    assert trajectory.record_driver_exec(_state(), command="ls", exit_code=0) is None


def test_a_state_whose_call_list_cannot_be_appended_to_does_not_raise() -> None:
    class _Frozen:
        tool_calls: tuple[()] = ()
        primary_repo_key = "acme/demo"
        repos: ClassVar[dict[str, Any]] = {}

    assert record_driver_exec(_Frozen(), command="ls", exit_code=0) is None


# ── classification at the execute choke ──────────────────────────────────────


def test_classify_failure_at_execute_prefers_typed_signals_over_prose() -> None:
    assert classify_failure_at_execute("anything", timed_out=True) == "transient"
    assert classify_failure_at_execute("anything", declined=True) == "policy"
    assert classify_failure_at_execute(None) == "unknown"
    assert classify_failure_at_execute("") == "unknown"
    assert classify_failure_at_execute("bwrap: no") == "environment"
    assert classify_failure_at_execute("E501 line too long") == "unknown"


class _FinishedProcess:
    """Stands in for the spawned shell: the command ran and exited ``returncode``."""

    pid = 4242

    def __init__(self, returncode: int) -> None:
        self.returncode = returncode

    def communicate(self, timeout: float | None = None) -> tuple[bytes, bytes]:
        del timeout
        return b"", b""


async def _mcp_shell_door(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, command: str, exit_code: int
) -> Any:
    """Run ``command`` through ``tools/call`` exactly as production does.

    The real ``shell`` tool spec, its ``execute()`` wrapper (which turns the
    body's dict into a :class:`ToolResult`) and ``dispatch_mcp_rpc`` all run;
    only the process spawn is replaced, so the test needs no sandbox.
    """
    import mergecraft.mcp.shell as shell_mod

    def _spawn(*_args: Any, **_kwargs: Any) -> _FinishedProcess:
        return _FinishedProcess(exit_code)

    monkeypatch.setattr(shell_mod, "_spawn_shell", _spawn)
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    # ``shell`` is a mutating tool; ``rpc.py`` binds the run's mode before it runs.
    state.selected_mode = "Fix"
    ctx = make_tool_context(tmp_path, trust_tier="trusted", tool_state=state)
    spec = shell_mod.shell_tool(ctx)
    response = await dispatch_mcp_rpc(
        1,
        "tools/call",
        {"name": "shell", "arguments": {"command": command, "description": "probe"}},
        tools=[spec],
        by_name={"shell": spec},
        tool_ctx=ctx,
        validators={},
    )
    assert "result" in response, response
    assert response["result"].get("isError") is not True, response
    return state


async def _driver_door(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, command: str, exit_code: int
) -> Any:
    del tmp_path, monkeypatch
    state = _state()
    record_driver_exec(state, command=command, exit_code=exit_code, output="")
    return state


_Door = Callable[..., Awaitable[Any]]


@pytest.mark.parametrize("door", [_mcp_shell_door, _driver_door], ids=["mcp-shell", "driver"])
async def test_a_no_match_search_claims_nothing_through_either_door(
    door: _Door, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``rg`` with no match exits 1; neither door may call that a failure (#1027)."""
    state = await door(tmp_path, monkeypatch, command="rg -n x src/", exit_code=1)

    assert [(row.tool, row.outcome_ok) for row in state.tool_calls] == [("shell", None)]
    assert "unresolved-failure" not in _rule_ids(state)


@pytest.mark.parametrize("door", [_mcp_shell_door, _driver_door], ids=["mcp-shell", "driver"])
async def test_a_failing_verify_command_is_one_unresolved_failure_through_either_door(
    door: _Door, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``pytest -q`` exiting 1 is a real failure through both doors (#1027)."""
    state = await door(tmp_path, monkeypatch, command="pytest -q", exit_code=1)

    assert [(row.tool, row.outcome_ok) for row in state.tool_calls] == [("shell", False)]
    findings = audit_trajectory(build_trajectory_record(state))
    assert [f.rule_id for f in findings].count("unresolved-failure") == 1


async def test_a_passing_command_through_the_mcp_door_is_a_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = await _mcp_shell_door(tmp_path, monkeypatch, command="pytest -q", exit_code=0)

    assert [row.outcome_ok for row in state.tool_calls] == [True]


def test_an_error_or_publication_skip_result_claims_no_outcome() -> None:
    """Only execution-outcome keys are read out of a wrapped result."""
    from mergecraft.mcp.shared import ToolResult, handle_tool_error, handle_tool_success
    from mergecraft.mcp.tool_call import _result_payload

    skip = handle_tool_success({"success": False, "skipped": True, "reason": "mismatch"})
    exited = handle_tool_success({"output": "", "exit_code": 1, "timed_out": False})
    not_json = ToolResult(content=[{"type": "text", "text": "plain text"}])

    assert _result_payload(skip) == {}
    assert _result_payload(handle_tool_error(RuntimeError("boom"))) is None
    assert _result_payload(not_json) is None
    assert _result_payload(exited) == {"exit_code": 1, "timed_out": False}
    assert trajectory.outcome_ok_from_result(_result_payload(skip)) is None


@pytest.mark.parametrize(
    ("command", "exit_code", "expected"),
    [
        ("rg -n x src/", 0, True),
        ("rg -n x src/", 1, None),
        ("rg -n x src/", 2, False),
        ("pytest -q", 1, False),
        ("bash -lc 'pytest -q'", 1, False),
    ],
)
def test_the_mcp_shell_reading_matches_the_driver_rule(
    command: str, exit_code: int, expected: bool | None
) -> None:
    """One rule, two doors: the MCP reading is the driver reading (#1027)."""
    mcp = trajectory.outcome_ok_from_result(
        {"exit_code": exit_code}, tool="shell", arguments={"command": command}
    )
    driver = record_driver_exec(_state(), command=command, exit_code=exit_code, output="")

    assert driver is not None
    assert mcp is expected
    assert driver.outcome_ok is expected


def test_a_gate_tool_exit_code_keeps_the_strict_reading() -> None:
    """A tool with no command to classify still reads any non-zero exit as a failure."""
    assert trajectory.outcome_ok_from_result({"exitCode": 1}, tool="run_static_checks") is False
    assert trajectory.outcome_ok_from_result({"exitCode": 1}) is False
