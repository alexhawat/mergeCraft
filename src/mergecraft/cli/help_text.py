"""Render docstring-style help as terminal help.

Module: mergecraft.cli.help_text
Depends: click

Command help comes from docstrings written for Sphinx, where inline code is
``double backticks``. The CLI renders help with Rich, which prints those
literally, so the generated reference looked clean while the terminal did not.
The CLI group rewrites each command's help once, before it is shown.

Exports:
    Functions:
        terminal_help — Rewrite one help string for the terminal.
        install_terminal_help — Rewrite a command's (and its subcommands') help.
"""

from __future__ import annotations

import weakref
from typing import TYPE_CHECKING

from typer.core import TyperGroup, TyperOption

if TYPE_CHECKING:
    from typer import _click

_INSTALLED: weakref.WeakSet[_click.Command] = weakref.WeakSet()


def terminal_help(text: str | None) -> str | None:
    """Return *text* with RST inline-literal markup reduced to single backticks.

    Args:
        text (str | None): A help string.

    Returns:
        str | None: The rewritten string (``None`` stays ``None``).

    Examples:
        >>> terminal_help("Scaffold ``.mergecraft/config.yaml``.")
        'Scaffold `.mergecraft/config.yaml`.'
    """
    if text is None:
        return None
    return text.replace("``", "`")


def install_terminal_help(command: _click.Command) -> None:
    """Rewrite the help of *command*, its options and its subcommands once.

    Args:
        command (_click.Command): A command or group about to be shown or run.
    """
    if command in _INSTALLED:
        return
    _INSTALLED.add(command)
    command.help = terminal_help(command.help)
    command.short_help = terminal_help(command.short_help)
    command.epilog = terminal_help(command.epilog)
    for param in command.params:
        if isinstance(param, TyperOption):
            param.help = terminal_help(param.help)
    if isinstance(command, TyperGroup):
        for sub in command.commands.values():
            install_terminal_help(sub)


__all__ = ["install_terminal_help", "terminal_help"]
