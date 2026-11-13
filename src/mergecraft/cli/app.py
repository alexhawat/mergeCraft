"""Typer CLI application — ``mergecraft`` entrypoint."""

from __future__ import annotations

import os
import sys

import typer

import mergecraft
from mergecraft import __version__, format_version_display, version_json_payload
from mergecraft.cli.consoles import err_console
from mergecraft.cli.exits import (
    CLI_CONFIGURATION_EXIT_CODE,
    CLI_SUCCESS_EXIT_CODE,
)
from mergecraft.cli.global_surface import (
    ColorMode,
    OutputFormat,
    apply_global_cli_options,
    drain_log_queue_after_command,
    emit_cli_json,
    validate_log_level_option,
)
from mergecraft.cli.lazy_group import LazyRootGroup
from mergecraft.cli.local_env import (
    _configured_env_path,
    local_env_path_for_cwd,
    local_env_path_for_process_cwd,
)
from mergecraft.config.env import EnvSettingsError, LocalDotEnv
from mergecraft.config.layered import running_in_github_actions


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
    no_args_is_help=False,
    rich_markup_mode="rich",
    cls=LazyRootGroup,
)


@app.callback(invoke_without_command=True, result_callback=drain_log_queue_after_command)
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
        typer.echo(format_version_display(__version__, mergecraft.__commit__))
        raise typer.Exit(CLI_SUCCESS_EXIT_CODE)
    if ctx.invoked_subcommand is None:
        from mergecraft.cli.interactive import (
            command_was_invoked_bare,
            is_interactive_session,
            run_group_session,
        )

        if is_interactive_session() and command_was_invoked_bare(ctx):
            run_group_session(ctx)
            return
        typer.echo(ctx.get_help())
        raise typer.Exit(CLI_SUCCESS_EXIT_CODE)


@app.command("version")
def version_cmd(
    format: OutputFormat | None = typer.Option(
        None,
        "--format",
        help="Output format. Defaults to text.",
        case_sensitive=False,
    ),
) -> None:
    """Show the mergeCraft package version."""
    if format == "json":
        emit_cli_json(version_json_payload(__version__, mergecraft.__commit__))
        return
    typer.echo(format_version_display(__version__, mergecraft.__commit__))


def _load_local_env(args: list[str] | None = None) -> None:
    """Populate ``os.environ`` from the local ``.env`` (no override).

    The auth command writes ``MERGECRAFT_LOGFIRE_TOKEN`` and
    ``MERGECRAFT_TRACING_PROJECT`` to ``.env`` via ``python-dotenv`` (see
    :func:`mergecraft.cli.auth_cmd._write_env_value`). Without this loader, the
    next CLI invocation in the same shell sees the new key in the file but not
    in ``os.environ`` — ``mergecraft config tracing`` reports ``enabled: false``
    because the env layer is empty.

    The file is parsed by :class:`mergecraft.config.env.LocalDotEnv`, the one
    ``.env`` reader, so the startup load, ``jev`` and ``provider`` all read the
    same file the same way. Keys already set by the operator, the GitHub Action
    or an earlier CLI step win: only missing keys are populated from the file.
    The file is silent-on-missing so global invocations from outside a checkout
    are unaffected.

    Inside GitHub Actions the load is skipped unless ``$MERGECRAFT_ENV`` names a
    file: the job workspace holds the reviewed checkout, so a PR that adds a
    ``.env`` could otherwise set ``MERGECRAFT_*`` keys the workflow never chose.
    This mirrors the ``config.local.yaml`` rule
    (:func:`mergecraft.config.layered.running_in_github_actions`). Outside
    Actions an implicitly selected tracked file is also skipped: credentials
    must be operator-owned. An explicit ``$MERGECRAFT_ENV`` always wins.
    """
    if running_in_github_actions() and _configured_env_path() is None:
        return
    from mergecraft.cli.startup_env import implicit_env_is_tracked, startup_local_target

    target = startup_local_target(app, args) if args is not None else None
    env_path = (
        local_env_path_for_cwd(target)
        if target is not None
        else local_env_path_for_process_cwd(on_missing_repo="use-process-cwd")
    )
    if not env_path.is_file():
        return
    if _configured_env_path() is None and implicit_env_is_tracked(env_path):
        err_console.print(
            "Skipping implicit .env: file or symlink target is tracked by Git, "
            "or its tracking status could not be verified. "
            "Use an untracked credential file or explicitly set MERGECRAFT_ENV.",
            style="yellow",
        )
        return
    for key, value in LocalDotEnv.from_file(env_path).raw_values().items():
        os.environ.setdefault(key, value)


def main() -> None:
    try:
        _load_local_env(sys.argv[1:])
        app()
    except EnvSettingsError as exc:
        # A malformed control-carrying environment variable (e.g. a typo'd
        # ``MERGECRAFT_TRACING``) must exit through the named configuration
        # code, not a Rich traceback. ``typer.Exit`` raised by ``cli_bail``
        # only becomes the process code inside Click's ``Command.main()``;
        # ``main`` runs outside it, so raise ``SystemExit`` directly. The
        # message names the variable and never the value.
        err_console.print(str(exc), style="red")
        raise SystemExit(CLI_CONFIGURATION_EXIT_CODE) from exc


if __name__ == "__main__":
    main()
