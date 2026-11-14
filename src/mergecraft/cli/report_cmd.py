"""Write aggregate metrics from stored mergeCraft evidence packets.

Exports:
    run: CLI entry point for `mergecraft report`.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from mergecraft.cli.errors import cli_bail
from mergecraft.cli.exits import CLI_USAGE_EXIT_CODE
from mergecraft.evidence.report import summarize_packets


def run(
    packets: list[Path] = typer.Argument(
        ..., help="Packet files or extracted artifact directories."
    ),
    output: Path = typer.Option(..., "--output", "-o", help="New JSON report file."),
) -> None:
    """Write review metrics from stored evidence packets."""
    try:
        summary = summarize_packets(packets)
        content = json.dumps(summary, indent=2, allow_nan=False)
        with output.open("x", encoding="utf-8") as report:
            report.write(content + "\n")
    except (OSError, ValueError, OverflowError) as exc:
        cli_bail(f"Could not write review report: {exc}", code=CLI_USAGE_EXIT_CODE)
