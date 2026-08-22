"""Shared JSONL trace loading for ``replay`` / ``run inspect`` / ``run diff``."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mergecraft.tracing.sinks import read_jsonl_events


def default_trace_dir() -> Path:
    """Resolve ``MERGECRAFT_TRACE_DIR`` or the default ``.mergecraft/traces`` path."""
    env_dir = os.environ.get("MERGECRAFT_TRACE_DIR")
    if env_dir:
        return Path(env_dir)
    return Path(".mergecraft/traces")


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


def session_ids_in_trace_order(events: list[dict[str, Any]]) -> list[str]:
    """Return unique ``session_id`` values ordered by earliest trace timestamp.

    UUID4 (and operator-supplied) ids are not chronological; lexicographic sort
    would pick the wrong default for ``replay`` / ``run inspect`` / ``run diff``.
    """
    first_index: dict[str, int] = {}
    min_ts: dict[str, int] = {}
    for idx, event in enumerate(events):
        raw = event.get("session_id")
        if raw is None or raw == "":
            continue
        session_id = str(raw)
        if session_id not in first_index:
            first_index[session_id] = idx
        ts = event.get("ts_start_ns")
        if isinstance(ts, int) and (session_id not in min_ts or ts < min_ts[session_id]):
            min_ts[session_id] = ts

    def _sort_key(session_id: str) -> tuple[int, int, int]:
        if session_id in min_ts:
            return (0, min_ts[session_id], first_index[session_id])
        return (1, first_index[session_id], 0)

    return sorted(first_index, key=_sort_key)


__all__ = ["default_trace_dir", "load_trace_jsonl_events", "session_ids_in_trace_order"]
