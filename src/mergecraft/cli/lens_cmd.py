"""``mergecraft lens`` — bundled themed lens catalog (AP5)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

import typer
from rich.table import Table

from mergecraft.agents.lenses import get_lens, load_lens_catalog, resolve_lens_prompt
from mergecraft.classify.change_classifier import classify_change
from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.exits import (
    CLI_CONFIGURATION_EXIT_CODE,
)
from mergecraft.review.lens_routing import load_routing_registry, route_lenses

if TYPE_CHECKING:
    from mergecraft.config.settings import RepoSettings

app = typer.Typer(
    name="lens",
    help="Inspect and test bundled review lenses.",
    no_args_is_help=True,
)


def _bail(msg: str) -> NoReturn:
    console.print(f"[red]{msg}[/red]")
    raise typer.Exit(CLI_CONFIGURATION_EXIT_CODE)


@app.command("list")
def list_cmd() -> None:
    """List bundled lens ids and display titles."""
    catalog = load_lens_catalog()
    table = Table(title="Lens catalog")
    table.add_column("id")
    table.add_column("title")
    for lens_id in sorted(catalog.all_lens_ids):
        lens = get_lens(lens_id)
        table.add_row(lens_id, lens.title)
    console.print(table)


@app.command("show")
def show_cmd(lens_id: str = typer.Argument(..., help="Lens id (e.g. security).")) -> None:
    """Show rubric, triggers, evidence, and tool classes for one lens."""
    try:
        lens = get_lens(lens_id)
    except KeyError:
        _bail(f"unknown lens id: {lens_id!r}")

    console.print(f"[bold]{lens.lens_id}[/bold] — {lens.title}")
    typer.echo("\n--- rubric ---\n")
    typer.echo(lens.rubric)
    typer.echo("\n--- triggers ---\n")
    typer.echo(f"categories: {', '.join(lens.triggers.categories) or '(none)'}")
    typer.echo(f"minRiskBand: {lens.triggers.min_risk_band or '(none)'}")
    typer.echo("\n--- required evidence ---\n")
    for item in lens.required_evidence:
        typer.echo(f"- {item}")
    typer.echo("\n--- tool classes ---\n")
    for item in sorted(lens.tool_classes, key=str):
        typer.echo(item.value)


@app.command("test")
def run_lens_test(
    lens_id: str = typer.Argument(..., help="Lens id to exercise in isolation."),
    diff: Path = typer.Option(..., "--diff", help="Diff fixture path.", exists=True),
) -> None:
    """Preview one lens dispatch (rubric + routing context) for a diff fixture."""
    try:
        lens = get_lens(lens_id)
    except KeyError:
        _bail(f"unknown lens id: {lens_id!r}")

    diff_text = diff.read_text(encoding="utf-8")
    changed_paths = [
        line.split(" b/", 1)[1]
        for line in diff_text.splitlines()
        if line.startswith("diff --git ") and " b/" in line
    ]
    if not changed_paths:
        changed_paths = [diff.name]

    classification = classify_change(
        {"changed_paths": changed_paths, "diff_stats": {"diff": diff_text, "files_changed": 1}}
    )
    registry = load_routing_registry(settings=_load_settings())
    decision = route_lenses(classification, registry=registry)
    selected = lens_id in decision.selected_lens_ids

    console.print(f"[bold]lens test[/bold]: {lens.lens_id}")
    typer.echo("\n--- hypothesis ---\n")
    typer.echo(
        f"Apply the {lens.title} lens to the supplied diff — falsifiable, load-bearing, "
        "independent investigation."
    )
    typer.echo("\n--- rubric ---\n")
    typer.echo(resolve_lens_prompt(lens_id))
    typer.echo("\n--- routing ---\n")
    typer.echo(f"selected_by_router: {selected}")
    if selected:
        entry = next(item for item in decision.entries if item.lens_id == lens_id)
        typer.echo(f"reason: {entry.reason}")


def _load_settings() -> RepoSettings:
    from mergecraft.config.settings import load_repo_settings

    return load_repo_settings()
