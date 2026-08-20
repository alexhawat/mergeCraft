"""``mergecraft config show|explain|set|validate`` (CC2)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import NoReturn

import typer
import yaml
from pydantic import ValidationError
from rich.table import Table

from mergecraft.cli.config_precedence import explain_setting, resolve_setting
from mergecraft.cli.consoles import err_console as console
from mergecraft.config.settings import _DEFAULT_CONFIG_REL, RepoSettings


def _bail(msg: str, *, code: int = 1) -> NoReturn:
    console.print(f"[red]{msg}[/red]")
    raise typer.Exit(code)


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
        _bail(str(exc))
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
        _bail(str(exc))
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
        raise typer.Exit(0)
    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        _bail(f"config parse error: {exc}")
    if loaded is None:
        console.print(f"[green]ok[/green] — empty config at {config_path}")
        raise typer.Exit(0)
    if not isinstance(loaded, dict):
        _bail(f"config root must be a mapping: {config_path}")
    try:
        RepoSettings.model_validate(loaded)
    except ValidationError as exc:
        _bail(f"config validation failed: {exc}")
    console.print(f"[green]ok[/green] — {config_path}")


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
    "config_show",
    "config_validate",
    "validate_repo_config_or_raise",
]
