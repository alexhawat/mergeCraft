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
from mergecraft.cli.global_surface import OutputFormat, emit_cli_json, wants_json_output
from mergecraft.evidence.audit import lookup_finding_packet
from mergecraft.review.completed import (
    completed_review_exists,
    lookup_finding_packet_in_review,
)


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


def finding_explain_payload(
    finding_id: str,
    packet: dict[str, Any],
    *,
    review_id: str | None = None,
) -> dict[str, Any]:
    state = packet.get("state", "unverified")
    kinds = packet.get("kinds", [])
    kinds_text = ", ".join(str(item) for item in kinds) if isinstance(kinds, list) else "none"
    payload: dict[str, Any] = {
        "verb": "explain",
        "finding_id": finding_id,
        "paths": [],
        "summary": f"Finding {finding_id} is {state} (kinds: {kinds_text}).",
        "packet": packet,
    }
    if review_id is not None:
        payload["review_id"] = review_id
    return payload


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
    review_id_or_finding: str | None = typer.Argument(
        default=None,
        help="Finding id or short id (MC-…). With two arguments: review id then finding id.",
    ),
    finding_id: str | None = typer.Argument(
        default=None,
        help="Short finding id when the first argument is a stored review id.",
    ),
    repo_root: Path = typer.Option(
        Path("."),
        "--repo-root",
        help="Repository root to read (output-only; nothing is written).",
    ),
    review_id: str | None = typer.Option(
        None,
        "--review-id",
        help="Stored review id when explaining a short finding id.",
    ),
    format: OutputFormat | None = typer.Option(
        None,
        "--format",
        help="Output format. Defaults to the root ``--format`` when omitted.",
    ),
) -> None:
    """Explain a stored finding or the current working-tree change."""
    root = repo_root.expanduser().resolve()
    resolved_review_id = review_id
    resolved_finding_id: str | None = None

    if finding_id is not None:
        resolved_review_id = review_id_or_finding
        resolved_finding_id = finding_id
    elif review_id_or_finding is not None:
        token = review_id_or_finding
        if completed_review_exists(token, repo_root=root):
            cli_bail(
                f"{token!r} is a stored review id — pass a finding id (MC-…) "
                "or use: explain <review-id> <finding-id>",
                code=CLI_USAGE_EXIT_CODE,
            )
        resolved_finding_id = token

    if resolved_finding_id:
        packet: dict[str, Any] | None = None
        if resolved_review_id:
            packet = lookup_finding_packet_in_review(
                resolved_review_id,
                resolved_finding_id,
                repo_root=root,
            )
            if packet is None:
                cli_bail(f"unknown finding id {resolved_finding_id}", code=CLI_USAGE_EXIT_CODE)
        else:
            packet = lookup_finding_packet(resolved_finding_id, repo_root=root)
            if packet is None:
                cli_bail(f"unknown finding id {resolved_finding_id}", code=CLI_USAGE_EXIT_CODE)
        payload = finding_explain_payload(
            resolved_finding_id,
            packet,
            review_id=resolved_review_id,
        )
    else:
        payload = _change_payload(root)
    use_json = format == "json" or (format is None and wants_json_output(ctx, json_flag=False))
    if use_json:
        emit_cli_json(payload)
        return
    console.print(_render_table(payload))


__all__ = ["finding_explain_payload", "run"]
