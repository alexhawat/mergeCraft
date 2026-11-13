"""Select an operator's local credential directory before loading startup env."""

from __future__ import annotations

import subprocess
from copy import copy
from pathlib import Path
from typing import TYPE_CHECKING

import click
from click.core import ParameterSource
from typer.main import get_command

from mergecraft.utils.git_hardening import git_argv
from mergecraft.utils.workspace import git_repo_root

if TYPE_CHECKING:
    import typer


def implicit_env_is_tracked(path: Path) -> bool:
    """Reject implicit repository credentials, including links to tracked files.

    Explicit MERGECRAFT_ENV overrides are an operator choice and do not use
    this guard. Probe the link itself as well as its resolved destination,
    even when a tracked file has been deleted from the worktree.
    """
    try:
        try:
            resolved = path.resolve(strict=True)
        except FileNotFoundError:
            # Missing worktree files can still have an index entry. Resolve
            # existing links too, including links to a deleted tracked target.
            resolved = path.resolve()
        candidates = {path.absolute(), resolved}
    except (OSError, RuntimeError):
        return True
    for candidate in candidates:
        root = git_repo_root(str(candidate.parent))
        if root is None:
            continue
        try:
            result = subprocess.run(
                git_argv(
                    [
                        "--literal-pathspecs",
                        "ls-files",
                        "--error-unmatch",
                        "--",
                        str(candidate.relative_to(root)),
                    ]
                ),
                cwd=root,
                capture_output=True,
                check=False,
                timeout=5,
            )
        except (OSError, ValueError, subprocess.SubprocessError):
            # A repository was located but its index could not be inspected.
            # Explicitly selecting the credential file remains available.
            return True
        if result.returncode != 1:
            return True
    return False


def startup_local_target(app: typer.Typer, args: list[str]) -> Path | None:
    """Read explicit source options using Click's grammar, without callbacks.

    Copies of the declared parameters preserve option arity and ``--`` handling.
    Command/option callbacks and interactive prompts never run during this pass.
    Normal invocation remains responsible for reporting invalid arguments.
    """
    # Only explicit target options can redirect credential discovery. Keep the
    # full grammar pass when they occur, including as another option's value.
    if not any(arg.split("=", 1)[0] in {"--cwd", "--repo"} for arg in args):
        return None
    from mergecraft.utils.source_resolve import _is_remote_source

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
        command = command.get_command(context, remaining[0])
        remaining = remaining[1:]
    return target
