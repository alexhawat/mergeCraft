"""``mergecraft audit`` — audit-log and usage/cost export CLI (#381)."""

from __future__ import annotations

from pathlib import Path

import typer

from mergecraft.cli.errors import cli_bail
from mergecraft.cli.exits import CLI_USAGE_EXIT_CODE
from mergecraft.enterprise.audit import (
    export_audit_log,
    load_audit_events,
    resolve_audit_log_path,
    verify_audit_chain,
)

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
    typer.echo(export_audit_log(load_audit_events()))


@app.command("verify")
def verify(
    path: Path | None = typer.Argument(
        None,
        help="Audit JSONL path (defaults to the resolved workspace audit log).",
    ),
) -> None:
    """Verify the audit hash chain and print any broken line numbers."""
    audit_path = path if path is not None else resolve_audit_log_path()
    breaks = verify_audit_chain(audit_path)
    if breaks:
        typer.echo(f"audit chain breaks at lines: {breaks}")
        raise typer.Exit(code=1)
    typer.echo("audit chain ok")
