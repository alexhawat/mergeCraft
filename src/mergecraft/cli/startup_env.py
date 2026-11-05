"""Select an operator's local credential directory before loading startup env."""

from __future__ import annotations

from copy import copy
from pathlib import Path
from typing import TYPE_CHECKING

import click
from click.core import ParameterSource
from typer.main import get_command

from mergecraft.utils.source_resolve import _is_remote_source

if TYPE_CHECKING:
    import typer


def startup_local_target(app: typer.Typer, args: list[str]) -> Path | None:
    """Read explicit source options using Click's grammar, without callbacks.

    Copies of the declared parameters preserve option arity and ``--`` handling.
    Command/option callbacks and interactive prompts never run during this pass.
    Normal invocation remains responsible for reporting invalid arguments.
    """
    command: click.Command | None = get_command(app)
    remaining = list(args)
    target: Path | None = None
    while command is not None:
        params = [copy(param) for param in command.params]
        for param in params:
            param.callback = None
            if isinstance(param, click.Option):
                param.prompt = None
        group = isinstance(command, click.Group)
        parser = click.Command(
            name=command.name,
            params=params,
            context_settings={"allow_interspersed_args": not group, "allow_extra_args": True},
        )
        with parser.make_context(command.name, remaining, resilient_parsing=True) as context:
            if context.get_parameter_source("cwd") is ParameterSource.COMMANDLINE:
                cwd = context.params.get("cwd")
                if cwd is not None:
                    target = Path(cwd).expanduser().resolve()
            if command.name in {"review", "diff-review"}:
                repo = context.params.get("repo")
                if isinstance(repo, str) and not _is_remote_source(repo):
                    target = Path(repo.strip()).expanduser().resolve()
            remaining = context.args
        if not isinstance(command, click.Group) or not remaining:
            break
        command = command.commands.get(remaining[0])
        remaining = remaining[1:]
    return target
