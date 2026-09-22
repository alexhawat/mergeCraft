"""Behavioral suite for ``reliability/recovery.py`` (plan 29 T3 / #768).

The prior coverage asserted only ``outcome.cleaned is True`` — a terminal
assertion that cannot observe whether cleanup did anything, and cannot fail
when the kill helper is skipped. These tests observe the cleanup itself:

- every recognised failure mode delegates to the process-group kill helper;
- a registered process group is genuinely terminated by the cleanup call;
- when the helper cannot complete, cleanup fails loudly instead of returning a
  ``cleaned=True`` outcome it did not earn;
- the mode guard rejects an unknown mode *before* any process is signalled.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from mergecraft.reliability import recovery
from mergecraft.reliability.recovery import CLEANUP_FAILURE_MODES, cleanup_on_failure
from mergecraft.utils import process_group


@pytest.mark.parametrize("mode", sorted(CLEANUP_FAILURE_MODES))
def test_cleanup_invokes_the_process_group_kill_for_every_mode(
    mode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each named failure mode must reach the kill helper (not just set a flag)."""
    calls: list[int] = []

    def _record() -> None:
        calls.append(1)

    monkeypatch.setattr(recovery, "kill_all_active_process_groups", _record)

    outcome = cleanup_on_failure(mode)

    assert calls == [1], f"cleanup for {mode!r} never invoked the kill helper"
    assert outcome.cleaned is True
    assert outcome.status == "degraded"


def test_cleanup_terminates_a_registered_process_group(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end: a registered sleeper is actually killed by cleanup.

    ``active_process_groups`` is scoped to this test's sleeper so the real
    ``killpg`` path runs without touching any other registered pid.
    """
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    monkeypatch.setattr(process_group, "active_process_groups", lambda: frozenset({proc.pid}))
    try:
        outcome = cleanup_on_failure("timeout")
        assert outcome.cleaned is True
        assert proc.wait(timeout=5) is not None
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_cleanup_failure_is_not_reported_as_cleaned(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the kill helper fails, cleanup must not claim ``cleaned=True``.

    Deleting the propagation (e.g. wrapping the helper in ``suppress``) makes
    this raise nothing and the test fails — a swallowed failure is the defect
    the terminal assertion could not see.
    """

    def _boom() -> None:
        raise RuntimeError("killpg unavailable")

    monkeypatch.setattr(recovery, "kill_all_active_process_groups", _boom)

    with pytest.raises(RuntimeError, match="killpg unavailable"):
        cleanup_on_failure("provider_crash")


@pytest.mark.parametrize("mode", ["", "TIMEOUT", "timeout ", "cancel", "reboot"])
def test_unknown_mode_raises_before_signalling_anything(
    mode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mode guard runs first: an unknown mode never signals a process group."""
    calls: list[int] = []
    monkeypatch.setattr(recovery, "kill_all_active_process_groups", lambda: calls.append(1))

    with pytest.raises(ValueError, match="unknown cleanup failure mode"):
        cleanup_on_failure(mode)

    assert calls == [], f"unknown mode {mode!r} still ran cleanup"


def test_cancellation_is_the_accepted_name_not_cancel() -> None:
    """``cancellation`` is in the vocabulary; the colloquial ``cancel`` is not."""
    assert "cancellation" in CLEANUP_FAILURE_MODES
    assert "cancel" not in CLEANUP_FAILURE_MODES


__all__: list[str] = []
