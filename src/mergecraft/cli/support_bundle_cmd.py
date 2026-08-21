"""``mergecraft support-bundle`` — write a redacted support archive (#381)."""

from __future__ import annotations

from pathlib import Path

import typer

from mergecraft.enterprise.support_bundle import write_support_bundle

app = typer.Typer(
    name="support-bundle",
    help="Write a gzipped support bundle with secret redaction.",
    no_args_is_help=False,
)

__all__ = ["app"]

_DEFAULT_OUTPUT = Path("mergecraft-support.tgz")


@app.callback(invoke_without_command=True)
def run(
    ctx: typer.Context,
    output: Path = typer.Option(
        _DEFAULT_OUTPUT,
        "--output",
        "-o",
        help="Destination path for the support bundle archive (.tgz).",
    ),
) -> None:
    """Write a support bundle archive to OUTPUT."""
    if ctx.invoked_subcommand is None:
        written = write_support_bundle(output)
        typer.echo(f"Support bundle written to {written}")
