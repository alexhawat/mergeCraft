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


def _write(output: Path) -> None:
    written = write_support_bundle(output)
    typer.echo(f"Support bundle written to {written}")


@app.callback(invoke_without_command=True)
def _callback(
    ctx: typer.Context,
    output: Path = typer.Option(
        _DEFAULT_OUTPUT,
        "--output",
        "-o",
        help="Destination path for the support bundle archive (.tgz / .tar.gz / .tar).",
    ),
) -> None:
    """Write a support bundle when invoked with no subcommand."""
    if ctx.invoked_subcommand is None:
        _write(output)


@app.command("write")
def write(
    output: Path = typer.Option(
        _DEFAULT_OUTPUT,
        "--output",
        "-o",
        help="Destination path for the support bundle archive (.tgz / .tar.gz / .tar).",
    ),
) -> None:
    """Write a support bundle archive to OUTPUT."""
    _write(output)
