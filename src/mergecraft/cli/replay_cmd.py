"""``mergecraft replay`` — output-only replay of a stored review run (#377).

Distinct from ``mergecraft eval replay`` (eval-bank cases).

Exports: ``run``
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
from rich.table import Table

from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.errors import cli_bail
from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE, CLI_USAGE_EXIT_CODE
from mergecraft.cli.global_surface import emit_cli_json, wants_json_output
from mergecraft.cli.trace_jsonl import (
    default_trace_dir,
    load_trace_jsonl_events,
    session_ids_in_trace_order,
)
from mergecraft.review.completed import load_completed_review_trace_events


def _payload(*, run_id: str | None, events: list[dict[str, Any]]) -> dict[str, Any]:
    sessions = session_ids_in_trace_order(events)
    chosen = run_id or (sessions[-1] if sessions else None)
    replayed = [event for event in events if chosen and event.get("session_id") == chosen]
    return {
        "verb": "replay",
        "run_id": chosen,
        "replayed": bool(replayed),
        "event_count": len(replayed),
        "runs": sessions,
    }


def _render_table(payload: dict[str, Any]) -> Table:
    table = Table(title="mergecraft replay", show_header=True, header_style="bold")
    table.add_column("field")
    table.add_column("value")
    table.add_row("run_id", str(payload.get("run_id") or "none"))
    table.add_row("replayed", "true" if payload.get("replayed") else "false")
    table.add_row("event_count", str(payload.get("event_count", 0)))
    runs = payload.get("runs") or []
    table.add_row("runs", ", ".join(str(item) for item in runs) if runs else "none")
    return table


def run(
    ctx: typer.Context,
    run_id: str | None = typer.Argument(
        default=None,
        help="Optional stored review run id to replay. Defaults to the latest traced run.",
    ),
    repo_root: Path = typer.Option(
        Path("."),
        "--repo-root",
        help="Repository root for durable review replay (read-only).",
    ),
    trace_dir: Path | None = typer.Option(
        None,
        "--trace-dir",
        help="Override $MERGECRAFT_TRACE_DIR for this invocation.",
    ),
) -> None:
    """Replay a stored review run from local traces (read-only)."""
    root = repo_root.expanduser().resolve()
    events: list[dict[str, Any]] = []
    if run_id:
        events = load_completed_review_trace_events(run_id, repo_root=root)
        if not events:
            cli_bail(f"unknown review run id {run_id}", code=CLI_USAGE_EXIT_CODE)
    else:
        target = trace_dir if trace_dir is not None else default_trace_dir()
        events = load_trace_jsonl_events(target)
    payload = _payload(run_id=run_id, events=events)
    if wants_json_output(ctx, json_flag=False):
        emit_cli_json(payload)
        raise typer.Exit(CLI_SUCCESS_EXIT_CODE)
    console.print(_render_table(payload))
    raise typer.Exit(CLI_SUCCESS_EXIT_CODE)


__all__ = ["run"]
