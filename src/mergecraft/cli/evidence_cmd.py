"""``mergecraft evidence`` — show and verify finding evidence packets (#354 / D10).

Output-only: never writes the reviewed tree. Does not call ``decide_approval()``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, NoReturn

import typer

from mergecraft.cli.errors import cli_bail
from mergecraft.cli.exits import CLI_USAGE_EXIT_CODE
from mergecraft.cli.global_surface import emit_cli_json, wants_json_output
from mergecraft.evidence.audit import (
    FALSIFICATION_RUBRIC,
    VERIFIER_STATES,
    lookup_finding_packet,
    replay_verification,
)

app = typer.Typer(
    name="evidence",
    help="Show and verify evidence packets for a finding.",
    no_args_is_help=True,
)


def _unknown_finding(finding_id: str) -> NoReturn:
    cli_bail(f"unknown finding id {finding_id}", code=CLI_USAGE_EXIT_CODE)


def _render_packet(finding_id: str, packet: dict[str, Any]) -> str:
    kinds = packet.get("kinds", [])
    kinds_text = ", ".join(str(item) for item in kinds) if isinstance(kinds, list) else "none"
    state = packet.get("state", "unverified")
    return "\n".join(
        [
            f"# Finding {finding_id}",
            "",
            f"State: {state}",
            f"Kinds: {kinds_text}",
            f"Captured: {packet.get('captured_at', 'unknown')}",
            "",
            "Verifier states: " + ", ".join(sorted(VERIFIER_STATES)),
            "",
        ]
    )


@app.command("show")
def show_cmd(
    ctx: typer.Context,
    finding_id: str = typer.Argument(
        help="Finding id (fingerprint) whose evidence packet to display.",
    ),
    repo_root: Path = typer.Option(
        Path("."),
        "--repo-root",
        help="Repository root that may own .mergecraft/evidence (output-only).",
    ),
) -> None:
    """Show the evidence packet for a finding."""
    root = repo_root.expanduser().resolve()
    packet = lookup_finding_packet(finding_id, repo_root=root)
    if packet is None:
        _unknown_finding(finding_id)
    if wants_json_output(ctx, json_flag=False):
        emit_cli_json(packet)
        return
    typer.echo(_render_packet(finding_id, packet))


@app.command("verify")
def verify_cmd(
    ctx: typer.Context,
    finding_id: str = typer.Argument(
        help="Finding id (fingerprint) to verify against its evidence packet.",
    ),
    repo_root: Path = typer.Option(
        Path("."),
        "--repo-root",
        help="Repository root that may own .mergecraft/evidence (output-only).",
    ),
) -> None:
    """Replay verification for a finding's evidence packet (not an approval)."""
    root = repo_root.expanduser().resolve()
    packet = lookup_finding_packet(finding_id, repo_root=root)
    if packet is None:
        _unknown_finding(finding_id)
    replay = replay_verification(packet)
    payload = {
        "finding_id": finding_id,
        "replay": replay,
        "rubric": FALSIFICATION_RUBRIC,
    }
    if wants_json_output(ctx, json_flag=False):
        emit_cli_json(payload)
        return
    typer.echo(
        "\n".join(
            [
                f"# Verify {finding_id}",
                "",
                f"State: {replay['state']}",
                f"Digest: {replay['digest']}",
                f"Completeness: {replay['completeness']}",
                "",
                FALSIFICATION_RUBRIC,
                "",
            ]
        )
    )


__all__ = ["app", "show_cmd", "verify_cmd"]
