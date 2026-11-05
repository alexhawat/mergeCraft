"""``mergecraft config show|explain|set|validate`` (CC2)."""

from __future__ import annotations

from pathlib import Path

import typer
from pydantic import ValidationError
from rich.table import Table

from mergecraft.cli.config_precedence import explain_setting, resolve_setting
from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.errors import cli_bail
from mergecraft.cli.exits import (
    CLI_SUCCESS_EXIT_CODE,
)
from mergecraft.config.io import (
    config_path_for_root,
    load_config_dict,
    patch_config_dict,
)
from mergecraft.config.layered import load_layered_config_dict, resolve_config_sources
from mergecraft.config.settings import RepoSettings

_SETTABLE_KEYS = frozenset({"model", "models", "tracing.enabled", "tracing"})
_TRUE_VALUES = frozenset({"true", "1", "yes", "on"})
_FALSE_VALUES = frozenset({"false", "0", "no", "off"})


def config_show(
    key: str = typer.Argument(..., help="Dotted config key to resolve (e.g. model)."),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root."),
    model: str | None = typer.Option(
        None,
        "--model",
        help="CLI override for model resolution (wins over env and YAML).",
    ),
) -> None:
    """Show a resolved config value and the precedence layer that supplied it."""
    root = cwd.resolve()
    try:
        value, layer = resolve_setting(key, cwd=root, cli_model=model)
    except KeyError as exc:
        cli_bail(str(exc))
    table = Table(title=f"mergecraft config show {key}", show_header=True, header_style="bold")
    table.add_column("field", style="cyan")
    table.add_column("value")
    table.add_row("value", str(value))
    table.add_row("source", layer.value)
    console.print(table)


def config_explain(
    key: str = typer.Argument(..., help="Dotted config key to explain."),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root."),
    model: str | None = typer.Option(None, "--model", help="CLI model override."),
) -> None:
    """Explain which precedence layer wins for a config key."""
    root = cwd.resolve()
    try:
        explained = explain_setting(key, cwd=root, cli_model=model)
    except KeyError as exc:
        cli_bail(str(exc))
    table = Table(title=f"mergecraft config explain {key}", show_header=True, header_style="bold")
    table.add_column("layer", style="cyan")
    table.add_column("value")
    for layer_name, layer_value in explained["layers"].items():
        table.add_row(layer_name, str(layer_value))
    table.add_row("[bold]winner[/bold]", f"{explained['winner']} → {explained['value']}")
    console.print(table)


def config_validate(
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root."),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to .mergecraft/config.yaml (default: workspace default).",
    ),
) -> None:
    """Strictly parse contributing files and validate their merged configuration."""
    root = cwd.resolve()
    files: tuple[Path, ...]
    if config is not None:
        if not config.is_file():
            cli_bail(f"config file does not exist: {config}")
        files = (config,)
    else:
        sources = resolve_config_sources(root)
        if sources.env_config_missing:
            cli_bail("MERGECRAFT_CONFIG names a missing config file")
        files = sources.files
    if not files:
        console.print("[green]ok[/green] — no config file (defaults apply)")
        raise typer.Exit(CLI_SUCCESS_EXIT_CODE)
    try:
        _validate_effective_config(cwd=root, explicit_path=config, strict=True)
    except ValueError as exc:
        cli_bail(str(exc))
    console.print(f"[green]ok[/green] — merged configuration from {', '.join(map(str, files))}")


def _parse_bool_value(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in _TRUE_VALUES:
        return True
    if lowered in _FALSE_VALUES:
        return False
    cli_bail(f"invalid boolean {value!r} — use true or false")
    raise AssertionError("unreachable")


def _split_model_slugs(value: str) -> list[str]:
    slugs = [part.strip() for part in value.replace(",", " ").split() if part.strip()]
    if not slugs:
        cli_bail("provide at least one model slug")
    return slugs


def _write_config_data(path: Path, *, patch: dict[str, object]) -> None:
    """Write *patch* into *path*, preserving comments and never duplicating a key."""
    patch_config_dict(path, patch)


def config_set(
    key: str = typer.Argument(
        ...,
        help="Dotted config key to write (model, models, tracing.enabled).",
    ),
    value: str = typer.Argument(
        ...,
        help="Value to write into .mergecraft/config.yaml.",
    ),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root."),
) -> None:
    """Write a supported config key into ``.mergecraft/config.yaml``."""
    root = cwd.resolve()
    normalized = key.strip().lower()
    if normalized not in _SETTABLE_KEYS:
        supported = ", ".join(sorted(_SETTABLE_KEYS))
        cli_bail(f"unsupported config key for set: {key!r} — supported: {supported}")

    config_path = config_path_for_root(root)
    data: dict[str, object] = load_config_dict(config_path)
    patch: dict[str, object]
    if normalized in {"model", "models"}:
        slugs = _split_model_slugs(value)
        data["models"] = slugs
        data.pop("model", None)
        patch = {"models": slugs}
    else:
        enabled = _parse_bool_value(value)
        tracing_raw = data.get("tracing")
        tracing = dict(tracing_raw) if isinstance(tracing_raw, dict) else {}
        tracing["enabled"] = enabled
        data["tracing"] = tracing
        patch = {"tracing": tracing}

    try:
        RepoSettings.model_validate(data)
    except ValidationError as exc:
        cli_bail(f"config validation failed: {exc}")

    _write_config_data(config_path, patch=patch)
    try:
        display = str(config_path.relative_to(root))
    except ValueError:
        display = str(config_path)
    console.print(f"wrote [green]{display}[/green] {normalized}={value}")


def _validate_effective_config(
    *, cwd: Path, explicit_path: Path | None = None, strict: bool = False
) -> None:
    loaded = load_layered_config_dict(root=cwd, explicit_path=explicit_path, strict=strict)
    try:
        RepoSettings.model_validate(loaded)
    except ValidationError as exc:
        msg = f"config validation failed: {exc}"
        raise ValueError(msg) from exc


def validate_repo_config_or_raise(*, cwd: Path) -> None:
    """Validate runtime's merged settings, retaining documented YAML fallback."""
    _validate_effective_config(cwd=cwd)


__all__ = [
    "config_explain",
    "config_set",
    "config_show",
    "config_validate",
    "validate_repo_config_or_raise",
]
