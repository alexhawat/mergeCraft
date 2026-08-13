"""Plan S1 — ``setup_script`` execution is bounded (F6).

Contracts:

- F6: a hanging ``setup_script`` is killed at its deadline (default 10m or
  operator-overridden). The deadline wraps ``asyncio.wait_for`` over the
  subprocess ``communicate()``, **not** a bare ``await proc.communicate()``.
- The setup script runs as a session leader (``start_new_session=True``) so
  its process group can be killed whole, including any children it forked.
- The setup elapsed time is **deducted** from the agent deadline so a slow
  setup cannot silently extend the run deadline (no budget creep).
- A timeout maps to ``RunOutcome.inconclusive`` (D5) with a reason
  distinguishable from a non-zero exit.

The timeout + grandchildren tests drive real subprocesses (no mocks in the
kill path) — mirroring ``tests/security/test_process_tree_kill.py``. The
budget / outcome tests drive the harness.
"""

from __future__ import annotations

import contextlib
import os
import signal
import time
from pathlib import Path

import pytest

from mergecraft.config.settings import RepoSettings
from mergecraft.run_outcome import RunOutcome
from tests.support.run_main_harness import FakeAgent, run_main_for_test

_TRUSTED_EVENT = "workflow_dispatch"
_TRUSTED_PAYLOAD: dict[str, object] = {"action": "workflow_dispatch"}


def _pid_alive(pid: int) -> bool:
    """POSIX check — a process can still receive signals."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_until_dead(pid: int, *, timeout_s: float = 5.0) -> bool:
    """Poll ``_pid_alive`` until it returns False or the timeout expires."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return True
        time.sleep(0.05)
    return not _pid_alive(pid)


# ── Pending (RED — green after S1.2) ─────────────────────────────────────────


@pytest.mark.skipif(not hasattr(os, "killpg"), reason="process groups are POSIX-only")
def test_hanging_setup_script_is_killed_at_deadline(tmp_path: Path) -> None:
    """F6 — a ``sleep 600`` script with a 2 s budget terminates promptly.

    Today's ``main.py:375`` does ``await proc.communicate()`` with no
    deadline — a hanging install stalls until the GitHub job ceiling. S1.2
    wraps the wait in ``asyncio.wait_for(..., timeout=setup_timeout_s)``
    and reuses ``utils.process_group.kill_process_group``.

    This test exercises the helper the impl wave will call — not a private
    second kill path (convention 9).
    """
    import subprocess

    from mergecraft.utils.process_group import wait_or_kill_process_group

    # Real subprocess as a session leader (mirrors what ``start_new_session=True``
    # buys in the asyncio subprocess_shell path).
    proc = subprocess.Popen(
        ["sleep", "600"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    started = time.monotonic()
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            wait_or_kill_process_group(proc, timeout=0.5)
        elapsed = time.monotonic() - started
        assert elapsed < 5.0, (
            f"kill path took {elapsed:.2f}s — TERM→grace→KILL must complete promptly"
        )
        # The session leader must be reaped within the deadline budget.
        assert _wait_until_dead(proc.pid, timeout_s=3.0), (
            f"session leader pid {proc.pid} survived the kill — the helper did "
            f"not actually terminate the group"
        )
        assert proc.poll() is not None
    finally:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(proc.pid, signal.SIGKILL)
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=1)


async def test_setup_timeout_exceeding_run_budget_raises_configuration_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """S1 review / F3 follow-up — a ``setup_timeout`` that consumes the
    entire (or exceeds the) run budget must fail closed as
    ``configuration_error``, before the setup script runs.

    Equal deadlines let the setup script eat the whole budget; the agent
    budget is then clamped to ~1 ms and the eventual
    ``_AgentTimeoutError`` masks the setup failure as ``timed_out``
    instead of the ``inconclusive`` / ``configuration_error`` the setup
    policy was supposed to produce. The fix reserves agent budget by
    raising ``_ConfigurationError`` at setup-timeout resolution.

    The S1 review follow-up wires ``setup_timeout`` through
    :func:`mergecraft.action.inputs.apply_setup_overrides`, so this test
    sets ``INPUT_SETUP_TIMEOUT`` *and* ``INPUT_TIMEOUT`` to pin the
    equal-deadline guard explicitly — the YAML side no longer
    accidentally collides with the default ``10m`` after the precedence
    fix lands.
    """
    from mergecraft.agents.shared import AgentResult

    sentinel_agent = FakeAgent(
        name="claude",
        result=AgentResult(success=True, output="must-not-run"),
    )

    # Action input wins: ``INPUT_SETUP_TIMEOUT: 30m`` is strictly larger
    # than the run budget ``INPUT_TIMEOUT: 60s`` — the equal-deadline /
    # exceeds-deadline guard in ``main.py`` must fire and short-circuit
    # before the agent loop.
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=RepoSettings(
            setup_script="./anything-here",
        ),
        env={
            "GITHUB_EVENT_NAME": _TRUSTED_EVENT,
            "INPUT_SETUP_TIMEOUT": "30m",
            "INPUT_TIMEOUT": "60s",
        },
        event_name=_TRUSTED_EVENT,
        event_payload=_TRUSTED_PAYLOAD,
        agents_by_slug={"claude": sentinel_agent},
    )
    assert rec.result is not None
    # The agent must NEVER have been invoked — the validation runs
    # before the agent loop.
    assert sentinel_agent.calls == [], (
        f"F3 follow-up violated: agent ran {len(sentinel_agent.calls)} "
        f"times despite setup_timeout > run timeout — the validation "
        f"must short-circuit before the agent loop, not after."
    )
    outcome = getattr(rec.result, "outcome", None)
    assert outcome is RunOutcome.configuration_error, (
        f"setup_timeout >= run timeout must fail closed as configuration_error; got {outcome!r}"
    )
    # S1 review / NEW2 — the F3 equal-deadline guard raises while
    # ``tool_context`` is already built (the NEW2 fix moves the
    # ``ToolContext(...)`` construction above this guard). The outer
    # handler therefore has a context to call ``report_status_checks``
    # on, and the harness records that call. The run must end with at
    # least one status-check call carrying the failure reason.
    assert rec.report_status_calls, (
        f"NEW2 violated: F3 equal-deadline guard raised but the outer "
        f"handler did not call report_status_checks — tool_context was "
        f"None when the guard raised; report_status_calls={rec.report_status_calls!r}"
    )
    last = rec.report_status_calls[-1]
    assert last.get("failure_reason"), (
        f"NEW2 violated: report_status_checks was called without a failure_reason; got {last!r}"
    )


async def test_timed_out_setup_script_yields_inconclusive(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """D5 / F6 — a timeout maps to ``inconclusive`` with a reason
    distinguishable from a non-zero exit.

    The harness's fake simulates a setup that hangs past the configured
    timeout (via the ``_FakeShellProc._delay_s`` field added by this wave).
    Today the harness fake returns immediately regardless of the rc, so this
    test asserts the S1.2 outcome resolution path.
    """
    # The fake waits long enough to trigger the asyncio.wait_for on the
    # production side. The impl wave sets up the deadline; until then this
    # is RED.
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=RepoSettings(setup_script="sleep 600"),
        env={
            "GITHUB_EVENT_NAME": _TRUSTED_EVENT,
            # Tiny budget so the test runs quickly even if S1.2 lands.
            "INPUT_SETUP_TIMEOUT": "1s",
        },
        event_name=_TRUSTED_EVENT,
        event_payload=_TRUSTED_PAYLOAD,
        setup_script_rc=0,  # would be rc 0 if it had finished — the timeout is the cause
        setup_script_delay_s=10.0,
    )
    assert rec.result is not None, f"main() raised: {rec.raised!r}"
    outcome = getattr(rec.result, "outcome", None)
    assert outcome is not None
    assert outcome is RunOutcome.inconclusive, (
        f"F6 + D5: timed-out setup_script must yield inconclusive; got {outcome!r}"
    )
    # Reason must be distinguishable from a non-zero exit so the reviewer /
    # operator can tell what happened.
    error_text = str(getattr(rec.result, "error", "") or "")
    assert error_text, "timeout must record a reason on the result"
    lowered = error_text.lower()
    assert "timeout" in lowered or "timed out" in lowered or "deadline" in lowered, (
        f"timeout reason must be distinguishable from a non-zero exit; got {error_text!r}"
    )


@pytest.mark.skipif(not hasattr(os, "killpg"), reason="process groups are POSIX-only")
def test_setup_script_grandchildren_are_reaped(tmp_path: Path) -> None:
    """F6 + convention 9 — a setup script that backgrounds a child must not
    leak that child when the script itself is killed.

    Mirrors ``tests/security/test_process_tree_kill.py::test_timeout_kills_grandchildren``
    exactly: a real shell script forks a ``sleep`` grandchild, the kill path
    runs, and we assert on the *real process state* (NOT a mock's call list).

    The script writes the grandchild PID to a file so we can probe ``os.kill``
    on it directly after the timeout.
    """
    import subprocess

    from mergecraft.utils.process_group import wait_or_kill_process_group

    pid_file = tmp_path / "grandchild.pid"
    cli = tmp_path / "setup-with-grandchild.sh"
    cli.write_text(
        "#!/bin/bash\n"
        "sleep 300 </dev/null >/dev/null 2>&1 &\n"
        f"echo $! > {pid_file}\n"
        "exec 1>&- 2>&-\n"
        "sleep 300\n",
        encoding="utf-8",
    )
    cli.chmod(0o755)

    proc = subprocess.Popen(
        [str(cli)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            wait_or_kill_process_group(proc, timeout=0.5)
        assert pid_file.exists(), "setup script never wrote its grandchild pid"
        grandchild = int(pid_file.read_text().strip())
        assert _wait_until_dead(grandchild, timeout_s=5.0), (
            f"grandchild pid {grandchild} survived the timeout kill — "
            f"the kill path reached the session leader but not the group"
        )
    finally:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(proc.pid, signal.SIGKILL)
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=1)


async def test_setup_timeout_is_deducted_from_the_run_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """F6 — a slow setup script must not silently extend the agent deadline.

    The agent deadline is computed at ``main.py:598-603`` as
    ``asyncio.wait_for(agent_task, timeout=timeout_ms / 1000.0)``. S1.2
    rewrites this so ``timeout_ms`` shrinks by the setup-script elapsed
    time. If a setup takes 2 s and ``timeout=10s`` is configured, the
    agent is given at most 8 s, not 10.

    The test patches ``asyncio.wait_for`` to record the timeout argument
    the production code passes for the *agent* task (not the setup script's
    own wait_for — those are distinct). Today there is no deduction, so
    the recorded deadline equals the full ``timeout_ms``; S1.2 must shrink
    it by the setup's measured elapsed time.
    """
    import asyncio as _asyncio
    import time as _time

    setup_delay = 2.0
    full_budget_s = 10.0
    recorded_agent_deadlines: list[float] = []

    real_wait_for = _asyncio.wait_for

    def _capturing_wait_for(awaitable, timeout=None, **kwargs):  # type: ignore[no-untyped-def]
        # Only capture the deadline argument on the AGENT wait — the setup
        # script has its own (smaller) wait_for. We tag it by the coroutine
        # name: ``_execute_agent`` is the only task S1.2 wraps at top-level.
        # Production passes a Task (``asyncio.create_task(_execute_agent())``),
        # so we resolve the underlying coroutine via ``get_coro`` first, then
        # fall back to direct ``cr_code`` (e.g. for raw coroutines).
        coro = awaitable
        if hasattr(awaitable, "get_coro"):
            with contextlib.suppress(Exception):
                coro = awaitable.get_coro()
        try:
            coro_name = getattr(getattr(coro, "cr_code", None), "co_name", "") or ""
        except AttributeError:
            coro_name = ""
        if coro_name == "_execute_agent" and timeout is not None:
            recorded_agent_deadlines.append(float(timeout))
        return real_wait_for(awaitable, timeout=timeout, **kwargs)

    monkeypatch.setattr(_asyncio, "wait_for", _capturing_wait_for)

    started = _time.monotonic()
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=RepoSettings(setup_script="slow-setup"),
        env={
            "GITHUB_EVENT_NAME": _TRUSTED_EVENT,
            "INPUT_TIMEOUT": f"{int(full_budget_s)}s",
            # Pin a setup budget shorter than the run budget so the S1
            # review follow-up ``setup_timeout < timeout`` guard accepts
            # the configuration — this test is about *deduction*, not
            # about the equal-deadline edge (covered separately).
            "INPUT_SETUP_TIMEOUT": "5s",
        },
        event_name=_TRUSTED_EVENT,
        event_payload=_TRUSTED_PAYLOAD,
        setup_script_rc=0,
        setup_script_delay_s=setup_delay,
    )
    elapsed = _time.monotonic() - started
    assert rec.result is not None
    assert rec.result.success, (
        f"setup_delay={setup_delay}s + agent must fit inside the deducted "
        f"deadline; got {rec.result!r}"
    )
    assert recorded_agent_deadlines, (
        "production code did not call asyncio.wait_for for the agent task — "
        "main.py:598-603 must wrap agent_task in a wait_for that records the "
        "deducted deadline"
    )
    agent_deadline = recorded_agent_deadlines[0]
    # The deadline must be SHORTER than the full budget by approximately
    # the setup delay (allow scheduling slack). A non-deducted path would
    # pass ``full_budget_s`` exactly.
    assert agent_deadline < full_budget_s - setup_delay + 1.0, (
        f"agent deadline {agent_deadline}s was not deducted by the setup "
        f"elapsed time {setup_delay}s — full budget {full_budget_s}s was "
        f"passed through verbatim; total wall-clock={elapsed:.2f}s"
    )
    assert agent_deadline <= full_budget_s - setup_delay + 0.5, (
        "agent deadline must reflect (timeout - setup_elapsed); today's "
        "non-deducted code passes timeout through verbatim"
    )


__all__ = [
    "test_hanging_setup_script_is_killed_at_deadline",
    "test_setup_script_grandchildren_are_reaped",
    "test_setup_timeout_exceeding_run_budget_raises_configuration_error",
    "test_setup_timeout_is_deducted_from_the_run_budget",
    "test_timed_out_setup_script_yields_inconclusive",
]
