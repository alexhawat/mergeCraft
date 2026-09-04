"""``mergecraft run inspect`` / ``mergecraft run diff`` — stored review runs (#377).

Distinct from ``mergecraft analyzers run``. Output-only.

Exports: ``app``
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich.table import Table

from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE
from mergecraft.cli.global_surface import emit_cli_json, wants_json_output
from mergecraft.tracing.trace_jsonl import (
    default_trace_dir,
    load_trace_jsonl_events,
    session_ids_in_trace_order,
)

app = typer.Typer(
    name="run",
    help="Inspect and compare stored review runs (not analyzer execution).",
    no_args_is_help=True,
)


def _load_events(trace_dir: Path) -> list[dict[str, Any]]:
    return load_trace_jsonl_events(trace_dir)


def _sessions(events: list[dict[str, Any]]) -> list[str]:
    return session_ids_in_trace_order(events)


def _kinds_for(events: list[dict[str, Any]], run_id: str) -> set[str]:
    return {
        str(event.get("kind", ""))
        for event in events
        if event.get("session_id") == run_id and event.get("kind")
    }


def _render_table(title: str, payload: dict[str, Any]) -> Table:
    table = Table(title=title, show_header=True, header_style="bold")
    table.add_column("field")
    table.add_column("value")
    for key, value in payload.items():
        if key == "schema_version":
            continue
        table.add_row(str(key), json.dumps(value) if isinstance(value, list | dict) else str(value))
    return table


def _emit(ctx: typer.Context, *, title: str, payload: dict[str, Any]) -> None:
    if wants_json_output(ctx, json_flag=False):
        emit_cli_json(payload)
        raise typer.Exit(CLI_SUCCESS_EXIT_CODE)
    console.print(_render_table(title, payload))
    raise typer.Exit(CLI_SUCCESS_EXIT_CODE)


@app.command("inspect")
def inspect_cmd(
    ctx: typer.Context,
    run_id: str | None = typer.Argument(
        default=None,
        help="Optional run id to inspect. Without it, list stored run ids.",
    ),
    trace_dir: Path | None = typer.Option(
        None,
        "--trace-dir",
        help="Override $MERGECRAFT_TRACE_DIR for this invocation.",
    ),
) -> None:
    """Inspect a stored review run (or list known run ids)."""
    target = trace_dir if trace_dir is not None else default_trace_dir()
    events = _load_events(target)
    sessions = _sessions(events)
    chosen = run_id or (sessions[-1] if sessions else None)
    matching = [event for event in events if chosen and event.get("session_id") == chosen]
    payload: dict[str, Any] = {
        "verb": "inspect",
        "run_id": chosen,
        "found": bool(matching),
        "event_count": len(matching),
        "runs": sessions,
    }
    _emit(ctx, title="mergecraft run inspect", payload=payload)


@app.command("diff")
def diff_cmd(
    ctx: typer.Context,
    run_a: str | None = typer.Argument(
        default=None,
        help="First run id. Optional when comparing the two most recent traced runs.",
    ),
    run_b: str | None = typer.Argument(
        default=None,
        help="Second run id.",
    ),
    trace_dir: Path | None = typer.Option(
        None,
        "--trace-dir",
        help="Override $MERGECRAFT_TRACE_DIR for this invocation.",
    ),
) -> None:
    """Compare two stored review runs by event kind."""
    target = trace_dir if trace_dir is not None else default_trace_dir()
    events = _load_events(target)
    sessions = _sessions(events)
    left = run_a
    right = run_b
    if left is None and right is None and len(sessions) >= 2:
        left, right = sessions[-2], sessions[-1]
    kinds_a = _kinds_for(events, left) if left else set()
    kinds_b = _kinds_for(events, right) if right else set()
    payload: dict[str, Any] = {
        "verb": "diff",
        "run_a": left,
        "run_b": right,
        "only_in_a": sorted(kinds_a - kinds_b),
        "only_in_b": sorted(kinds_b - kinds_a),
        "shared": sorted(kinds_a & kinds_b),
        "runs": sessions,
    }
    _emit(ctx, title="mergecraft run diff", payload=payload)


__all__ = ["app", "diff_cmd", "inspect_cmd"]
