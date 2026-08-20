"""Typer CLI application — ``mergecraft`` entrypoint."""

from __future__ import annotations

import os
from pathlib import Path

from mergecraft.cli.exits import (
    CLI_SUCCESS_EXIT_CODE,
)

# Typer 0.25+: explicit ``--show-completion bash|zsh|fish`` (shellingham is unreliable
# in CI and non-interactive shells). Must be set before the Typer() constructor runs.
os.environ.setdefault("_TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION", "1")

import typer
from dotenv import load_dotenv

from mergecraft import __version__
from mergecraft.cli import (
    agents_cmd,
    analyzers_cmd,
    auth_cmd,
    cache_cmd,
    config_surface_cmd,
    context_cmd,
    diff_review_cmd,
    doctor_cmd,
    eval_cmd,
    findings_cmd,
    gha_cmd,
    init_cmd,
    learnings_cmd,
    lens_cmd,
    mcp_cmd,
    memory_cmd,
    models_cmd,
    pipeline_cmd,
    plan_cmd,
    policy_cmd,
    tracing_cmd,
    tracing_logfire_cmd,
    watch_cmd,
)

app = typer.Typer(
    name="mergecraft",
    help="Standalone BYOK GitHub Action runtime for coding agents (mergeCraft).",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

app.add_typer(agents_cmd.app, name="agents")
app.add_typer(lens_cmd.app, name="lens")
app.add_typer(pipeline_cmd.app, name="pipeline")
app.add_typer(mcp_cmd.app, name="mcp")
app.add_typer(cache_cmd.app, name="cache")
app.add_typer(context_cmd.app, name="context")
app.add_typer(auth_cmd.app, name="auth")
app.add_typer(models_cmd.app, name="models")
app.add_typer(analyzers_cmd.app, name="analyzers")
app.command("init")(init_cmd.run)
app.command("watch")(watch_cmd.run)
app.command("doctor")(doctor_cmd.run)
app.command("plan")(plan_cmd.run)
app.command("review")(diff_review_cmd.run)
app.command("diff-review", hidden=True)(diff_review_cmd.run)
app.add_typer(gha_cmd.app, name="gha")
app.add_typer(learnings_cmd.app, name="learnings")
app.add_typer(memory_cmd.app, name="memory")
app.add_typer(policy_cmd.app, name="policy")
app.add_typer(findings_cmd.app, name="findings")
app.add_typer(eval_cmd.app, name="eval")
# W8.4 — ``mergecraft config tracing`` + ``mergecraft traces <run-id>``.
tracing_cmd.config_app.command("show")(config_surface_cmd.config_show)
tracing_cmd.config_app.command("explain")(config_surface_cmd.config_explain)
tracing_cmd.config_app.command("validate")(config_surface_cmd.config_validate)
app.add_typer(tracing_cmd.config_app, name="config")
app.add_typer(tracing_cmd.app, name="traces")
# W8.6 — ``mergecraft tracing logfire enable|disable`` (sevn symmetry).
tracing_logfire_cmd.register(app)


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
        raise typer.Exit(CLI_SUCCESS_EXIT_CODE)
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(CLI_SUCCESS_EXIT_CODE)


@app.command("version")
def version_cmd() -> None:
    """Show the mergeCraft package version."""
    typer.echo(__version__)


def _local_env_path() -> Path:
    """Return the .env path the CLI loads at startup.

    Mirrors :func:`mergecraft.cli.auth_cmd._local_env_path` so the loader and
    the writer agree on the same file: ``$MERGECRAFT_ENV`` if set (tests pin a
    temp file), otherwise ``./.env`` relative to the current working directory.
    """
    configured = os.environ.get("MERGECRAFT_ENV")
    if configured:
        return Path(configured).resolve()
    return Path.cwd() / ".env"


def _load_local_env() -> None:
    """Populate ``os.environ`` from the local ``.env`` (no override).

    The auth command writes ``MERGECRAFT_LOGFIRE_TOKEN`` and
    ``MERGECRAFT_TRACING_PROJECT`` to ``.env`` via ``python-dotenv`` (see
    :func:`mergecraft.cli.auth_cmd._write_env_value`). Without this loader, the
    next CLI invocation in the same shell sees the new key in the file but not
    in ``os.environ`` — ``mergecraft config tracing`` reports ``enabled: false``
    because the env layer is empty.

    ``override=False`` is the contract: env vars already set by the operator,
    the GitHub Action, or earlier CLI steps win. Only missing keys are populated
    from the file. The file is silent-on-missing so CI sandboxes and global
    invocations from outside a checkout are unaffected.
    """
    env_path = _local_env_path()
    if not env_path.is_file():
        return
    load_dotenv(env_path, override=False, encoding="utf-8")


def main() -> None:
    _load_local_env()
    app()


if __name__ == "__main__":
    main()
