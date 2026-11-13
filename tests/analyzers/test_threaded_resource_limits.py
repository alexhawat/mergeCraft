"""Concurrent analyzer launches apply limits without Python callbacks after fork."""

from __future__ import annotations

import json
import resource
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from mergecraft.analyzers.run import _run_in_own_session, _SandboxLimits
from mergecraft.analyzers.sandbox import SandboxContext


def test_threaded_launch_applies_limits_without_preexec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = SandboxContext(
        repo_root=tmp_path,
        scratch_dir=tmp_path,
        timeout_s=5,
        memory_mb=512 if sys.platform == "linux" else 0,
        max_processes=256,
        network_allowlist=[],
        read_only_source=True,
        source_mount_read_only=True,
        network_default="deny",
    )
    expected_memory = (
        [512 * 1024**2] * 2
        if sys.platform == "linux"
        else list(resource.getrlimit(resource.RLIMIT_AS))
    )
    pair = (resource.getrlimit(resource.RLIMIT_NPROC)[0],) * 2
    limits = _SandboxLimits(context, process_limit=pair)
    spawn = subprocess.Popen
    callbacks = []

    def popen(*args: Any, **kwargs: Any) -> Any:
        callbacks.append(kwargs.get("preexec_fn"))
        return spawn(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", popen)
    script = (
        "import json,resource; print(json.dumps([resource.getrlimit(resource.RLIMIT_NPROC), "
        "resource.getrlimit(resource.RLIMIT_AS)]))"
    )

    def launch(_: int) -> subprocess.CompletedProcess[str]:
        return _run_in_own_session(
            [sys.executable, "-I", "-c", script],
            cwd=tmp_path,
            timeout_s=5,
            env={"PATH": "/usr/bin:/bin"},
            pass_fds=(),
            preexec_fn=limits,
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(launch, range(8)))
    assert all(result.returncode == 0 for result in results)
    assert [json.loads(result.stdout) for result in results] == [[list(pair), expected_memory]] * 8
    assert callbacks == [None] * 8


def test_invalid_child_limits_never_execute_payload(tmp_path: Path) -> None:
    context = SandboxContext(
        repo_root=tmp_path,
        scratch_dir=tmp_path,
        timeout_s=5,
        memory_mb=0,
        max_processes=256,
        network_allowlist=[],
        read_only_source=True,
        source_mount_read_only=True,
        network_default="deny",
    )
    marker = tmp_path / "executed"
    result = _run_in_own_session(
        [sys.executable, "-I", "-c", "from pathlib import Path; Path('executed').touch()"],
        cwd=tmp_path,
        timeout_s=5,
        env={"PATH": "/usr/bin:/bin"},
        pass_fds=(),
        preexec_fn=_SandboxLimits(context, process_limit=(-2, -2)),
    )
    assert result.returncode != 0
    assert not marker.exists()


def test_limited_child_timeout_is_reaped(tmp_path: Path) -> None:
    context = SandboxContext(
        repo_root=tmp_path,
        scratch_dir=tmp_path,
        timeout_s=1,
        memory_mb=0,
        max_processes=256,
        network_allowlist=[],
        read_only_source=True,
        source_mount_read_only=True,
        network_default="deny",
    )
    pair = (resource.getrlimit(resource.RLIMIT_NPROC)[0],) * 2
    with pytest.raises(subprocess.TimeoutExpired):
        _run_in_own_session(
            [sys.executable, "-I", "-c", "import time; time.sleep(30)"],
            cwd=tmp_path,
            timeout_s=1,
            env={"PATH": "/usr/bin:/bin"},
            pass_fds=(),
            preexec_fn=_SandboxLimits(context, process_limit=pair),
        )


def test_threaded_sandbox_calibration_never_uses_preexec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real sandbox wrapper calibrates root drops from analyzer workers."""
    import threading

    from mergecraft.analyzers import run, sandbox
    from mergecraft.analyzers.resolve import AnalyzerPlan

    context = SandboxContext(
        repo_root=tmp_path,
        scratch_dir=tmp_path,
        timeout_s=5,
        memory_mb=0,
        max_processes=16,
        network_allowlist=[],
        read_only_source=True,
        source_mount_read_only=True,
        network_default="deny",
    )
    monkeypatch.setattr(sandbox.os, "geteuid", lambda: 0)
    monkeypatch.setattr(sandbox.shutil, "which", lambda _name: "/usr/bin/setpriv")
    monkeypatch.setattr(sandbox, "resolve_drop_target_uid", lambda: 1001)
    monkeypatch.setattr(sandbox, "resolve_drop_target_gid", lambda: 1001)
    monkeypatch.setattr(sandbox, "process_count_for_uid", lambda _uid: 0)
    monkeypatch.setattr(
        sandbox, "build_analyzer_sandbox_argv_for_run", lambda argv, **_kwargs: list(argv)
    )
    launches: list[tuple[str, dict[str, Any]]] = []

    def launch(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        launches.append((threading.current_thread().name, kwargs))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", launch)
    plan = AnalyzerPlan(manifest_id="ruff", mode="managed", argv=("ruff", "check", "."))
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="analyzer") as pool:
        results = list(pool.map(lambda _: run._sandboxed_argv(plan, context), range(2)))

    assert len(launches) == 2
    assert all(thread.startswith("analyzer") for thread, _ in launches)
    assert all(limits is not None and limits.process_limit == (32, 32) for _, limits in results)
    assert all(options.get("preexec_fn") is None for _, options in launches)
