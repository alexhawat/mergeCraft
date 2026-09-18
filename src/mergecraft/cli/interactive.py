"""TTY interactive sessions for bare ``mergecraft`` commands.

A command name with no extra arguments (``mergecraft``, ``mergecraft review``,
``mergecraft provider``) opens a prompt session when stdin is a TTY. Scripts,
CI, and piped invocations keep today's non-interactive behaviour.

Exports:
    GroupMenuItem -- one visible subcommand in a group menu.
    ReviewWizardChoice -- options collected by the review wizard.
    command_was_invoked_bare -- True when every command parameter is defaulted.
    confirm -- yes/no prompt; cancel raises ``typer.Exit``.
    install_missing_param_prompts -- wrap ``parse_args`` so missing required
        parameters are prompted on a TTY.
    is_interactive_session -- TTY + not CI + not MERGECRAFT_NONINTERACTIVE.
    prompt_choice -- numbered menu; empty / 0 / q cancels.
    prompt_text -- line prompt with optional default.
    run_group_session -- pick a subcommand and invoke it.
    run_review_wizard -- collect review options, or None when cancelled.
    visible_group_commands -- non-hidden subcommands of a Click group.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click
import typer
from click.core import ParameterSource

from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE, CLI_USAGE_EXIT_CODE

_TRUE = frozenset({"1", "true", "yes", "on"})
_CANCEL_TOKENS = frozenset({"", "q", "quit", "0"})


def is_interactive_session(
    *,
    env: Mapping[str, str] | None = None,
    stdin: Any | None = None,
) -> bool:
    """Return True when a human TTY session should prompt.

    Disabled when ``CI`` is set, ``MERGECRAFT_NONINTERACTIVE`` is truthy, or
    stdin is not a TTY. Tests force the session with
    ``MERGECRAFT_FORCE_INTERACTIVE=1`` (still requires a TTY or that flag
    together with a prompt monkeypatch).
    """
    env_map = os.environ if env is None else env
    if _env_truthy(env_map.get("MERGECRAFT_NONINTERACTIVE")):
        return False
    if _env_truthy(env_map.get("MERGECRAFT_FORCE_INTERACTIVE")):
        return True
    if _env_truthy(env_map.get("CI")):
        return False
    stream = sys.stdin if stdin is None else stdin
    isatty = getattr(stream, "isatty", None)
    return bool(isatty()) if callable(isatty) else False


def _env_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in _TRUE


def command_was_invoked_bare(
    ctx: click.Context,
    *,
    ignore: frozenset[str] | None = None,
) -> bool:
    """True when every parameter on *ctx* still has its declared default."""
    skipped = ignore or frozenset()
    for param in ctx.command.params:
        name = param.name
        if name is None or name in skipped:
            continue
        source = ctx.get_parameter_source(name)
        if source not in {None, ParameterSource.DEFAULT}:
            return False
    return True


def prompt_text(
    message: str,
    *,
    default: str | None = None,
    required: bool = True,
) -> str:
    """Prompt for a line of text. Empty input with no default cancels when required."""
    raw = typer.prompt(message, default=default or "", show_default=bool(default))
    value = str(raw).strip()
    if value:
        return value
    if default:
        return default
    if required:
        console.print("canceled.")
        raise typer.Exit(CLI_SUCCESS_EXIT_CODE)
    return ""


def confirm(message: str, *, default: bool = True) -> bool:
    """Return a yes/no answer. ``typer.Abort`` becomes a clean cancel."""
    try:
        return bool(typer.confirm(message, default=default))
    except typer.Abort:
        console.print("canceled.")
        raise typer.Exit(CLI_SUCCESS_EXIT_CODE) from None


@dataclass(frozen=True, slots=True)
class GroupMenuItem:
    """One visible subcommand offered by :func:`run_group_session`."""

    name: str
    help: str


def visible_group_commands(ctx: click.Context) -> list[GroupMenuItem]:
    """Return non-hidden subcommands of the Click group in *ctx*."""
    group = ctx.command
    if not isinstance(group, click.Group):
        return []
    items: list[GroupMenuItem] = []
    for name in group.list_commands(ctx):
        command = group.get_command(ctx, name)
        if command is None or command.hidden:
            continue
        items.append(GroupMenuItem(name=name, help=_short_help(command)))
    return items


def _short_help(command: click.Command) -> str:
    text = (command.short_help or command.help or "").strip()
    if not text:
        return ""
    return text.split("\n\n", 1)[0].replace("\n", " ")


def prompt_choice(
    title: str,
    options: Sequence[tuple[str, str]],
    *,
    default_index: int = 1,
) -> int:
    """Print a numbered menu and return the 1-based selection.

    Empty input accepts *default_index*. ``0`` / ``q`` cancels.
    """
    if not options:
        msg = "interactive menu has no options"
        raise RuntimeError(msg)
    console.print(f"[bold]{title}[/bold]")
    for index, (label, detail) in enumerate(options, start=1):
        suffix = f"  [dim]{detail}[/dim]" if detail else ""
        marker = " [dim](default)[/dim]" if index == default_index else ""
        console.print(f"  {index}. {label}{marker}{suffix}")
    raw = str(
        typer.prompt(
            "Selection (Enter for default, 0 to cancel)",
            default=str(default_index),
            show_default=False,
        )
    ).strip()
    if raw.lower() in _CANCEL_TOKENS:
        console.print("canceled.")
        raise typer.Exit(CLI_SUCCESS_EXIT_CODE)
    try:
        selected = int(raw)
    except ValueError:
        console.print(f"[red]invalid selection {raw!r}[/red]")
        raise typer.Exit(CLI_USAGE_EXIT_CODE) from None
    if selected < 1 or selected > len(options):
        console.print(f"[red]selection {selected} out of range (1-{len(options)})[/red]")
        raise typer.Exit(CLI_USAGE_EXIT_CODE)
    return selected


def run_group_session(ctx: click.Context) -> None:
    """Offer the group's subcommands and invoke the one that is chosen."""
    items = visible_group_commands(ctx)
    if not items:
        typer.echo(ctx.get_help())
        raise typer.Exit(CLI_SUCCESS_EXIT_CODE)
    path = _command_path(ctx)
    options = [(item.name, item.help) for item in items]
    selected = prompt_choice(f"{path} — interactive session", options)
    name = items[selected - 1].name
    command = ctx.command.get_command(ctx, name) if isinstance(ctx.command, click.Group) else None
    if command is None:
        console.print(f"[red]unknown command {name!r}[/red]")
        raise typer.Exit(CLI_USAGE_EXIT_CODE)
    install_missing_param_prompts(command)
    with command.make_context(name, [], parent=ctx) as sub_ctx:
        command.invoke(sub_ctx)


def _command_path(ctx: click.Context) -> str:
    names: list[str] = []
    current: click.Context | None = ctx
    while current is not None:
        if current.info_name:
            names.append(current.info_name)
        current = current.parent
    names.reverse()
    return " ".join(names) or "mergecraft"


def install_missing_param_prompts(command: click.Command) -> None:
    """Wrap *command.parse_args* so a TTY can supply missing required values."""
    if getattr(command, "_mergecraft_missing_param_prompts", False):
        return
    original = command.parse_args

    def parse_args(ctx: click.Context, args: list[str]) -> list[str]:
        return _parse_args_prompting_missing(original, ctx, args)

    command.parse_args = parse_args  # type: ignore[method-assign]
    command._mergecraft_missing_param_prompts = True  # type: ignore[attr-defined]


def _parse_args_prompting_missing(
    original: Callable[[click.Context, list[str]], list[str]],
    ctx: click.Context,
    args: list[str],
) -> list[str]:
    current = list(args)
    while True:
        try:
            return original(ctx, current)
        except click.MissingParameter as exc:
            if not is_interactive_session() or exc.param is None or ctx.resilient_parsing:
                raise
            current = _inject_prompted_param(exc.param, current)


def _inject_prompted_param(param: click.Parameter, args: list[str]) -> list[str]:
    label = param.human_readable_name or param.name or "value"
    if isinstance(param, click.Argument):
        value = prompt_text(label)
        return [*args, value]
    flag = param.opts[0] if param.opts else f"--{param.name}"
    if isinstance(param, click.Option) and param.is_flag:
        return [flag, *args]
    value = prompt_text(label)
    return [flag, value, *args]


@dataclass(frozen=True, slots=True)
class ReviewWizardChoice:
    """Review options collected by :func:`run_review_wizard`."""

    repo: str | None = None
    cwd: Path | None = None
    diff: Path | None = None
    staged: bool = False
    unstaged: bool = False
    base: str | None = None
    head: str | None = None
    commit_range: str | None = None
    dry_run: bool = False
    agent_mode: bool = False
    json_output: Path | None = None
    prompt: str | None = None


def run_review_wizard() -> ReviewWizardChoice:
    """Collect review options on a TTY. Cancel raises ``typer.Exit``."""
    console.print("[bold]mergecraft review — interactive session[/bold]")
    console.print("[dim]Enter accepts the default. 0 / q cancels.[/dim]")

    source = prompt_choice(
        "Source",
        (
            ("current checkout", "git repo in this directory"),
            ("local path", "--cwd PATH"),
            ("GitHub repo", "--repo owner/repo"),
            ("diff/patch file", "--diff FILE"),
        ),
    )
    repo: str | None = None
    cwd: Path | None = None
    diff: Path | None = None
    if source == 2:
        cwd = Path(prompt_text("local path"))
    elif source == 3:
        repo = prompt_text("GitHub repo (owner/repo or URL)")
    elif source == 4:
        diff = Path(prompt_text("diff/patch file"))

    staged = False
    unstaged = False
    base: str | None = None
    head: str | None = None
    commit_range: str | None = None
    if diff is None:
        selection = prompt_choice(
            "Diff selection",
            (
                ("default", "uncommitted edits plus commits since the detected base"),
                ("staged only", "git diff --cached"),
                ("unstaged only", "working-tree changes"),
                ("custom base/head", "--base and optional --head"),
                ("commit range", "--range A..B"),
            ),
        )
        if selection == 2:
            staged = True
        elif selection == 3:
            unstaged = True
        elif selection == 4:
            base = prompt_text("base ref")
            head_raw = prompt_text("head ref (empty for HEAD)", required=False)
            head = head_raw or None
        elif selection == 5:
            commit_range = prompt_text("commit range (e.g. origin/main..HEAD)")

    mode = prompt_choice(
        "Mode",
        (
            ("live review", "requires a provider credential"),
            ("dry-run", "print the Review prompt, no LLM call"),
        ),
    )
    dry_run = mode == 2

    output = prompt_choice(
        "Output",
        (
            ("text", "human-readable review on stderr"),
            ("json file", "write structured findings to a path"),
            ("agent JSONL", "orchestrator protocol on stdout"),
        ),
    )
    json_output: Path | None = None
    agent_mode = False
    if output == 2:
        json_output = Path(prompt_text("findings JSON path"))
    elif output == 3:
        agent_mode = True

    extra = prompt_text("extra prompt (optional)", required=False)
    if not confirm("Run review with these settings?", default=True):
        console.print("canceled.")
        raise typer.Exit(CLI_SUCCESS_EXIT_CODE)

    return ReviewWizardChoice(
        repo=repo,
        cwd=cwd,
        diff=diff,
        staged=staged,
        unstaged=unstaged,
        base=base,
        head=head,
        commit_range=commit_range,
        dry_run=dry_run,
        agent_mode=agent_mode,
        json_output=json_output,
        prompt=extra or None,
    )


__all__ = [
    "GroupMenuItem",
    "ReviewWizardChoice",
    "command_was_invoked_bare",
    "confirm",
    "install_missing_param_prompts",
    "is_interactive_session",
    "prompt_choice",
    "prompt_text",
    "run_group_session",
    "run_review_wizard",
    "visible_group_commands",
]
