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

from typing import Any, ClassVar

import pytest

from mergecraft.evidence import trajectory
from mergecraft.evidence.trajectory import build_trajectory_record, record_tool_call
from mergecraft.evidence.trajectory_audit import audit_trajectory
from mergecraft.mcp.tool_state import init_tool_state

_CANARY = "sk-canary-driver-exec-0123456789abcdef0123456789"


def record_driver_exec(*args: Any, **kwargs: Any) -> Any:
    return trajectory.record_driver_exec(*args, **kwargs)


def classify_failure_at_execute(*args: Any, **kwargs: Any) -> Any:
    return trajectory.classify_failure_at_execute(*args, **kwargs)


def _state() -> Any:
    return init_tool_state(owner="acme", name="demo", dir="/tmp/demo")


def _rule_ids(state: Any) -> set[str]:
    return {f.rule_id for f in audit_trajectory(build_trajectory_record(state))}


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
