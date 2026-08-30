"""Global CLI surface — format, verbosity, color (#342 / D12)."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

import typer
from rich.console import COLOR_SYSTEMS

from mergecraft.cli import consoles
from mergecraft.cli.errors import cli_bail
from mergecraft.cli.exits import CLI_USAGE_EXIT_CODE
from mergecraft.review.snapshot import REVIEW_SCHEMA_VERSION as CLI_JSON_SCHEMA_VERSION
from mergecraft.utils.log import configure_logging, drain_loguru_queue

OutputFormat = Literal["table", "json"]
ColorMode = Literal["auto", "always", "never"]

_LOG_LEVELS = frozenset({"TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"})


@dataclass(frozen=True)
class CliGlobals:
    """Root callback options propagated to subcommands via ``ctx.obj``."""

    format: OutputFormat = "table"
    quiet: bool = False
    verbose: bool = False
    log_level: str | None = None
    color: ColorMode = "auto"


def _env_is_set(name: str, *, env: Mapping[str, str] | None = None) -> bool:
    env_map = env if env is not None else os.environ
    value = env_map.get(name)
    return value is not None and value != ""


def parse_color_flag_from_argv(argv: Sequence[str]) -> ColorMode | None:
    """Parse ``--color VALUE`` / ``--color=VALUE`` from a token list."""
    for index, token in enumerate(argv):
        if token == "--color" and index + 1 < len(argv):
            value = argv[index + 1].strip().lower()
            if value in {"auto", "always", "never"}:
                return cast("ColorMode", value)  # narrow argv token to ColorMode literal union
        if token.startswith("--color="):
            value = token.split("=", maxsplit=1)[1].strip().lower()
            if value in {"auto", "always", "never"}:
                return cast("ColorMode", value)  # narrow argv token to ColorMode literal union
    return None


def resolve_color_enabled(
    *,
    color: ColorMode,
    is_tty: bool | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[bool, bool]:
    """Return ``(color_enabled, force_terminal)`` from env and ``--color``."""
    if is_tty is None:
        is_tty = sys.stderr.isatty() or sys.stdout.isatty()

    if _env_is_set("NO_COLOR", env=env):
        return False, False
    if _env_is_set("FORCE_COLOR", env=env):
        return True, True
    if color == "never":
        return False, False
    if color == "always":
        return True, True
    return bool(is_tty), False


def apply_typer_rich_help_color(
    *,
    color: ColorMode,
    is_tty: bool | None = None,
    env: Mapping[str, str] | None = None,
) -> None:
    """Configure Typer's Rich help renderer (must run before ``--help`` formatting)."""
    try:
        from typer import rich_utils
    except ImportError:
        return

    color_enabled, force_terminal = resolve_color_enabled(color=color, is_tty=is_tty, env=env)
    if color_enabled:
        rich_utils.COLOR_SYSTEM = "truecolor"
        rich_utils.FORCE_TERMINAL = force_terminal or color == "always"
    else:
        rich_utils.COLOR_SYSTEM = None
        rich_utils.FORCE_TERMINAL = False


def apply_console_color(*, color_enabled: bool, force_terminal: bool) -> None:
    """Apply the resolved colour policy to shared Rich consoles."""
    for console in (consoles.out_console, consoles.err_console):
        console.no_color = not color_enabled
        console._force_terminal = True if force_terminal else None
        if color_enabled:
            color_system = console._detect_color_system()
            if color_system is None and force_terminal:
                color_system = COLOR_SYSTEMS["truecolor"]
            console._color_system = color_system
        else:
            console._color_system = None


def bootstrap_cli_surface_from_argv(
    argv: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    is_tty: bool | None = None,
) -> None:
    """Apply colour policy from argv/env before Typer parses ``--help``."""
    color = parse_color_flag_from_argv(argv) or "auto"
    color_enabled, force_terminal = resolve_color_enabled(color=color, is_tty=is_tty, env=env)
    apply_console_color(color_enabled=color_enabled, force_terminal=force_terminal)
    apply_typer_rich_help_color(color=color, is_tty=is_tty, env=env)


def _normalize_log_level(value: str) -> str:
    """Strip and upper-case a log level (validation happens in the Typer callback)."""
    return value.strip().upper()


def resolve_effective_log_level(
    *,
    quiet: bool,
    verbose: bool,
    log_level: str | None,
) -> str:
    """Resolve Loguru level from root flags and ``MERGECRAFT_LOG_LEVEL`` / ``LOG_LEVEL``."""
    if log_level is not None:
        return _normalize_log_level(log_level)
    if verbose:
        return "DEBUG"
    if quiet:
        return "WARNING"
    mergecraft_level = (os.environ.get("MERGECRAFT_LOG_LEVEL") or "").strip().upper()
    if mergecraft_level in _LOG_LEVELS:
        return mergecraft_level
    from mergecraft.utils.log import resolve_log_level

    return resolve_log_level()


def validate_log_level_option(value: str | None) -> str | None:
    """Typer callback — reject unknown ``--log-level`` values at the CLI boundary."""
    if value is None:
        return None
    normalized = _normalize_log_level(value)
    if normalized not in _LOG_LEVELS:
        cli_bail(
            f"invalid --log-level {value!r} — must be one of: {', '.join(sorted(_LOG_LEVELS))}",
            code=CLI_USAGE_EXIT_CODE,
        )
    return normalized


def apply_global_cli_options(
    ctx: typer.Context,
    *,
    output_format: OutputFormat,
    quiet: bool,
    verbose: bool,
    log_level: str | None,
    color: ColorMode,
) -> None:
    """Store root options on ``ctx.obj`` and configure logging.

    Colour is applied earlier by :func:`bootstrap_cli_surface_from_argv` so
    ``--help`` renders with the correct Rich policy before this callback runs.
    """
    ctx.obj = CliGlobals(
        format=output_format,
        quiet=quiet,
        verbose=verbose,
        log_level=log_level,
        color=color,
    )
    level = resolve_effective_log_level(quiet=quiet, verbose=verbose, log_level=log_level)
    configure_logging(force=True, level=level)


def get_cli_globals(ctx: typer.Context) -> CliGlobals:
    """Return propagated root options, or defaults when the callback did not run."""
    obj = ctx.obj
    if isinstance(obj, CliGlobals):
        return obj
    return CliGlobals()


def wants_json_output(ctx: typer.Context, *, json_flag: bool) -> bool:
    """True when the caller should emit JSON (global ``--format json`` or ``--json``)."""
    if json_flag:
        return True
    return get_cli_globals(ctx).format == "json"


def cli_json_dumps(payload: dict[str, Any]) -> str:
    """Serialize a CLI JSON payload with a pinned ``schema_version`` (D12)."""
    enriched = {"schema_version": CLI_JSON_SCHEMA_VERSION, **payload}
    return json.dumps(enriched, indent=2, sort_keys=True)


def emit_cli_json(payload: dict[str, Any]) -> None:
    """Write a schema-versioned JSON document to stdout."""
    typer.echo(cli_json_dumps(payload))


def drain_log_queue_after_command(*_args: object, **_kwargs: object) -> None:
    """Flush enqueued Loguru records before Typer returns (D6)."""
    drain_loguru_queue()


__all__ = [
    "CLI_JSON_SCHEMA_VERSION",
    "CliGlobals",
    "ColorMode",
    "OutputFormat",
    "apply_global_cli_options",
    "apply_typer_rich_help_color",
    "bootstrap_cli_surface_from_argv",
    "cli_json_dumps",
    "drain_log_queue_after_command",
    "emit_cli_json",
    "get_cli_globals",
    "parse_color_flag_from_argv",
    "resolve_color_enabled",
    "resolve_effective_log_level",
    "validate_log_level_option",
    "wants_json_output",
]
