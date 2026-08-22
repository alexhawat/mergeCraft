"""``mergecraft explain`` — output-only explanation of a finding or the current change (#377).

Exports: ``run``
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import typer
from rich.table import Table

from mergecraft.analyzers.scope import changed_paths_from_scope, parse_diff_scope
from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.errors import cli_bail
from mergecraft.cli.exits import CLI_USAGE_EXIT_CODE
from mergecraft.cli.global_surface import emit_cli_json, wants_json_output
from mergecraft.evidence.audit import lookup_finding_packet


def _read_diff(repo_root: Path) -> str:
    if not (repo_root / ".git").exists():
        return ""
    try:
        completed = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout


def _change_payload(repo_root: Path) -> dict[str, Any]:
    diff = _read_diff(repo_root)
    paths = changed_paths_from_scope(parse_diff_scope(diff)) if diff else []
    return {
        "verb": "explain",
        "finding_id": None,
        "paths": paths,
        "summary": (
            f"{len(paths)} changed path(s) in the working tree."
            if paths
            else "No working-tree diff to explain."
        ),
    }


def _finding_payload(finding_id: str, packet: dict[str, Any]) -> dict[str, Any]:
    state = packet.get("state", "unverified")
    kinds = packet.get("kinds", [])
    kinds_text = ", ".join(str(item) for item in kinds) if isinstance(kinds, list) else "none"
    return {
        "verb": "explain",
        "finding_id": finding_id,
        "paths": [],
        "summary": f"Finding {finding_id} is {state} (kinds: {kinds_text}).",
        "packet": packet,
    }


def _render_table(payload: dict[str, Any]) -> Table:
    table = Table(title="mergecraft explain", show_header=True, header_style="bold")
    table.add_column("field")
    table.add_column("value")
    finding_id = payload.get("finding_id")
    table.add_row("finding_id", str(finding_id) if finding_id else "none")
    paths = payload.get("paths") or []
    table.add_row("paths", ", ".join(str(path) for path in paths) if paths else "none")
    table.add_row("summary", str(payload.get("summary", "")))
    return table


def run(
    ctx: typer.Context,
    finding_id: str | None = typer.Argument(
        default=None,
        help="Optional finding id to explain. Without it, explain the working-tree diff.",
    ),
    repo_root: Path = typer.Option(
        Path("."),
        "--repo-root",
        help="Repository root to read (output-only; nothing is written).",
    ),
) -> None:
    """Explain a stored finding or the current working-tree change."""
    root = repo_root.expanduser().resolve()
    if finding_id:
        packet = lookup_finding_packet(finding_id, repo_root=root)
        if packet is None:
            cli_bail(f"unknown finding id {finding_id}", code=CLI_USAGE_EXIT_CODE)
        payload = _finding_payload(finding_id, packet)
    else:
        payload = _change_payload(root)
    if wants_json_output(ctx, json_flag=False):
        emit_cli_json(payload)
        return
    console.print(_render_table(payload))


__all__ = ["run"]
