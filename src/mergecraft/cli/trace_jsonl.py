"""Shared JSONL trace loading for ``replay`` / ``run inspect`` / ``run diff``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mergecraft.tracing.sinks import read_jsonl_events


def load_trace_jsonl_events(trace_dir: Path) -> list[dict[str, Any]]:
    """Parse every ``*.jsonl`` file under ``trace_dir`` via the tracing sink reader."""
    if not trace_dir.is_dir():
        return []
    matched: list[dict[str, Any]] = []
    for jsonl_path in sorted(trace_dir.glob("*.jsonl")):
        try:
            events = read_jsonl_events(jsonl_path)
        except OSError:
            continue
        for event in events:
            if isinstance(event, dict):
                matched.append(event)
    return matched


__all__ = ["load_trace_jsonl_events"]
