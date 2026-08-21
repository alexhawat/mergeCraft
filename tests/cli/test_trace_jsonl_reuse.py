"""JSONL reuse: replay/run inspect share ``load_trace_jsonl_events``."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.trace_jsonl import default_trace_dir, load_trace_jsonl_events

if TYPE_CHECKING:
    import pytest

runner = CliRunner()
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}


def test_replay_and_run_cmd_use_shared_jsonl_loader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Happy: ``replay`` and ``run inspect`` both call ``load_trace_jsonl_events``."""
    calls: list[Path] = []
    events = [{"session_id": "s1", "kind": "span"}]

    def _load(trace_dir: Path) -> list[dict[str, Any]]:
        calls.append(trace_dir)
        return events

    monkeypatch.setattr("mergecraft.cli.trace_jsonl.load_trace_jsonl_events", _load)
    monkeypatch.setattr("mergecraft.cli.replay_cmd.load_trace_jsonl_events", _load)
    monkeypatch.setattr("mergecraft.cli.run_cmd.load_trace_jsonl_events", _load)
    replay = runner.invoke(app, ["replay", "--trace-dir", str(tmp_path / "traces")], env=_DUMB_ENV)
    inspect_run = runner.invoke(
        app, ["run", "inspect", "--trace-dir", str(tmp_path / "traces")], env=_DUMB_ENV
    )
    assert replay.exit_code == 0, replay.stdout + replay.stderr
    assert inspect_run.exit_code == 0, inspect_run.stdout + inspect_run.stderr
    assert len(calls) >= 2


def test_default_trace_dir_reads_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Happy: ``default_trace_dir`` honors ``MERGECRAFT_TRACE_DIR``."""
    target = tmp_path / "custom-traces"
    monkeypatch.setenv("MERGECRAFT_TRACE_DIR", str(target))
    assert default_trace_dir() == target


def test_default_trace_dir_falls_back_to_mergecraft_traces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Edge: unset env uses ``.mergecraft/traces``."""
    monkeypatch.delenv("MERGECRAFT_TRACE_DIR", raising=False)
    assert default_trace_dir() == Path(".mergecraft/traces")


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
