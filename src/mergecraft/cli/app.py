"""Typer CLI application — ``mergecraft`` entrypoint."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import typer
from dotenv import load_dotenv

from mergecraft import __version__
from mergecraft.cli import (
    agents_cmd,
    analyzers_cmd,
    ask_cmd,
    audit_cmd,
    auth_cmd,
    cache_cmd,
    capabilities_cmd,
    config_surface_cmd,
    context_cmd,
    describe_cmd,
    diff_review_cmd,
    doctor_cmd,
    eval_cmd,
    evidence_cmd,
    explain_cmd,
    findings_cmd,
    gha_cmd,
    health_cmd,
    init_cmd,
    learnings_cmd,
    lens_cmd,
    mcp_cmd,
    memory_cmd,
    models_cmd,
    pipeline_cmd,
    plan_cmd,
    policy_cmd,
    profile_cmd,
    replay_cmd,
    requirements_cmd,
    run_cmd,
    support_bundle_cmd,
    tracing_cmd,
    tracing_logfire_cmd,
    watch_cmd,
    xrepo_cmd,
)
from mergecraft.cli.exits import (
    CLI_SUCCESS_EXIT_CODE,
)
from mergecraft.cli.global_surface import (
    ColorMode,
    OutputFormat,
    apply_global_cli_options,
    validate_log_level_option,
)
from mergecraft.cli.typer_group import MergecraftTyperGroup


def _enable_install_completion_auto_detect(argv: list[str] | None = None) -> bool:
    """Return True when argv invokes bare ``--install-completion`` (README flow)."""
    args = list(sys.argv[1:] if argv is None else argv)
    if "--install-completion" not in args:
        return False
    idx = args.index("--install-completion")
    next_arg = args[idx + 1] if idx + 1 < len(args) else None
    return next_arg is None or next_arg.startswith("-")


def _configure_typer_shell_detection() -> None:
    """Configure Typer completion shell detection before ``Typer()`` is built."""
    # Typer 0.25: disable shellingham auto-detection by default so explicit
    # ``--show-completion bash|zsh|fish`` stays reliable in CI. Re-enable only for
    # bare ``--install-completion`` so Typer can auto-detect the current shell.
    if not _enable_install_completion_auto_detect():
        os.environ.setdefault("_TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION", "1")


_configure_typer_shell_detection()

app = typer.Typer(
    name="mergecraft",
    help="Standalone BYOK GitHub Action runtime for coding agents (mergeCraft).",
    no_args_is_help=True,
    rich_markup_mode="rich",
    cls=MergecraftTyperGroup,
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
app.command("capabilities")(capabilities_cmd.run)
app.command("describe")(describe_cmd.run)
app.command("explain")(explain_cmd.run)
app.command("ask")(ask_cmd.run)
app.command("replay")(replay_cmd.run)
app.command("plan")(plan_cmd.run)
app.command("review")(diff_review_cmd.run)
app.command("diff-review", hidden=True)(diff_review_cmd.run)
app.add_typer(gha_cmd.app, name="gha")
app.add_typer(learnings_cmd.app, name="learnings")
app.add_typer(memory_cmd.app, name="memory")
app.add_typer(policy_cmd.app, name="policy")
app.add_typer(profile_cmd.app, name="profile")
app.add_typer(requirements_cmd.app, name="requirements")
app.add_typer(xrepo_cmd.app, name="xrepo")
app.add_typer(evidence_cmd.app, name="evidence")
app.add_typer(findings_cmd.app, name="findings")
app.add_typer(eval_cmd.app, name="eval")
app.add_typer(run_cmd.app, name="run")
# W8.4 — ``mergecraft config tracing`` + ``mergecraft traces <run-id>``.
tracing_cmd.config_app.command("show")(config_surface_cmd.config_show)
tracing_cmd.config_app.command("explain")(config_surface_cmd.config_explain)
tracing_cmd.config_app.command("validate")(config_surface_cmd.config_validate)
app.add_typer(tracing_cmd.config_app, name="config")
app.add_typer(tracing_cmd.app, name="traces")
# W8.6 — ``mergecraft tracing logfire enable|disable`` (sevn symmetry).
tracing_logfire_cmd.register(app)
app.add_typer(health_cmd.app, name="health")
app.add_typer(audit_cmd.app, name="audit")
app.add_typer(support_bundle_cmd.app, name="support-bundle")


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
    output_format: OutputFormat = typer.Option(
        "table",
        "--format",
        help="Default output format for machine-readable subcommands.",
        case_sensitive=False,
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        "-q",
        help="Suppress informational Loguru records.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        help="Enable DEBUG Loguru records.",
    ),
    log_level: str | None = typer.Option(
        None,
        "--log-level",
        help="Explicit Loguru level (TRACE, DEBUG, INFO, WARNING, ERROR, CRITICAL).",
        callback=validate_log_level_option,
    ),
    color: ColorMode = typer.Option(
        "auto",
        "--color",
        help="Colour policy for Rich/Typer chrome: auto, always, or never.",
        case_sensitive=False,
    ),
) -> None:
    apply_global_cli_options(
        ctx,
        output_format=output_format,
        quiet=quiet,
        verbose=verbose,
        log_level=log_level,
        color=color,
    )
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
