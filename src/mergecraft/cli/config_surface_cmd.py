"""``mergecraft config show|explain|set|validate`` (CC2)."""

from __future__ import annotations

import os
from pathlib import Path

import typer
import yaml
from pydantic import ValidationError
from rich.table import Table

from mergecraft.cli.config_precedence import explain_setting, resolve_setting
from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.errors import cli_bail
from mergecraft.cli.exits import (
    CLI_SUCCESS_EXIT_CODE,
)
from mergecraft.config.io import (
    append_config_mapping,
    config_has_yaml_comments,
    config_path_for_root,
    load_config_dict,
    write_config_dict,
)
from mergecraft.config.settings import _DEFAULT_CONFIG_REL, RepoSettings

_SETTABLE_KEYS = frozenset({"model", "models", "tracing.enabled", "tracing"})
_TRUE_VALUES = frozenset({"true", "1", "yes", "on"})
_FALSE_VALUES = frozenset({"false", "0", "no", "off"})


def _config_path(cwd: Path) -> Path | None:
    env_path = os.environ.get("MERGECRAFT_CONFIG")
    if env_path:
        candidate = Path(env_path)
        if candidate.is_file():
            return candidate
    candidate = cwd / _DEFAULT_CONFIG_REL
    return candidate if candidate.is_file() else None


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
    """Validate repo config — unknown keys are rejected (extra=forbid)."""
    root = cwd.resolve()
    config_path = config or _config_path(root)
    if config_path is None or not config_path.is_file():
        console.print("[green]ok[/green] — no config file (defaults apply)")
        raise typer.Exit(CLI_SUCCESS_EXIT_CODE)
    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        cli_bail(f"config parse error: {exc}")
    if loaded is None:
        console.print(f"[green]ok[/green] — empty config at {config_path}")
        raise typer.Exit(CLI_SUCCESS_EXIT_CODE)
    if not isinstance(loaded, dict):
        cli_bail(f"config root must be a mapping: {config_path}")
    try:
        RepoSettings.model_validate(loaded)
    except ValidationError as exc:
        cli_bail(f"config validation failed: {exc}")
    console.print(f"[green]ok[/green] — {config_path}")


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


def _write_config_data(path: Path, data: dict[str, object], *, patch: dict[str, object]) -> None:
    if config_has_yaml_comments(path):
        append_config_mapping(path, patch)
        return
    write_config_dict(path, data)


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

    config_path = _config_path(root) or config_path_for_root(root)
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

    _write_config_data(config_path, data, patch=patch)
    try:
        display = str(config_path.relative_to(root))
    except ValueError:
        display = str(config_path)
    console.print(f"wrote [green]{display}[/green] {normalized}={value}")


def validate_repo_config_or_raise(*, cwd: Path) -> None:
    """Raise ``ValueError`` when the workspace config fails validation."""
    config_path = _config_path(cwd)
    if config_path is None:
        return
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if loaded is None:
        return
    if not isinstance(loaded, dict):
        msg = f"config root must be a mapping: {config_path}"
        raise ValueError(msg)
    try:
        RepoSettings.model_validate(loaded)
    except ValidationError as exc:
        msg = f"config validation failed: {exc}"
        raise ValueError(msg) from exc


__all__ = [
    "config_explain",
    "config_set",
    "config_show",
    "config_validate",
    "validate_repo_config_or_raise",
]
