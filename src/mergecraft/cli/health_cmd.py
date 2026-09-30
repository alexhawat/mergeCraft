"""``mergecraft health`` — machine-readable enterprise health check (#381)."""

from __future__ import annotations

import typer

from mergecraft.cli.global_surface import cli_json_dumps
from mergecraft.cli.typer_group import mergecraft_typer
from mergecraft.enterprise.health import health_payload

app = mergecraft_typer(
    name="health",
    help="Liveness + telemetry mode — not a readiness probe (emits JSON).",
    no_args_is_help=False,
)

__all__ = ["app"]


def _emit() -> None:
    typer.echo(cli_json_dumps(health_payload()))


@app.callback(invoke_without_command=True)
def _callback(ctx: typer.Context) -> None:
    """Emit JSON health status when invoked with no subcommand."""
    if ctx.invoked_subcommand is None:
        _emit()


@app.command("run")
def run() -> None:
    """Emit JSON health status for the running mergeCraft installation."""
    _emit()
