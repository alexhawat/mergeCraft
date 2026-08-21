"""``mergecraft replay`` — output-only replay of a stored review run (#377).

Distinct from ``mergecraft eval replay`` (eval-bank cases).

Exports: ``run``
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import typer
from rich.table import Table

from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE
from mergecraft.cli.global_surface import emit_cli_json, wants_json_output


def _trace_dir() -> Path:
    env_dir = os.environ.get("MERGECRAFT_TRACE_DIR")
    if env_dir:
        return Path(env_dir)
    return Path(".mergecraft/traces")


def _load_events(trace_dir: Path, *, run_id: str | None) -> list[dict[str, Any]]:
    if not trace_dir.is_dir():
        return []
    matched: list[dict[str, Any]] = []
    for jsonl_path in sorted(trace_dir.glob("*.jsonl")):
        try:
            raw = jsonl_path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in raw.splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            session = event.get("session_id")
            if run_id is not None and session != run_id:
                continue
            matched.append(event)
    return matched


def _payload(*, run_id: str | None, events: list[dict[str, Any]]) -> dict[str, Any]:
    sessions = sorted({str(event.get("session_id")) for event in events if event.get("session_id")})
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
    trace_dir: Path | None = typer.Option(
        None,
        "--trace-dir",
        help="Override $MERGECRAFT_TRACE_DIR for this invocation.",
    ),
) -> None:
    """Replay a stored review run from local traces (read-only)."""
    target = trace_dir if trace_dir is not None else _trace_dir()
    events = _load_events(target, run_id=run_id)
    payload = _payload(run_id=run_id, events=events)
    if wants_json_output(ctx, json_flag=False):
        emit_cli_json(payload)
        raise typer.Exit(CLI_SUCCESS_EXIT_CODE)
    console.print(_render_table(payload))
    raise typer.Exit(CLI_SUCCESS_EXIT_CODE)


__all__ = ["run"]
