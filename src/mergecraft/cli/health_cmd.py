"""``mergecraft health`` — machine-readable enterprise health check (#381)."""

from __future__ import annotations

import json

import typer

from mergecraft.enterprise.health import health_payload

app = typer.Typer(
    name="health",
    help="Enterprise health check (emits JSON).",
    no_args_is_help=False,
)

__all__ = ["app"]


def _emit() -> None:
    typer.echo(json.dumps(health_payload()))


@app.callback(invoke_without_command=True)
def _callback(ctx: typer.Context) -> None:
    """Emit JSON health status when invoked with no subcommand."""
    if ctx.invoked_subcommand is None:
        _emit()


@app.command("run")
def run() -> None:
    """Emit JSON health status for the running mergeCraft installation."""
    _emit()
