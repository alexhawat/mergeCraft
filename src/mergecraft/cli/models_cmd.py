"""``mergecraft models`` — inspect and configure ordered model preference (#14)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

import typer
import yaml

from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.exits import (
    CLI_CONFIGURATION_EXIT_CODE,
)
from mergecraft.config import load_repo_settings
from mergecraft.config.settings import _DEFAULT_CONFIG_REL
from mergecraft.models import MODEL_ALIASES
from mergecraft.utils.agent_resolve import (
    effective_model_slugs,
    has_credentials_for_slug,
    resolve_effective_model_slug,
)

if TYPE_CHECKING:
    from mergecraft.config.settings import RepoSettings

app = typer.Typer(
    help="Inspect and configure ordered model preferences.",
    no_args_is_help=True,
)


def _bail(msg: str) -> NoReturn:
    console.print(f"[red]{msg}[/red]")
    raise typer.Exit(CLI_CONFIGURATION_EXIT_CODE)


def _configured_model_slugs(settings: RepoSettings) -> list[str]:
    if settings.models:
        return list(settings.models)
    if settings.model:
        return [settings.model]
    return []


def _config_path(cwd: Path) -> Path:
    return (cwd / _DEFAULT_CONFIG_REL).resolve()


def _load_config_dict(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        _bail(f"config must be a mapping: {path}")
    return loaded


def _write_models_config(*, cwd: Path, slugs: list[str]) -> Path:
    config_path = _config_path(cwd)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    data = _load_config_dict(config_path)
    data["models"] = slugs
    config_path.write_text(
        yaml.safe_dump(data, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    return config_path


@app.command("list")
def list_cmd(
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root."),
) -> None:
    """List curated model slugs and whether credentials are detected locally."""
    repo_root = cwd.resolve()
    console.print("[bold]Model catalog[/bold]")
    for alias in sorted(MODEL_ALIASES, key=lambda entry: entry.slug):
        if alias.hidden:
            continue
        creds = "yes" if has_credentials_for_slug(alias.slug) else "no"
        console.print(f"{alias.slug} {alias.provider} {alias.display_name} {creds}")

    settings = load_repo_settings(root=repo_root, load_learnings_files=False)
    configured = _configured_model_slugs(settings)
    if configured:
        console.print(
            f"\nconfigured order in [cyan]{_DEFAULT_CONFIG_REL}[/cyan]: " + ", ".join(configured)
        )


@app.command("set")
def set_cmd(
    slugs: list[str] = typer.Argument(
        ...,
        help="Ordered model slugs written to the models: list in config.",
    ),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root."),
) -> None:
    """Write an ordered ``models:`` list to ``.mergecraft/config.yaml``."""
    if not slugs:
        _bail("provide at least one model slug")

    cleaned = [slug.strip() for slug in slugs if slug.strip()]
    if not cleaned:
        _bail("provide at least one non-empty model slug")

    repo_root = cwd.resolve()
    config_path = _write_models_config(cwd=repo_root, slugs=cleaned)
    console.print(
        f"wrote [green]{config_path.relative_to(repo_root)}[/green] models: " + ", ".join(cleaned)
    )


@app.command("show")
def show_cmd(
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root."),
) -> None:
    """Show effective model order, env override, and the slug that would win now."""
    repo_root = cwd.resolve()
    settings = load_repo_settings(root=repo_root, load_learnings_files=False)
    order = effective_model_slugs(settings)
    env_override = os.environ.get("MERGECRAFT_MODEL", "").strip()
    winner = resolve_effective_model_slug(settings)

    if env_override:
        console.print(f"env override [cyan]MERGECRAFT_MODEL[/cyan]: {env_override}")
    else:
        console.print("[dim]env override MERGECRAFT_MODEL: (unset)[/dim]")

    if not order:
        console.print("[yellow]no models configured[/yellow]")
        if winner:
            console.print(f"would win now: {winner}")
        return

    console.print("effective order:")
    for index, slug in enumerate(order, start=1):
        markers: list[str] = []
        if env_override and slug == env_override:
            markers.append("env")
        if winner and slug == winner:
            markers.append("win")
        creds = "yes" if has_credentials_for_slug(slug) else "no"
        suffix = f" ({', '.join(markers)})" if markers else ""
        line = f"  {index}. {slug} [credentials: {creds}]{suffix}"
        console.print(line)

    if winner:
        console.print(f"\nwould win now: [bold]{winner}[/bold]")
