"""A claude run that parses no events must still say why.

The streaming path reported only ``claude CLI produced no events`` when the
accumulator was empty. The exit code and stderr were both already read and
both were discarded, and ``is_retryable_cli_failure`` was never consulted, so
a transient failure was marked non-retryable and the model chain gave up on
the rung after one attempt.

Observed on run 33208727218: the Claude backstop engaged exactly as designed
and then failed with nothing to diagnose from. Closed issue #445 is the same
defect in the codex driver.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.agents.claude import _run_claude_once
from mergecraft.agents.shared import AgentRunContext, ResolvedInstructions
from mergecraft.mcp.context import PayloadEvent, ResolvedPayload
from mergecraft.mcp.tool_state import init_tool_state

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

_AUTH_STDERR = "Invalid API key · Please run /login\n"


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


class _SilentProcess:
    """A CLI that emits no stdout events, then exits with a reason on stderr."""

    def __init__(self, *, returncode: int, stderr: str) -> None:
        self.stdout = iter(())
        self.stderr = _Reader(stderr)
        self._returncode = returncode
        self.pid = 4242

    def wait(self, timeout: float | None = None) -> int:
        return self._returncode

    def poll(self) -> int:
        return self._returncode

    def kill(self) -> None:  # pragma: no cover - not reached on a clean exit
        return None


class _Reader:
    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text


def _drive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    returncode: int,
    stderr: str,
) -> tuple[Any, list[tuple[str, str]]]:
    module = importlib.import_module("mergecraft.agents.claude")
    monkeypatch.setattr(
        module,
        "spawn_agent_cli",
        lambda *_a, **_k: _SilentProcess(returncode=returncode, stderr=stderr),
    )
    monkeypatch.setattr(module, "track_process_group", _noop_ctx)
    monkeypatch.setattr(module, "wait_or_kill_process_group", lambda proc, timeout: proc.wait())

    records: list[tuple[str, str]] = []
    sink = logger.add(
        lambda rec: records.append((rec.record["level"].name, rec.record["message"])),
        level="DEBUG",
    )
    try:
        result = _run_claude_once(
            cli="/usr/bin/claude",
            prompt="review this diff",
            ctx=_run_ctx(tmp_path),
            mcp_config=str(tmp_path / "mcp.json"),
        )
    finally:
        logger.remove(sink)
    return result, records


class _noop_ctx:
    def __init__(self, *_a: object, **_k: object) -> None: ...
    def __enter__(self) -> None: ...
    def __exit__(self, *_a: object) -> bool:
        return False


def test_zero_events_surfaces_the_exit_code_and_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reported case: the backstop failed with no diagnosis available."""
    result, records = _drive(tmp_path, monkeypatch, returncode=1, stderr=_AUTH_STDERR)

    assert result.success is False
    assert result.error is not None
    assert result.error != "claude CLI produced no events", "the symptom is not the diagnosis"
    assert "1" in result.error, f"exit code missing: {result.error}"
    assert "Invalid API key" in result.error, f"stderr missing: {result.error}"

    visible = [msg for level, msg in records if level in {"WARNING", "ERROR"}]
    assert any("Invalid API key" in msg for msg in visible), visible


def test_zero_events_still_names_the_attempt_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The model is what tells a reader which rung of the cascade died."""
    result, _ = _drive(tmp_path, monkeypatch, returncode=1, stderr=_AUTH_STDERR)

    assert result.error is not None
    assert "claude-sonnet" in result.error.lower(), result.error


def test_a_clean_exit_with_no_events_is_reported_distinctly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exit 0 and silence is a different fault; do not invent an exit code."""
    result, _ = _drive(tmp_path, monkeypatch, returncode=0, stderr="")

    assert result.success is False
    assert result.error is not None
    assert "exited 0" in result.error
    assert "no stderr output" in result.error


def test_a_retryable_zero_event_failure_keeps_its_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The classifier must run, or the chain abandons the rung after one try.

    This is the half that cost the backstop. ``429`` is chosen deliberately:
    ``is_retryable_cli_failure`` calls it retryable, so the unfixed path --
    which set no metadata at all -- reads as non-retryable and fails here. A
    stderr the classifier already considers terminal would have compared
    ``False == False`` and passed against the bug.
    """
    module = importlib.import_module("mergecraft.agents.claude")
    retryable_stderr = "429 Too Many Requests\n"
    assert module.is_retryable_cli_failure(returncode=1, stderr=retryable_stderr) is True

    result, _ = _drive(tmp_path, monkeypatch, returncode=1, stderr=retryable_stderr)

    assert result.metadata.get("retryable") is True, (
        "a retryable zero-event failure must keep its retry, or the backstop "
        "is spent on one attempt"
    )


def test_a_terminal_zero_event_failure_is_not_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guard the guard: classifying must not mark everything retryable."""
    module = importlib.import_module("mergecraft.agents.claude")
    assert module.is_retryable_cli_failure(returncode=1, stderr=_AUTH_STDERR) is False

    result, _ = _drive(tmp_path, monkeypatch, returncode=1, stderr=_AUTH_STDERR)

    assert not result.metadata.get("retryable")
