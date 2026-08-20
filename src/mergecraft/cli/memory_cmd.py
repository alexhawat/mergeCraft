"""``mergecraft memory`` — repo-scoped memory lifecycle verbs (DG7)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import typer
from loguru import logger

from mergecraft.cli.consoles import err_console as console
from mergecraft.utils.learnings import repo_memory_paths
from mergecraft.utils.memory import (
    FeedbackOutcome,
    export_memory_bundle,
    import_memory_bundle,
    parse_memory_entries_from_learnings,
    record_finding_feedback,
    remove_memory_entry_from_learnings,
)

app = typer.Typer(
    help="Manage repo-scoped review memory (active learnings, feedback, negative rules).",
    no_args_is_help=True,
)


def _learnings_path(repo: Path) -> Path:
    return repo / ".mergecraft" / "learnings.md"


def _load_entries(repo: Path) -> list[dict[str, str]]:
    path = _learnings_path(repo)
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("could not read {}: {}", path, exc)
        return []
    return parse_memory_entries_from_learnings(text)


def _find_entry(entries: list[dict[str, str]], memory_id: str) -> dict[str, str] | None:
    for entry in entries:
        if entry["id"] == memory_id:
            return entry
    return None


@app.command("list")
def list_cmd(
    repo: Path = typer.Option(
        Path("."),
        "--repo",
        "-r",
        help="Repository whose memory should be listed.",
        exists=True,
        file_okay=False,
        dir_okay=True,
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """List active memory entries for a repository."""
    payload: list[dict[str, Any]] = _load_entries(repo)
    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        if not payload:
            typer.echo("(no entries)")
        for entry in payload:
            typer.echo(f"- {entry['id']}: {entry['text']}")
    sys.stdout.flush()


@app.command("show")
def show_cmd(
    memory_id: str,
    repo: Path = typer.Option(
        Path("."),
        "--repo",
        "-r",
        help="Repository whose memory should be shown.",
        exists=True,
        file_okay=False,
        dir_okay=True,
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Show one memory entry by id."""
    entry = _find_entry(_load_entries(repo), memory_id)
    if entry is None:
        console.print(f"[red]unknown memory id {memory_id}[/red]")
        raise typer.Exit(1)
    if json_output:
        typer.echo(json.dumps(entry, indent=2, sort_keys=True))
    else:
        typer.echo(f"id: {entry['id']}\ntext: {entry['text']}")
    sys.stdout.flush()


@app.command("forget")
def forget_cmd(
    memory_id: str,
    repo: Path = typer.Option(
        Path("."),
        "--repo",
        "-r",
        help="Repository whose memory entry should be removed.",
        exists=True,
        file_okay=False,
        dir_okay=True,
    ),
) -> None:
    """Remove one active memory entry."""
    path = _learnings_path(repo)
    if not path.is_file():
        console.print(f"[red]no learnings file at {path}[/red]")
        raise typer.Exit(1)
    if _find_entry(_load_entries(repo), memory_id) is None:
        console.print(f"[red]unknown memory id {memory_id}[/red]")
        raise typer.Exit(1)
    text = path.read_text(encoding="utf-8")
    path.write_text(remove_memory_entry_from_learnings(text, memory_id), encoding="utf-8")
    typer.echo(f"forgot {memory_id}")
    sys.stdout.flush()


@app.command("feedback")
def feedback_cmd(
    fingerprint: str,
    outcome: FeedbackOutcome = typer.Option(
        ...,
        "--outcome",
        "-o",
        help="Developer feedback outcome for the finding fingerprint.",
    ),
    reason: str = typer.Option(..., "--reason", "-r", help="Why this outcome was recorded."),
    pr_number: int | None = typer.Option(None, "--pr", help="Pull request number, when known."),
    repo: Path = typer.Option(
        Path("."),
        "--repo",
        help="Repository whose feedback ledger should be updated.",
        exists=True,
        file_okay=False,
        dir_okay=True,
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Record accepted / dismissed / disputed feedback for a finding fingerprint."""
    feedback_path, _ = repo_memory_paths(repo)
    record = record_finding_feedback(
        store_path=feedback_path,
        fingerprint=fingerprint,
        outcome=outcome,
        reason=reason,
        pr_number=pr_number,
    )
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "fingerprint": record.fingerprint,
                    "outcome": record.outcome.value,
                    "reason": record.reason,
                    "pr_number": record.pr_number,
                    "recorded_at": record.recorded_at.astimezone().isoformat(),
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        typer.echo(f"recorded {record.outcome.value} for {record.fingerprint}")
    sys.stdout.flush()


@app.command("export")
def export_cmd(
    repo: Path = typer.Option(
        Path("."),
        "--repo",
        "-r",
        help="Repository whose memory bundle should be exported.",
        exists=True,
        file_okay=False,
        dir_okay=True,
    ),
    output: Path = typer.Option(..., "--output", "-o", help="Destination JSON file."),
) -> None:
    """Export repo memory to a JSON bundle."""
    bundle = export_memory_bundle(repo=repo)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    typer.echo(f"exported to {output}")
    sys.stdout.flush()


@app.command("import")
def import_cmd(
    bundle_path: Path = typer.Argument(..., exists=True, dir_okay=False, help="Export JSON file."),
    repo: Path = typer.Option(
        Path("."),
        "--repo",
        "-r",
        help="Repository that should receive the bundle.",
        exists=True,
        file_okay=False,
        dir_okay=True,
    ),
) -> None:
    """Import a memory export bundle into a repository."""
    raw = bundle_path.read_text(encoding="utf-8")
    bundle = json.loads(raw)
    if not isinstance(bundle, dict):
        console.print("[red]bundle must be a JSON object[/red]")
        raise typer.Exit(1)
    import_memory_bundle(repo=repo, bundle=bundle)
    typer.echo(f"imported from {bundle_path}")
    sys.stdout.flush()
