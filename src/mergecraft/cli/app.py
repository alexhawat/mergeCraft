"""Typer CLI application — ``mergecraft`` entrypoint."""

from __future__ import annotations

import typer
from rich.console import Console

from mergecraft import __version__
from mergecraft.cli import (
    analyzers_cmd,
    auth_cmd,
    diff_review_cmd,
    gha_cmd,
    init_cmd,
    learnings_cmd,
    models_cmd,
    watch_cmd,
)

app = typer.Typer(
    name="mergecraft",
    help="Standalone BYOK GitHub Action runtime for coding agents (mergeCraft).",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
)
console = Console(stderr=True)

app.add_typer(auth_cmd.app, name="auth")
app.add_typer(models_cmd.app, name="models")
app.add_typer(analyzers_cmd.app, name="analyzers")
app.command("init")(init_cmd.run)
app.command("watch")(watch_cmd.run)
app.command("diff-review")(diff_review_cmd.run)
app.add_typer(gha_cmd.app, name="gha")
app.add_typer(learnings_cmd.app, name="learnings")


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        help="Show version and exit.",
        is_eager=True,
    ),
) -> None:
    if version:
        typer.echo(__version__)
        raise typer.Exit(0)
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(0)


@app.command("version")
def version_cmd() -> None:
    """Show the mergeCraft package version."""
    typer.echo(__version__)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
