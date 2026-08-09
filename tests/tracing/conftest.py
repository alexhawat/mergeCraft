"""Shared fixtures for tracing contract tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def trace_dir(tmp_path: Path) -> Path:
    return tmp_path / ".mergecraft" / "traces"


@pytest.fixture
def fake_attrs() -> dict[str, Any]:
    return {"model.id": "anthropic/claude-sonnet", "attempt": 1}


@pytest.fixture
def trace_event_data(fake_attrs: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "llm.call",
        "span_id": "span-1",
        "parent_span_id": None,
        "session_id": "run-1",
        "turn_id": "turn-1",
        "tier": "trusted",
        "ts_start_ns": 1_000,
        "ts_end_ns": 2_000,
        "status": "ok",
        "attrs": fake_attrs,
    }
