"""The sandbox pre-exec must widen ``RLIMIT_NPROC`` for a shared drop target.

The sudo-elevated drop lands on the orchestrator's own uid. A credential-changing
``execve`` (``setpriv --reuid``) is refused with ``EAGAIN`` when that target
real-uid already exceeds the sandbox's ``RLIMIT_NPROC``, so a flat ``(max, max)``
cap made the drop fail on a busy runner
(``setpriv: failed to execute /bin/bash: Resource temporarily unavailable``).

The cap cannot be sized from a ``/proc`` count: inside a PID namespace — the CI
harness runs pytest under ``unshare --pid --mount-proc`` — that count reads zero
for a uid the kernel still knows is busy in the parent namespace. The runner
therefore resolves the target identity and derives the pair by probing the
kernel's own answer (the real credential-changing exec, stepped upward while it
is refused) in the parent, before the fork, and hands the pair to the pre-exec.
With no drop it stays exactly ``(max, max)`` and the probe is never reached.
"""

from __future__ import annotations

import resource
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from mergecraft.analyzers import run as run_mod
from mergecraft.analyzers import sandbox as sandbox_mod
from mergecraft.analyzers.resolve import AnalyzerPlan
from mergecraft.analyzers.run import run_plan
from mergecraft.mcp import shell as shell_mod
from tests.analyzers.support_sandbox_limits import (
    ProbeAttempt,
    install_probe,
    patch_drop_target,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_MAX_PROCESSES = 16


@pytest.fixture(autouse=True)
def _reset_caches() -> None:
    shell_mod.reset_detection_cache()
    sandbox_mod.reset_detection_cache()


def _full_caps() -> sandbox_mod.SandboxCapabilities:
    return sandbox_mod.SandboxCapabilities(
        pid_namespace=True,
        network_namespace=True,
        read_only_bind=True,
        tmpfs=True,
        cgroup_memory=False,
        rlimit_nproc=True,
        pid_namespace_method="unshare",
        user_namespace=True,
    )


def _sandbox_context(tmp_path: Path) -> sandbox_mod.SandboxContext:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    return sandbox_mod.build_sandbox_context(
        repo_root=tmp_path,
        scratch_dir=scratch,
        limits=sandbox_mod.SandboxLimits(timeout_s=30, memory_mb=256, max_processes=_MAX_PROCESSES),
        network_allowlist=[],
        read_only_source=True,
        caps=_full_caps(),
    )


def _pin_resolvers(
    monkeypatch: pytest.MonkeyPatch, *, target_uid: int | None, target_gid: int | None
) -> None:
    """Pin the drop-target resolution in both the sandbox module and ``run``'s namespace."""
    for module in (sandbox_mod, run_mod):
        patch_drop_target(monkeypatch, module, uid=target_uid, gid=target_gid)


def _pin_resolved_pair(
    monkeypatch: pytest.MonkeyPatch,
    *,
    target_uid: int | None,
    target_gid: int | None,
    pair: tuple[int, int],
) -> list[tuple[int, int | None, int | None]]:
    """Pin the resolved target and the derived pair; record every ``process_limit_for_drop`` call."""
    calls: list[tuple[int, int | None, int | None]] = []
    _pin_resolvers(monkeypatch, target_uid=target_uid, target_gid=target_gid)

    def _limit(
        max_processes: int, *, target_uid: int | None, target_gid: int | None
    ) -> tuple[int, int]:
        calls.append((max_processes, target_uid, target_gid))
        return pair

    for module in (sandbox_mod, run_mod):
        monkeypatch.setattr(module, "process_limit_for_drop", _limit, raising=False)
    return calls


def _install_sandbox_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shell_mod, "detect_sandbox_method", lambda: "unshare")
    monkeypatch.setattr(sandbox_mod, "probe_capabilities", _full_caps)
    shell_mod._reset_shell_detection_globals()


def _drive_sandboxed_spawn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    limits: list[tuple[int, tuple[int, int]]],
    before_fork: Callable[[], None],
) -> Callable[[], None]:
    """Run a sandboxed plan and return the pre-exec it passes to ``subprocess.run``."""
    monkeypatch.setattr(resource, "setrlimit", lambda which, value: limits.append((which, value)))
    _install_sandbox_spawn(monkeypatch)
    captured: dict[str, object] = {}

    def _run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        before_fork()
        captured.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", _run)
    plan = AnalyzerPlan(manifest_id="probe", argv=("true",), cwd=tmp_path, mode="native")
    run_plan(plan, sandbox_context=_sandbox_context(tmp_path))
    preexec = captured.get("preexec_fn")
    assert callable(preexec), "the sandboxed spawn must carry a pre-exec"
    return preexec


def _nproc_limits(limits: list[tuple[int, tuple[int, int]]]) -> list[tuple[int, int]]:
    return [value for which, value in limits if which == resource.RLIMIT_NPROC]


def test_sandboxed_preexec_widens_nproc_for_the_drop_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The resolved drop identity drives the pair the pre-exec installs, before the fork."""
    calls = _pin_resolved_pair(monkeypatch, target_uid=1001, target_gid=2002, pair=(56, 56))
    limits: list[tuple[int, tuple[int, int]]] = []

    def _before_fork() -> None:
        assert calls, "the drop cap must be resolved before the fork"

    preexec = _drive_sandboxed_spawn(monkeypatch, tmp_path, limits=limits, before_fork=_before_fork)
    preexec()

    assert calls == [(_MAX_PROCESSES, 1001, 2002)]
    nproc = _nproc_limits(limits)
    assert nproc == [(56, 56)]
    assert nproc[0][0] - 40 == _MAX_PROCESSES, "the additional allowance must stay max_processes"


def test_sandboxed_preexec_keeps_the_flat_nproc_without_a_drop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no drop the historical ``(max, max)`` cap is exactly preserved."""
    calls = _pin_resolved_pair(monkeypatch, target_uid=None, target_gid=None, pair=(16, 16))
    limits: list[tuple[int, tuple[int, int]]] = []

    preexec = _drive_sandboxed_spawn(monkeypatch, tmp_path, limits=limits, before_fork=lambda: None)
    preexec()

    assert _nproc_limits(limits) == [(_MAX_PROCESSES, _MAX_PROCESSES)]
    assert calls == [(_MAX_PROCESSES, None, None)]


def test_sandboxed_preexec_no_drop_never_reaches_the_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real ``process_limit_for_drop`` short-circuits without probing when no drop applies."""
    _pin_resolvers(monkeypatch, target_uid=None, target_gid=None)
    attempt = ProbeAttempt(succeed_at=None)
    install_probe(monkeypatch, sandbox_mod, attempt)
    limits: list[tuple[int, tuple[int, int]]] = []

    preexec = _drive_sandboxed_spawn(monkeypatch, tmp_path, limits=limits, before_fork=lambda: None)
    preexec()

    assert _nproc_limits(limits) == [(_MAX_PROCESSES, _MAX_PROCESSES)]
    assert attempt.attempts == [], "no probe may run when no drop applies"


def test_sandboxed_preexec_probes_the_drop_cap_before_the_fork(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The kernel probe runs in the parent before the fork and never inside the pre-exec."""
    _pin_resolvers(monkeypatch, target_uid=1001, target_gid=2002)
    monkeypatch.setattr(sandbox_mod, "process_count_for_uid", lambda *_a, **_k: 0, raising=False)
    attempt = ProbeAttempt(succeed_at=48)
    install_probe(monkeypatch, sandbox_mod, attempt)
    limits: list[tuple[int, tuple[int, int]]] = []
    attempts_before_fork: list[int] = []

    def _before_fork() -> None:
        attempts_before_fork.append(len(attempt.attempts))

    preexec = _drive_sandboxed_spawn(monkeypatch, tmp_path, limits=limits, before_fork=_before_fork)
    assert attempts_before_fork, "the drop cap must be probed before the fork"
    assert attempts_before_fork[0] >= 1
    preexec()

    assert attempt.attempts == [16, 32, 48], "the pre-exec must not probe again"
    assert _nproc_limits(limits) == [(48, 48)]
