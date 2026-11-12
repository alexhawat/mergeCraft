"""Honour or reject the root ``--format json`` for every command.

Module: mergecraft.cli.machine_output
Depends: click, mergecraft.cli.global_surface

``mergecraft --format json <command>`` used to be silently ignored by most
commands: exit 0, a table on stderr and nothing on stdout, so a script could
not tell that it had received no JSON. The rule now covers every command,
including any added later, because the CLI group installs it on each command
it resolves:

* a command that reads the root format itself (:data:`ROOT_FORMAT_COMMANDS`)
  runs unchanged;
* a command with its own JSON switch gets it: a boolean ``--json`` flag, or a
  ``--format`` / ``--output-format`` option that offers or defaults to ``json``
  (an explicit value on the command line still wins);
* any other command exits ``2`` with one line saying it has no JSON output.

``--help`` is never affected.

Exports:
    Constants:
        ROOT_FORMAT_COMMANDS — Command paths that read the root format themselves.
    Functions:
        json_capability — How a command satisfies the root ``--format json``.
        install_root_format_guard — Apply the rule to a command (and its subcommands).
"""

from __future__ import annotations

import weakref
from typing import TYPE_CHECKING, Literal

import click

from mergecraft.cli.exits import CLI_USAGE_EXIT_CODE
from mergecraft.cli.global_surface import CliGlobals

if TYPE_CHECKING:
    from collections.abc import Callable

#: Commands that consult the root ``--format`` through ``wants_json_output``
#: (or emit JSON unconditionally) and have no option of their own to inject.
ROOT_FORMAT_COMMANDS: frozenset[tuple[str, ...]] = frozenset(
    {
        ("ask",),
        ("capabilities",),
        ("describe",),
        ("diff-review",),
        ("evidence", "show"),
        ("evidence", "verify"),
        ("findings", "_by_review_id"),
        ("findings", "export"),
        ("findings", "ledger"),
        ("health", "run"),
        ("profile", "recommend"),
        ("replay",),
        ("requirements", "explain"),
        ("requirements", "inspect"),
        ("review",),
        ("run", "diff"),
        ("run", "inspect"),
        ("watch",),
        ("xrepo", "explain"),
    }
)

Capability = Literal["root", "json-flag", "format-choice", "none"]

_INSTALLED: weakref.WeakSet[click.Command] = weakref.WeakSet()


def _json_flag(command: click.Command) -> click.Option | None:
    for param in command.params:
        if isinstance(param, click.Option) and param.is_flag and "--json" in param.opts:
            return param
    return None


def _format_choice(command: click.Command) -> click.Option | None:
    for param in command.params:
        if not isinstance(param, click.Option):
            continue
        if not {"--format", "--output-format"} & set(param.opts):
            continue
        choices = getattr(param.type, "choices", None)
        if (choices is not None and "json" in choices) or param.default == "json":
            return param
    return None


def json_capability(command: click.Command, path: tuple[str, ...]) -> Capability:
    """Return how *command* satisfies the root ``--format json``.

    Args:
        command (click.Command): A leaf command.
        path (tuple[str, ...]): Its subcommand path below ``mergecraft``.

    Returns:
        Capability: ``root``, ``json-flag``, ``format-choice`` or ``none``.
    """
    if path in ROOT_FORMAT_COMMANDS:
        return "root"
    if _json_flag(command) is not None:
        return "json-flag"
    if _format_choice(command) is not None:
        return "format-choice"
    return "none"


def _command_path(ctx: click.Context) -> tuple[str, ...]:
    names: list[str] = []
    node: click.Context | None = ctx
    while node is not None and node.parent is not None:
        names.append(node.info_name or "")
        node = node.parent
    return tuple(reversed(names))


def _mentions(args: list[str], opts: list[str]) -> bool:
    return any(arg in opts or any(arg.startswith(f"{opt}=") for opt in opts) for arg in args)


def _root_wants_json(ctx: click.Context) -> bool:
    globals_ = ctx.find_root().obj
    return isinstance(globals_, CliGlobals) and globals_.format == "json"


def _wants_help(ctx: click.Context, args: list[str]) -> bool:
    return any(arg in ctx.help_option_names for arg in args)


def _guarded_parse_args(
    command: click.Command, original: Callable[[click.Context, list[str]], list[str]]
) -> Callable[[click.Context, list[str]], list[str]]:
    def parse_args(ctx: click.Context, args: list[str]) -> list[str]:
        if ctx.resilient_parsing or _wants_help(ctx, args) or not _root_wants_json(ctx):
            return original(ctx, args)
        path = _command_path(ctx)
        capability = json_capability(command, path)
        if capability == "json-flag":
            flag = _json_flag(command)
            if flag is not None and not _mentions(args, flag.opts):
                args = ["--json", *args]
        elif capability == "format-choice":
            option = _format_choice(command)
            if option is not None and not _mentions(args, option.opts):
                args = [option.opts[0], "json", *args]
        elif capability == "none":
            name = " ".join(("mergecraft", *path))
            raise click.exceptions.Exit(_reject(name))
        return original(ctx, args)

    return parse_args


def _reject(name: str) -> int:
    from mergecraft.cli.consoles import err_console

    err_console.print(
        f"{name} has no JSON output: drop the root --format json for this command.",
        style="red",
        markup=False,
        highlight=False,
        soft_wrap=True,
    )
    return CLI_USAGE_EXIT_CODE


def install_root_format_guard(command: click.Command) -> None:
    """Apply the root ``--format json`` rule to *command* and its subcommands.

    Installed once per command by the CLI group, like the repo-root resolver.

    Args:
        command (click.Command): A command or group about to be invoked.
    """
    if command in _INSTALLED:
        return
    _INSTALLED.add(command)
    if isinstance(command, click.Group):
        for sub in command.commands.values():
            install_root_format_guard(sub)
        return
    # Instance attribute shadows the bound method; Context.make_context calls it.
    command.parse_args = _guarded_parse_args(  # type: ignore[method-assign, assignment]  # — Click reads parse_args off the instance
        command, command.parse_args
    )


__all__ = ["ROOT_FORMAT_COMMANDS", "install_root_format_guard", "json_capability"]
