"""Resolve only the selected root command while keeping help import-free.

Exports:
    LazyRootGroup: Typer group with lazy root-command resolution.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

import click
import typer
from typer.main import get_command, get_group

from mergecraft.cli.command_catalog import COMMANDS
from mergecraft.cli.typer_group import MergecraftTyperGroup

if TYPE_CHECKING:
    from click.shell_completion import CompletionItem


class LazyRootGroup(MergecraftTyperGroup):
    """Load command implementations on demand; advertise metadata for discovery."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._loaded: set[str] = set()
        self._discovery = False
        for name, entry in COMMANDS.items():
            command_type = click.Group if entry.group else click.Command
            self.commands[name] = command_type(name, help=entry.help, hidden=entry.hidden)

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        if self._discovery:
            return self.commands.get(cmd_name)
        if cmd_name in COMMANDS and cmd_name not in self._loaded:
            entry = COMMANDS[cmd_name]
            module = import_module(f"mergecraft.cli.{entry.module}")
            target = getattr(module, entry.attribute)
            if cmd_name == "config":
                from mergecraft.cli import config_surface_cmd

                # Build a fresh wrapper: repeated root conversion must not append
                # the same config commands to the module-owned Typer object.
                wrapper = typer.Typer()
                wrapper.add_typer(target, name="config")
                command = get_command(wrapper)
                assert isinstance(command, click.Group)
                group = command.commands["config"]
                assert isinstance(group, click.Group)
                additions = typer.Typer()
                for verb in ("show", "explain", "set", "validate"):
                    additions.command(verb)(getattr(config_surface_cmd, f"config_{verb}"))
                extra = get_command(additions)
                assert isinstance(extra, click.Group)
                group.commands.update(extra.commands)
                command = group
            elif entry.group:
                command = get_group(target)
            else:
                wrapper = typer.Typer(add_completion=False)
                wrapper.command(cmd_name, hidden=entry.hidden)(target)
                command = get_command(wrapper)
            command.name = cmd_name
            command.hidden = entry.hidden
            self.commands[cmd_name] = command
            self._loaded.add(cmd_name)
            from mergecraft.cli.help_text import install_terminal_help

            install_terminal_help(command)
        return super().get_command(ctx, cmd_name)

    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        self._discovery = True
        try:
            super().format_help(ctx, formatter)
        finally:
            self._discovery = False

    def shell_complete(self, ctx: click.Context, incomplete: str) -> list[CompletionItem]:
        self._discovery = True
        try:
            return super().shell_complete(ctx, incomplete)
        finally:
            self._discovery = False
