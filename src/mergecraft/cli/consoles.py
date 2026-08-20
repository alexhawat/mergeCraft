"""Shared Rich consoles for the mergeCraft CLI (D14).

Command modules import :data:`err_console` for status, tables, and errors.
Machine-readable payloads use ``typer.echo`` (or :data:`out_console` when Rich
formatting must land on stdout). Only this module may construct a stdout
``Console()``.
"""

from __future__ import annotations

from rich.console import Console

out_console = Console()
err_console = Console(stderr=True)

__all__ = ["err_console", "out_console"]
