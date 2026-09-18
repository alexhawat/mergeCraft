"""Typer group that bootstraps colour and TTY interactive sessions."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import typer
from typer.core import TyperGroup

from mergecraft.cli.global_surface import bootstrap_cli_surface_from_argv

if TYPE_CHECKING:
    import click


class MergecraftTyperGroup(TyperGroup):
    """Apply #342 colour policy before Rich help, and open a TTY session.

    A group invoked with no subcommand (``mergecraft provider``,
    ``mergecraft analyzers``) prints help for scripts and CI. On a TTY it
    offers an interactive menu of the group's commands instead.
    """

    def make_context(
        self,
        info_name: str | None,
        args: list[str],
        parent: click.Context | None = None,
        **extra: Any,
    ) -> click.Context:
        bootstrap_cli_surface_from_argv(args, env=os.environ)
        return super().make_context(info_name, args, parent=parent, **extra)

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        command = super().get_command(ctx, cmd_name)
        if command is None:
            return None
        from mergecraft.cli.interactive import install_missing_param_prompts

        install_missing_param_prompts(command)
        return command

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        # Click 8.4 raises NoArgsIsHelpError in parse_args before invoke.
        # Clear the flag so empty TTY invocations can open a session.
        saved = self.no_args_is_help
        if saved and not args and not ctx.resilient_parsing:
            self.no_args_is_help = False
            try:
                return super().parse_args(ctx, args)
            finally:
                self.no_args_is_help = saved
        return super().parse_args(ctx, args)

    def invoke(self, ctx: click.Context) -> Any:
        if _is_empty_group_invocation(self, ctx):
            from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE
            from mergecraft.cli.interactive import (
                command_was_invoked_bare,
                is_interactive_session,
                run_group_session,
            )

            if is_interactive_session() and command_was_invoked_bare(ctx):
                run_group_session(ctx)
                return None
            if self.no_args_is_help:
                typer.echo(ctx.get_help())
                raise typer.Exit(CLI_SUCCESS_EXIT_CODE)
        return super().invoke(ctx)


def _is_empty_group_invocation(group: TyperGroup, ctx: click.Context) -> bool:
    """True when a group was invoked with no subcommand and no leftover args."""
    if group.invoke_without_command:
        return False
    if ctx.invoked_subcommand is not None:
        return False
    if ctx.args:
        return False
    protected = getattr(ctx, "_protected_args", None)
    return not protected


def mergecraft_typer(**kwargs: Any) -> typer.Typer:
    """Build a Typer app that uses :class:`MergecraftTyperGroup`."""
    kwargs.setdefault("cls", MergecraftTyperGroup)
    return typer.Typer(**kwargs)


__all__ = ["MergecraftTyperGroup", "mergecraft_typer"]
