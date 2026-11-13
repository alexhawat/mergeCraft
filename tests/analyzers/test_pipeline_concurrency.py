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
