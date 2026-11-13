"""Independent analyzer adapters overlap with bounded, deterministic collection."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pytest

from mergecraft.analyzers import adapters, pipeline
from mergecraft.analyzers.registry import get_manifest
from mergecraft.config import RepoSettings


def test_adapters_overlap_and_keep_manifest_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool_ids = ["ruff", "bandit", "vulture", "mypy", "pyright", "basedpyright"]
    settings = RepoSettings()
    monkeypatch.setattr(pipeline, "load_repo_settings", lambda **_kwargs: settings)
    monkeypatch.setattr(
        pipeline, "detect_enabled", lambda **_kwargs: [get_manifest(tool) for tool in tool_ids]
    )
    lock = threading.Lock()
    active = 0
    peak = 0

    def run_adapter(**kwargs: Any) -> adapters.AdapterRunResult:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.08 if kwargs["tool_id"] == "ruff" else 0.04)
        with lock:
            active -= 1
        return adapters.AdapterRunResult(findings=[])

    monkeypatch.setattr(adapters, "run_adapter", run_adapter)
    state = pipeline.run_analyzer_pipeline(
        repo_root=tmp_path, changed_files=["a.py"], tier="trusted", shell="restricted", offline=True
    )
    assert 2 <= peak <= 4
    assert [row.id for row in state.analyzers] == tool_ids
    assert all(row.status == "passed" for row in state.analyzers)


def test_fatal_adapter_failure_reaps_only_its_pipeline_children(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A collector failure cancels worker processes before propagating."""
    import subprocess
    import sys

    import pytest

    from mergecraft.analyzers.run import _run_in_own_session

    tool_ids = ["ruff", "bandit", "vulture", "mypy", "pyright", "basedpyright"]
    monkeypatch.setattr(pipeline, "load_repo_settings", lambda **_kwargs: RepoSettings())
    monkeypatch.setattr(
        pipeline, "detect_enabled", lambda **_kwargs: [get_manifest(tool) for tool in tool_ids]
    )
    ready = threading.Event()
    lock = threading.Lock()
    processes: list[subprocess.Popen[str]] = []
    original_popen = subprocess.Popen
    unrelated = original_popen([sys.executable, "-c", "import time; time.sleep(30)"])

    def spawn(*args: Any, **kwargs: Any) -> subprocess.Popen[str]:
        process = original_popen(*args, **kwargs)
        with lock:
            processes.append(process)
            if len(processes) >= 3:
                ready.set()
        return process

    monkeypatch.setattr(subprocess, "Popen", spawn)

    def run_adapter(**kwargs: Any) -> adapters.AdapterRunResult:
        if kwargs["tool_id"] == "ruff":
            assert ready.wait(5), "the other workers must start before the fatal result"
            raise RuntimeError("fatal adapter failure")
        _run_in_own_session(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            cwd=tmp_path,
            timeout_s=5,
            env={"PATH": "/usr/bin:/bin"},
            pass_fds=(),
            preexec_fn=None,
        )
        return adapters.AdapterRunResult(findings=[])

    monkeypatch.setattr(adapters, "run_adapter", run_adapter)
    started = time.monotonic()
    try:
        with pytest.raises(RuntimeError, match="fatal adapter failure"):
            pipeline.run_analyzer_pipeline(
                repo_root=tmp_path,
                changed_files=["a.py"],
                tier="trusted",
                shell="restricted",
                offline=True,
            )
        assert time.monotonic() - started < 2, "shutdown must not wait for analyzer timeouts"
        assert all(process.poll() is not None for process in processes)
        assert unrelated.poll() is None, "another review's subprocess must remain alive"
    finally:
        for process in [unrelated, *processes]:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
