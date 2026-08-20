"""``mergecraft learnings`` — provenance + influence audit subcommand.

D11 surface: lists the learning entries that will be (or were) seeded
into the active review, by their provenance record. The shape is the
same for both ``active`` (promoted) and ``staging`` (quarantined)
sections; ``influence`` shows both.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import typer
from loguru import logger

from mergecraft.cli.consoles import err_console as console
from mergecraft.utils.learnings import (
    LearningProvenance,
    list_active_entries,
    list_staging_entries,
)

app = typer.Typer(
    help="Inspect the provenance-gated learnings file for a repository.",
    no_args_is_help=True,
)


def _resolve_learnings_path(repo: Path) -> Path:
    """Return the workspace ``.mergecraft/learnings.md`` for ``repo``."""
    return repo / ".mergecraft" / "learnings.md"


def _entry_to_dict(entry: dict[str, Any]) -> dict[str, Any]:
    """Coerce a parsed section entry to a JSON-safe dict.

    Provenance records are Pydantic models — serialise them explicitly.
    """
    prov = entry.get("provenance")
    return {
        "heading": entry.get("heading") or "",
        "body": entry.get("body") or "",
        "provenance": prov.model_dump(mode="json")
        if isinstance(prov, LearningProvenance)
        else None,
    }


def _format_output(payload: list[dict[str, Any]], *, json_output: bool) -> str:
    if json_output:
        return json.dumps(payload, indent=2, sort_keys=True)
    if not payload:
        return "(no entries)"
    lines: list[str] = []
    for entry in payload:
        heading = entry["heading"] or "(anonymous)"
        lines.append(f"- {heading}")
        prov = entry.get("provenance")
        if prov:
            run = prov.get("run_id") or "?"
            author = prov.get("author_login") or "?"
            tier = prov.get("trust_tier") or "?"
            pr = prov.get("pr_number")
            pr_part = f" pr=#{pr}" if pr else ""
            ts = prov.get("timestamp") or "?"
            lines.append(f"    run={run} author={author}{pr_part} tier={tier} ts={ts}")
        body = entry["body"]
        if body:
            for body_line in body.splitlines()[:3]:
                lines.append(f"    {body_line}")
    return "\n".join(lines)


@app.command("influence")
def influence(
    repo: Path = typer.Option(
        Path("."),
        "--repo",
        "-r",
        help="Path to the repository whose learnings file should be audited.",
        exists=True,
        file_okay=False,
        dir_okay=True,
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit the listing as JSON (audit-friendly).",
    ),
) -> None:
    """List active + staging learning entries with their provenance.

    The output names every entry's heading and its originating run
    id (D11). Use ``--json`` for machine-readable audit logs.
    """
    learn_path = _resolve_learnings_path(repo)
    if not learn_path.is_file():
        console.print(
            f"[yellow]no learnings file at {learn_path}[/yellow] — run mergeCraft once to seed it."
        )
        raise typer.Exit(0)
    try:
        text = learn_path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("could not read {}: {}", learn_path, exc)
        console.print(f"[red]could not read {learn_path}: {exc}[/red]")
        raise typer.Exit(1) from None
    payload: list[dict[str, Any]] = []
    for entry in list_active_entries(text):
        payload.append(_entry_to_dict(entry))
    output = _format_output(payload, json_output=json_output)
    if json_output:
        typer.echo(output)
    else:
        typer.echo(output)
    if not json_output:
        staging_payload = [_entry_to_dict(e) for e in list_staging_entries(text)]
        if staging_payload:
            typer.echo("\nstaging (quarantined — promotion required):")
            typer.echo(_format_output(staging_payload, json_output=False))
        else:
            typer.echo("\nstaging (quarantined — promotion required): (none)")
    sys.stdout.flush()


@app.command("active")
def active(
    repo: Path = typer.Option(
        Path("."),
        "--repo",
        "-r",
        help="Path to the repository whose learnings file should be audited.",
        exists=True,
        file_okay=False,
        dir_okay=True,
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """List only the active (promoted) learning entries."""
    learn_path = _resolve_learnings_path(repo)
    if not learn_path.is_file():
        console.print(f"[yellow]no learnings file at {learn_path}[/yellow]")
        raise typer.Exit(0)
    text = learn_path.read_text(encoding="utf-8")
    payload = [_entry_to_dict(e) for e in list_active_entries(text)]
    typer.echo(_format_output(payload, json_output=json_output))


@app.command("staging")
def staging(
    repo: Path = typer.Option(
        Path("."),
        "--repo",
        "-r",
        help="Path to the repository whose learnings file should be audited.",
        exists=True,
        file_okay=False,
        dir_okay=True,
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """List only the staging (quarantined) learning entries."""
    learn_path = _resolve_learnings_path(repo)
    if not learn_path.is_file():
        console.print(f"[yellow]no learnings file at {learn_path}[/yellow]")
        raise typer.Exit(0)
    text = learn_path.read_text(encoding="utf-8")
    payload = [_entry_to_dict(e) for e in list_staging_entries(text)]
    typer.echo(_format_output(payload, json_output=json_output))
