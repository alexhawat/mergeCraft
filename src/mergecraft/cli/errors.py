"""Shared CLI error helpers."""

from __future__ import annotations

from typing import NoReturn

import typer

from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.exits import CLI_CONFIGURATION_EXIT_CODE


def cli_bail(msg: str, *, code: int = CLI_CONFIGURATION_EXIT_CODE) -> NoReturn:
    """Print a red error line and exit with a named CLI code."""
    console.print(f"[red]{msg}[/red]")
    raise typer.Exit(code)


__all__ = ["cli_bail"]
