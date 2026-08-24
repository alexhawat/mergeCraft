"""Shared JSONL trace loading for CLI replay/inspect and durable review artifacts."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mergecraft.tracing.sinks import read_jsonl_events


def default_trace_dir(*, repo_root: Path | None = None) -> Path:
    """Resolve ``MERGECRAFT_TRACE_DIR`` or the default ``.mergecraft/traces`` path."""
    env_dir = os.environ.get("MERGECRAFT_TRACE_DIR")
    if env_dir:
        return Path(env_dir)
    if repo_root is not None:
        return repo_root / ".mergecraft" / "traces"
    return Path(".mergecraft/traces")


def load_trace_jsonl_events(
    trace_dir: Path,
    *,
    session_id: str | None = None,
) -> list[dict[str, Any]]:
    """Parse ``*.jsonl`` files under ``trace_dir``, optionally filtering by session."""
    if not trace_dir.is_dir():
        return []
    matched: list[dict[str, Any]] = []
    for jsonl_path in sorted(trace_dir.glob("*.jsonl")):
        try:
            events = read_jsonl_events(jsonl_path)
        except OSError:
            continue
        for event in events:
            if not isinstance(event, dict):
                continue
            if session_id is not None and str(event.get("session_id", "")) != session_id:
                continue
            matched.append(event)
    return matched


def session_ids_in_trace_order(events: list[dict[str, Any]]) -> list[str]:
    """Return unique ``session_id`` values ordered by earliest trace timestamp."""
    first_index: dict[str, int] = {}
    min_ts: dict[str, int] = {}
    for idx, event in enumerate(events):
        raw = event.get("session_id")
        if raw is None or raw == "":
            continue
        session = str(raw)
        if session not in first_index:
            first_index[session] = idx
        ts = event.get("ts_start_ns")
        if isinstance(ts, int) and (session not in min_ts or ts < min_ts[session]):
            min_ts[session] = ts

    def _sort_key(session: str) -> tuple[int, int, int]:
        if session in min_ts:
            return (0, min_ts[session], first_index[session])
        return (1, first_index[session], 0)

    return sorted(first_index, key=_sort_key)


__all__ = ["default_trace_dir", "load_trace_jsonl_events", "session_ids_in_trace_order"]
