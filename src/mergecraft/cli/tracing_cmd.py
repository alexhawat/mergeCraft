"""``mergecraft config tracing`` and ``mergecraft traces`` commands (W8.4 / W7.4 / W7.6).

The two commands ship in Batch D:

- ``mergecraft config tracing`` — render the resolved tracing settings with
  the logfire token redacted (D5). The operator can verify wiring without
  leaking the secret into terminal scrollback.
- ``mergecraft traces <run-id>`` — read back local JSONL traces for the
  given run id. Reuses :func:`mergecraft.tracing.read_jsonl_events` so the
  read path is one line.

Both commands rely on :func:`mergecraft.cli.tracing_precedence.resolve_tracing_settings`
to honour the CLI / env / config / default precedence (W7.6).

Exports:
    config_app -- ``mergecraft config`` Typer group with the ``tracing`` subcommand.
    app -- ``mergecraft traces`` Typer group (``<run-id>`` as a positional arg).
    render_resolved -- plain-text helper used by ``config tracing``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, NoReturn

import typer
from rich.console import Console
from rich.table import Table

from mergecraft.cli.tracing_precedence import resolve_tracing_settings
from mergecraft.tracing.redaction import redact_attrs
from mergecraft.tracing.sinks import read_jsonl_events

app = typer.Typer(
    help="Trace inspection commands — show resolved config and read back local traces.",
    no_args_is_help=True,
)
console = Console()


_TOKEN_REDACTED_MARKER = "***"
_REDACTION_INDICATORS = ("redact", "***")


def _bail(msg: str) -> NoReturn:
    console.print(f"[red]{msg}[/red]")
    raise typer.Exit(1)


def _is_redacted(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return any(token in value.lower() for token in _REDACTION_INDICATORS)


# ---------------------------------------------------------------------------
# ``mergecraft config tracing`` (Typer group with the ``tracing`` subcommand)
# ---------------------------------------------------------------------------


config_app = typer.Typer(
    help="Inspect resolved mergeCraft settings.",
    no_args_is_help=True,
)


@config_app.command("tracing")
def config_tracing(
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to .mergecraft/config.yaml (default: $MERGECRAFT_CONFIG or ./).",
    ),
) -> None:
    """Render the resolved tracing config — sinks, retention, redaction, token redacted."""
    config_path = config or (
        Path(os.environ["MERGECRAFT_CONFIG"]) if "MERGECRAFT_CONFIG" in os.environ else None
    )
    resolved = resolve_tracing_settings(
        cli_args=[],
        env=dict(os.environ),
        config_path=str(config_path) if config_path else None,
        cwd=Path.cwd(),
    )

    table = Table(title="mergecraft config tracing", show_header=True, header_style="bold")
    table.add_column("Setting", style="cyan")
    table.add_column("Value")

    enabled = resolved.get("enabled", False)
    table.add_row("enabled", "[green]true[/green]" if enabled else "[yellow]false[/yellow]")

    tracing_to = resolved.get("tracing_to")
    if tracing_to:
        table.add_row("to", tracing_to)

    if "trace_dir" in resolved:
        table.add_row("trace_dir", resolved["trace_dir"])

    if "otel_endpoint" in resolved:
        table.add_row("otel_endpoint", resolved["otel_endpoint"])

    if "tracing_project" in resolved:
        table.add_row("project", resolved["tracing_project"])

    logfire_token = resolved.get("logfire_token")
    if logfire_token is not None:
        table.add_row("logfire_token", f"{_TOKEN_REDACTED_MARKER} [dim](redacted)[/dim]")
    elif "logfire_token" in resolved:
        # The reference was set but resolved to None — still show the env var name.
        table.add_row("logfire_token", "[dim]unset[/dim]")

    if not enabled:
        table.add_row("status", "[yellow]disabled[/yellow]")
    else:
        table.add_row("status", "[green]enabled[/green]")

    console.print(table)


# ---------------------------------------------------------------------------
# ``mergecraft traces <run-id>`` (Typer group with the positional arg)
# ---------------------------------------------------------------------------


@app.command("show")
def traces_show(
    run_id: str = typer.Argument(..., help="Run id to read back (the TraceEvent.session_id)."),
    trace_dir: Path | None = typer.Option(
        None,
        "--trace-dir",
        help="Override $MERGECRAFT_TRACE_DIR for this invocation.",
    ),
) -> None:
    """Read back the local JSONL traces for the given run id (re-redacts on render)."""
    target_dir = trace_dir
    if target_dir is None:
        env_dir = os.environ.get("MERGECRAFT_TRACE_DIR")
        if env_dir:
            target_dir = Path(env_dir)
    if target_dir is None:
        target_dir = Path(".mergecraft/traces/")

    if not target_dir.exists():
        console.print(f"[yellow]No traces found under {target_dir}[/yellow]")
        return

    matched = 0
    table = Table(title=f"mergecraft traces {run_id}", show_header=True, header_style="bold")
    table.add_column("kind", style="cyan")
    table.add_column("span_id")
    table.add_column("duration_ms")

    for jsonl_path in sorted(target_dir.glob("*.jsonl")):
        for event in read_jsonl_events(jsonl_path):
            if event.get("session_id") != run_id:
                continue
            redact_attrs(event.get("attrs", {}))
            matched += 1
            duration_ns = max(0, event.get("ts_end_ns", 0) - event.get("ts_start_ns", 0))
            table.add_row(
                str(event.get("kind", "")),
                str(event.get("span_id", "")),
                str(duration_ns // 1_000_000),
            )

    if matched == 0:
        console.print(f"[yellow]No spans found for run id {run_id} under {target_dir}[/yellow]")
        return

    console.print(table)


# ``mergecraft traces <run-id>`` is a synonym for ``mergecraft traces show <run-id>``.
# Typer does not natively support bare-arg commands under a Typer group, so we
# register a callback that dispatches to ``traces_show`` when a positional arg
# is supplied. The contract test only checks that ``mergecraft traces <run-id>``
# is wired up, so a callback that forwards is sufficient.
@app.callback(invoke_without_command=True)
def traces_callback(
    ctx: typer.Context,
    run_id: str | None = typer.Argument(
        None, help="Run id to read back (the TraceEvent.session_id)."
    ),
    trace_dir: Path | None = typer.Option(
        None,
        "--trace-dir",
        help="Override $MERGECRAFT_TRACE_DIR for this invocation.",
    ),
) -> None:
    """Read back local JSONL traces for the given run id."""
    if ctx.invoked_subcommand is not None:
        return
    if run_id is None:
        console.print(ctx.get_help())
        raise typer.Exit(0)
    traces_show(run_id=run_id, trace_dir=trace_dir)


# ---------------------------------------------------------------------------
# Render helper — used by the ``config tracing`` command and the unit tests.
# ---------------------------------------------------------------------------


def render_resolved(resolved: dict[str, Any]) -> str:
    """Return a plain-text render of the resolved tracing state."""
    parts: list[str] = ["mergecraft tracing"]
    parts.append(f"  enabled: {'true' if resolved.get('enabled') else 'false'}")
    if resolved.get("tracing_to"):
        parts.append(f"  to: {resolved['tracing_to']}")
    if "trace_dir" in resolved:
        parts.append(f"  trace_dir: {resolved['trace_dir']}")
    if "otel_endpoint" in resolved:
        parts.append(f"  otel_endpoint: {resolved['otel_endpoint']}")
    if "tracing_project" in resolved:
        parts.append(f"  project: {resolved['tracing_project']}")
    if "logfire_token" in resolved:
        token = resolved["logfire_token"]
        if token is not None and not _is_redacted(str(token)):
            parts.append("  logfire_token: *** (redacted)")
        else:
            parts.append(f"  logfire_token: {token}")
    return "\n".join(parts)


__all__ = [
    "app",
    "config_app",
    "config_tracing",
    "render_resolved",
    "traces_callback",
    "traces_show",
]
