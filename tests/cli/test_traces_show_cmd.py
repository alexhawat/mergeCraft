"""``mergecraft traces show <run-id>`` and its ``traces <run-id>`` synonym (#1338)."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from mergecraft.cli.app import app

if TYPE_CHECKING:
    from pathlib import Path

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_ENV = {"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "200"}


def _trace_dir(tmp_path: Path) -> Path:
    """Write one span for ``run-42`` and return the trace directory."""
    trace_dir = tmp_path / "traces"
    trace_dir.mkdir()
    span = {"kind": "mergecraft.run", "span_id": "root-span", "session_id": "run-42", "attrs": {}}
    (trace_dir / "2026-11-12.jsonl").write_text(json.dumps(span) + "\n", encoding="utf-8")
    return trace_dir


_SPELLINGS = [
    ["traces", "show", "run-42"],
    ["traces", "run-42"],
    ["traces", "show", "--trace-dir", "{dir}", "run-42"],
    ["traces", "--trace-dir", "{dir}", "run-42"],
    ["traces", "run-42", "--trace-dir", "{dir}"],
]


@pytest.mark.parametrize(
    "argv",
    _SPELLINGS,
    ids=["show", "synonym", "show-option-first", "synonym-option-first", "synonym-option-last"],
)
def test_traces_spellings_read_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, argv: list[str]
) -> None:
    """Every documented spelling resolves to the run's spans."""
    trace_dir = _trace_dir(tmp_path)
    monkeypatch.setenv("MERGECRAFT_TRACE_DIR", str(trace_dir))
    args = [a.replace("{dir}", str(trace_dir)) for a in argv]

    result = CliRunner().invoke(app, args, env={**_ENV, "MERGECRAFT_TRACE_DIR": str(trace_dir)})

    out = _ANSI.sub("", result.stdout + result.stderr)
    assert result.exit_code == 0, out
    assert "root-span" in out, out
    assert "No such command" not in out


def test_traces_show_unknown_run_names_the_run_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``traces show`` reports the requested id, never the word ``show``."""
    trace_dir = _trace_dir(tmp_path)
    monkeypatch.setenv("MERGECRAFT_TRACE_DIR", str(trace_dir))

    result = CliRunner().invoke(
        app, ["traces", "show", "other-run"], env={**_ENV, "MERGECRAFT_TRACE_DIR": str(trace_dir)}
    )

    out = _ANSI.sub("", result.stdout + result.stderr)
    assert result.exit_code == 0, out
    assert "No spans found for run id other-run" in " ".join(out.split()), out


def test_traces_without_run_id_prints_help() -> None:
    """A bare ``traces`` prints the group help, which names the run-id form."""
    result = CliRunner().invoke(app, ["traces"], env=_ENV)
    out = _ANSI.sub("", result.stdout + result.stderr)
    assert result.exit_code == 0, out
    assert "show" in out
    assert "RUN_ID" in out
