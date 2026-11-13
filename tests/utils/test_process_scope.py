"""Nested operation scopes cancel only owned children, including late spawns."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.analyzers.run import _run_in_own_session
from mergecraft.utils.process_group import track_process_group
from mergecraft.utils.process_scope import ProcessGroupScope, bind_process_group_scope

if TYPE_CHECKING:
    from pathlib import Path


def test_inner_cancellation_keeps_an_outer_sibling_alive() -> None:
    outer, inner = ProcessGroupScope(), ProcessGroupScope()
    command = [sys.executable, "-c", "import time; time.sleep(30)"]
    with (
        bind_process_group_scope(outer),
        subprocess.Popen(command, start_new_session=True) as sibling,
        track_process_group(sibling),
    ):
        try:
            with (
                bind_process_group_scope(inner),
                subprocess.Popen(command, start_new_session=True) as child,
                track_process_group(child),
            ):
                inner.cancel()
                child.wait(timeout=5)
                assert sibling.poll() is None
                assert not outer.cancelled.is_set()
        finally:
            outer.cancel()
            sibling.wait(timeout=5)


def test_outer_cancellation_reaches_nested_child() -> None:
    outer, inner = ProcessGroupScope(), ProcessGroupScope()
    command = [sys.executable, "-c", "import time; time.sleep(30)"]
    with (
        bind_process_group_scope(outer),
        bind_process_group_scope(inner),
        subprocess.Popen(command, start_new_session=True) as child,
        track_process_group(child),
    ):
        outer.cancel()
        child.wait(timeout=5)
        assert child.poll() is not None


def test_cancelled_scope_refuses_analyzer_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = ProcessGroupScope()
    scope.cancel()

    def unexpected_spawn(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("cancelled operation spawned another analyzer")

    monkeypatch.setattr(subprocess, "Popen", unexpected_spawn)
    with bind_process_group_scope(scope), pytest.raises(asyncio.CancelledError):
        _run_in_own_session(
            [sys.executable, "-c", "pass"],
            cwd=tmp_path,
            timeout_s=5,
            env={},
            pass_fds=(),
            preexec_fn=None,
        )


def test_child_spawned_during_cancellation_is_killed_and_reaped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = ProcessGroupScope()
    original_popen = subprocess.Popen
    children: list[subprocess.Popen[str]] = []

    def spawn(*args: Any, **kwargs: Any) -> subprocess.Popen[str]:
        child = original_popen(*args, **kwargs)
        children.append(child)
        scope.cancel()  # Before track_process_group can register the new child.
        return child

    monkeypatch.setattr(subprocess, "Popen", spawn)
    with bind_process_group_scope(scope), pytest.raises(asyncio.CancelledError):
        _run_in_own_session(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            cwd=tmp_path,
            timeout_s=5,
            env={},
            pass_fds=(),
            preexec_fn=None,
        )
    assert len(children) == 1
    assert children[0].poll() is not None
