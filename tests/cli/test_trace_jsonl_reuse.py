"""JSONL reuse: replay/run inspect share ``load_trace_jsonl_events``."""

from __future__ import annotations

import inspect
from pathlib import Path

from mergecraft.cli.trace_jsonl import load_trace_jsonl_events


def test_replay_and_run_cmd_use_shared_jsonl_loader() -> None:
    """Unit: no duplicated ``json.loads`` glob in replay / run inspect."""
    from mergecraft.cli import replay_cmd, run_cmd

    replay_src = inspect.getsource(replay_cmd)
    run_src = inspect.getsource(run_cmd)
    assert "load_trace_jsonl_events" in replay_src
    assert "load_trace_jsonl_events" in run_src
    assert "from mergecraft.cli.trace_jsonl import load_trace_jsonl_events" in replay_src
    assert "from mergecraft.cli.trace_jsonl import load_trace_jsonl_events" in run_src
    assert 'glob("*.jsonl")' not in replay_src
    assert 'glob("*.jsonl")' not in run_src


def test_load_trace_jsonl_events_skips_malformed_lines(tmp_path: Path) -> None:
    """Edge: malformed JSONL lines are skipped; valid objects are kept."""
    trace_dir = tmp_path / "traces"
    trace_dir.mkdir()
    (trace_dir / "run.jsonl").write_text(
        '{"session_id":"ok","kind":"span"}\nnot-json\n{"session_id":"two"}\n',
        encoding="utf-8",
    )
    events = load_trace_jsonl_events(trace_dir)
    assert [event.get("session_id") for event in events] == ["ok", "two"]


def test_load_trace_jsonl_events_missing_dir_returns_empty(tmp_path: Path) -> None:
    """Edge: a missing trace directory is an empty list, not OSError."""
    assert load_trace_jsonl_events(tmp_path / "missing-traces") == []
