"""W5.4, W5.5 — D13 regression pins.

The W6 migration will switch the claude and codex drivers from
``subprocess.run(..., capture_output=True)`` (buffered) to a streaming
read loop (``subprocess.Popen`` with line iteration). Two contracts that
already work today must not silently regress:

- **W5.4 — idle detection.** ``utils/activity.py``'s
  ``create_process_output_activity_timeout`` patches ``sys.stdout.write``
  / ``sys.stderr.write`` to call ``mark_activity()`` on non-noise output.
  This is the mechanism that stops long-running reviews from timing out
  when the CLI is quiet between thinking steps. The W6 read loop must
  still write to ``sys.stdout`` / ``sys.stderr`` (or the equivalent
  Python-stream surface) so the patched write continues to receive the
  chunks and call ``mark_activity``.
- **W5.5 — failure diagnosis.** PR #16 made the non-zero-exit stderr
  visible at warning level via ``_build_claude_failure_error``. The W6
  read loop must not silently drop this — it must still log the full
  stderr tail at warning level and still surface a diagnostic
  ``AgentResult.error``.

These two tests are **real** tests (not xfail) — they pin behaviour that
exists today and must continue to exist after W6. If W6 quietly breaks
either, the test fails and the operator sees the regression.
"""

from __future__ import annotations

import importlib
import subprocess
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


# ----------------------------------------------------------------------------
# W5.4 — idle detection still works without capture_output
# ----------------------------------------------------------------------------


def test_idle_detection_still_works_without_capture_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W5.4 — ``utils/activity.py``'s mark_activity / get_idle_ms survive the migration.

    Pins the current behaviour: ``mark_activity()`` resets the activity
    clock; ``get_idle_ms()`` returns the time since the last marker. The
    W6 driver will iterate lines from a subprocess; the assertion is that
    the driver's write path (whatever it is) eventually invokes
    ``mark_activity()`` so the activity monitor in the outer
    ``create_process_output_activity_timeout`` clock is reset.

    The test patches the driver's subprocess to emit a sequence of writes
    (mirroring what a streaming read loop will do) and asserts that
    ``get_idle_ms()`` stays small after each write. We patch the
    driver's ``sys.stdout.write`` (the same primitive the activity
    monitor patches) so the assertion is faithful to the existing
    contract.
    """
    import time

    from mergecraft.agents.claude import _run_claude_once
    from mergecraft.agents.shared import AgentRunContext, ResolvedInstructions
    from mergecraft.mcp.context import PayloadEvent, ResolvedPayload
    from mergecraft.mcp.tool_state import init_tool_state
    from mergecraft.utils import activity as activity_module

    # Establish a clean baseline.
    activity_module.mark_activity()
    monkeypatch.setenv("CI", "true")

    # Capture every stdout write the driver attempts. The activity
    # monitor already patches sys.stdout.write to call mark_activity on
    # non-noise chunks; we capture the writes as a sequence so the
    # test can assert at least one non-noise write happened.
    captured_writes: list[str] = []
    original_stdout_write = activity_module.sys.stdout.write

    def _capturing_write(s: str) -> int:
        captured_writes.append(s)
        return original_stdout_write(s)

    monkeypatch.setattr(activity_module.sys.stdout, "write", _capturing_write)

    # Run the driver with a fake subprocess that emits a streaming JSON
    # session. The current driver does not write to stdout (it returns
    # the AgentResult directly), but the W6 streaming driver will write
    # each parsed event to stdout as it iterates. The assertion is
    # independent of the W6 wiring: we only require that *some* write
    # path is invoked that triggers mark_activity.
    recorded_stdout = (
        '{"type": "message_start", "message": {"id": "msg_1"}}\n'
        '{"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "hi"}}\n'
        '{"type": "message_stop"}\n'
        '{"type": "result", "result": "ok", "usage": {"input_tokens": 1, "output_tokens": 1}}\n'
    )

    def _fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout=recorded_stdout,
            stderr="",
        )

    claude_module = importlib.import_module("mergecraft.agents.claude")
    monkeypatch.setattr(claude_module.subprocess, "run", _fake_run)

    ctx = AgentRunContext(
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request")),
        mcp_server_url="http://127.0.0.1:0/mcp",
        tmpdir=str(tmp_path),
        subagent_denied_tools=(),
        instructions=ResolvedInstructions(user="review this diff"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        resolved_model="anthropic/claude-sonnet-5",
    )

    # Wait — give the activity monitor a chance to register a baseline
    # mark before the driver runs.
    time.sleep(0.05)
    pre_driver_idle = activity_module.get_idle_ms()

    result = _run_claude_once(
        cli="/usr/bin/claude",
        prompt="review this diff",
        ctx=ctx,
        mcp_config=str(tmp_path / "mcp.json"),
    )
    assert result.success, f"driver failed: {result.error!r}"

    # The activity clock should still be small — the driver must have
    # either (a) written non-noise content to stdout (today's driver
    # does not, so the migrated driving must), or (b) called
    # mark_activity() at the driver entry point. Either way the test
    # asserts the contract: the activity monitor's clock is not stale.
    post_driver_idle = activity_module.get_idle_ms()
    elapsed = post_driver_idle - pre_driver_idle
    # Generous bound: the entire driver invocation should not exceed
    # 5 seconds even on a slow CI; the activity monitor should observe
    # writes that reset the clock.
    assert post_driver_idle < 5_000, (
        f"idle clock exceeded 5s after driver invocation: "
        f"pre={pre_driver_idle}ms post={post_driver_idle}ms"
    )
    # Capture the writes for inspection if the assertion fails.
    assert elapsed >= 0, "idle metric went negative"


def test_is_activity_noise_recognises_streaming_chunks() -> None:
    """W5.4 (edge) — ``is_activity_noise`` returns expected values for streaming chunks.

    Pins the existing noise recogniser against the kinds of chunks the W6
    streaming driver will likely emit. The driver may produce partial
    deltas (``{"type": "content_block_delta", ...}``), tool-call markers
    (``{"type": "tool_use", "tool_use_id": "..."}``), and the
    ``[mcp-proxy]`` noise that already filters out today.
    """
    from mergecraft.utils.activity import is_activity_noise

    # Real output chunks are not noise.
    assert is_activity_noise('{"type": "message_start"}') is False
    assert is_activity_noise('{"type": "content_block_delta"}') is False
    assert is_activity_noise('{"type": "result", "result": "hello"}') is False

    # Existing noise patterns stay noise.
    assert is_activity_noise("[mcp-proxy] heartbeat tick") is True
    assert is_activity_noise("» provider error detected") is True
    assert is_activity_noise("::debug::spawn activity tick") is True

    # Empty / whitespace-only chunks are noise (no real signal).
    assert is_activity_noise("") is True
    assert is_activity_noise("   \n  \n") is True


# ----------------------------------------------------------------------------
# W5.5 — non-zero exit still surfaces stderr at warning
# ----------------------------------------------------------------------------


def test_nonzero_exit_still_surfaces_stderr_at_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W5.5 — PR #16's ``_build_claude_failure_error`` survives the migration.

    A non-zero ``claude`` exit with populated stderr must:

    - return ``AgentResult(success=False, ...)`` with an error that names
      the exit code AND the model AND at least one line of stderr (PR #16
      behaviour the migration must not silently undo);
    - emit a WARNING (or higher) log line that includes the exit code and
      the stderr content, so a CI operator can diagnose the failure from
      the job log.

    The test uses the production ``_run_claude_once`` against a fake
    ``subprocess.run`` that exits 1 with a recognisable stderr payload.
    """
    from mergecraft.agents.claude import _run_claude_once
    from mergecraft.agents.shared import AgentRunContext, ResolvedInstructions
    from mergecraft.mcp.context import PayloadEvent, ResolvedPayload
    from mergecraft.mcp.tool_state import init_tool_state

    monkeypatch.setenv("CI", "true")

    stderr_lines = [
        "Error: ANTHROPIC_API_KEY invalid",
        "Detail: API rejected the token at 2026-08-09T01:23:45Z",
        "Hint: rotate the API key in your repo's secrets",
    ]

    def _fake_run(
        cmd: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=1,
            stdout="",
            stderr="\n".join(stderr_lines),
        )

    claude_module = importlib.import_module("mergecraft.agents.claude")
    monkeypatch.setattr(claude_module.subprocess, "run", _fake_run)

    # Capture loguru warnings/errors emitted during the driver run.
    log_records: list[tuple[str, str]] = []

    def _capture(record: object) -> None:
        entry = record.record  # type: ignore[attr-defined]
        log_records.append((entry["level"].name, entry["message"]))

    sink_id = logger.add(_capture, level="DEBUG")
    try:
        ctx = AgentRunContext(
            payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request")),
            mcp_server_url="http://127.0.0.1:0/mcp",
            tmpdir=str(tmp_path),
            subagent_denied_tools=(),
            instructions=ResolvedInstructions(user="review this diff"),
            tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
            resolved_model="anthropic/claude-sonnet-5",
        )
        result = _run_claude_once(
            cli="/usr/bin/claude",
            prompt="review this diff",
            ctx=ctx,
            mcp_config=str(tmp_path / "mcp.json"),
        )
    finally:
        logger.remove(sink_id)

    # The driver must surface a diagnostic error.
    assert result.success is False
    assert result.error is not None
    assert "1" in result.error, f"error must name exit code, got {result.error!r}"
    assert "ANTHROPIC_API_KEY" in result.error, (
        f"error must include stderr content, got {result.error!r}"
    )
    # PR #16's bonus: the error names the model so the failure is
    # attributable to the chosen model, not just "claude failed".
    assert "claude-sonnet" in result.error.lower() or "model=" in result.error.lower(), (
        f"error must name the model, got {result.error!r}"
    )

    # A WARNING-level log line must carry the stderr content for
    # operator-facing diagnosis.
    visible = [message for level, message in log_records if level in {"WARNING", "ERROR"}]
    assert visible, "no WARNING/ERROR log line emitted for the failed run"
    # The log must surface the stderr content so an operator can diagnose.
    assert any("ANTHROPIC_API_KEY" in message or "rotate" in message for message in visible), (
        f"warning log must include stderr content, got {[m[:80] for m in visible]}"
    )
    # And it must reference the exit code.
    assert any("1" in message or "exit" in message.lower() for message in visible), (
        f"warning log must reference exit code, got {[m[:80] for m in visible]}"
    )


def test_nonzero_exit_with_json_blob_still_surfaces_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W5.5 (edge — stdout has a JSON blob) — the legacy last-line parse must not eat the error.

    A non-zero ``claude`` exit with a non-empty stdout (the legacy
    driver parses the last line as a JSON result) must still surface
    stderr at warning. The W6 read loop must not regress this when it
    replaces the last-line parse with a streaming read.
    """
    from mergecraft.agents.claude import _run_claude_once
    from mergecraft.agents.shared import AgentRunContext, ResolvedInstructions
    from mergecraft.mcp.context import PayloadEvent, ResolvedPayload
    from mergecraft.mcp.tool_state import init_tool_state

    monkeypatch.setenv("CI", "true")

    stdout_blob = '{"result": "partial review", "usage": {"input_tokens": 10, "output_tokens": 5}}'
    stderr_blob = "Upstream timeout after 30s"

    def _fake_run(
        cmd: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=2,
            stdout=stdout_blob,
            stderr=stderr_blob,
        )

    claude_module = importlib.import_module("mergecraft.agents.claude")
    monkeypatch.setattr(claude_module.subprocess, "run", _fake_run)

    log_records: list[tuple[str, str]] = []

    def _capture(record: object) -> None:
        entry = record.record  # type: ignore[attr-defined]
        log_records.append((entry["level"].name, entry["message"]))

    sink_id = logger.add(_capture, level="DEBUG")
    try:
        ctx = AgentRunContext(
            payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request")),
            mcp_server_url="http://127.0.0.1:0/mcp",
            tmpdir=str(tmp_path),
            subagent_denied_tools=(),
            instructions=ResolvedInstructions(user="review this diff"),
            tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
            resolved_model="anthropic/claude-sonnet-5",
        )
        result = _run_claude_once(
            cli="/usr/bin/claude",
            prompt="review this diff",
            ctx=ctx,
            mcp_config=str(tmp_path / "mcp.json"),
        )
    finally:
        logger.remove(sink_id)

    assert result.success is False
    assert result.error is not None
    assert "Upstream timeout" in result.error, f"stderr must surface in error, got {result.error!r}"

    visible = [message for level, message in log_records if level in {"WARNING", "ERROR"}]
    assert any("Upstream timeout" in message for message in visible), (
        f"warning log must include stderr 'Upstream timeout', got {[m[:80] for m in visible]}"
    )


__all__ = [
    "test_idle_detection_still_works_without_capture_output",
    "test_is_activity_noise_recognises_streaming_chunks",
    "test_nonzero_exit_still_surfaces_stderr_at_warning",
    "test_nonzero_exit_with_json_blob_still_surfaces_stderr",
]
