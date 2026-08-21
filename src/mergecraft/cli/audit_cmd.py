"""``mergecraft audit`` — audit-log and usage/cost export CLI (#381)."""

from __future__ import annotations

import typer

from mergecraft.cli.errors import cli_bail
from mergecraft.cli.exits import CLI_USAGE_EXIT_CODE
from mergecraft.enterprise.audit import export_audit_log

app = typer.Typer(
    name="audit",
    help="Audit-log and usage/cost export.",
    no_args_is_help=True,
)

__all__ = ["app"]


@app.callback()
def _callback() -> None:
    """Audit-log and usage/cost export."""


@app.command("export")
def export(
    format: str = typer.Option(
        "json",
        "--format",
        help="Output format (only 'json' is supported).",
    ),
) -> None:
    """Export the audit log as a JSON array."""
    if format.strip().casefold() != "json":
        cli_bail(
            f"unsupported audit export format {format!r}; only 'json' is supported",
            code=CLI_USAGE_EXIT_CODE,
        )
    typer.echo(export_audit_log([]))
