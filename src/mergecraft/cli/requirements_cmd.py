"""``mergecraft requirements`` — inspect and explain mapped requirements (#352 / D10).

Output-only (D13): never writes into the reviewed tree.
"""

from __future__ import annotations

from pathlib import Path

import typer

from mergecraft.cli.errors import cli_bail
from mergecraft.cli.exits import CLI_USAGE_EXIT_CODE
from mergecraft.cli.global_surface import emit_cli_json, wants_json_output
from mergecraft.requirements import (
    REQUIREMENT_STATES,
    IngestResult,
    Requirement,
    ingest_requirements,
)

app = typer.Typer(
    name="requirements",
    help="Inspect and explain requirements mapped from tickets and local specs.",
    no_args_is_help=True,
)


def _inspect_repo(
    *,
    repo_root: Path,
    source: str,
) -> tuple[IngestResult, list[Requirement]]:
    ingested = ingest_requirements(source=source, repo_root=repo_root)
    return ingested, list(ingested.requirements)


def _render_inspect(requirements: list[Requirement]) -> str:
    state_legend = ", ".join(sorted(REQUIREMENT_STATES))
    if not requirements:
        return "\n".join(
            [
                "# Requirements",
                "",
                "No atomic requirements found.",
                "",
                f"States: {state_legend}",
                "",
            ]
        )
    lines = ["# Requirements", ""]
    for item in requirements:
        evidence = ", ".join(item.evidence_paths) if item.evidence_paths else "none"
        lines.append(
            f"- {item.requirement_id} [{item.state}] {item.text} "
            f"(source: {item.source} {item.source_ref}; evidence: {evidence})"
        )
    lines.extend(["", f"States: {state_legend}", ""])
    return "\n".join(lines)


def _render_explain(item: Requirement) -> str:
    evidence = ", ".join(item.evidence_paths) if item.evidence_paths else "none"
    return "\n".join(
        [
            f"# {item.requirement_id}",
            "",
            f"State: {item.state}",
            f"Kind: {item.kind}",
            f"Source: {item.source} ({item.source_ref})",
            f"Evidence: {evidence}",
            "",
            item.text,
            "",
        ]
    )


@app.command("inspect")
def inspect_cmd(
    ctx: typer.Context,
    repo_root: Path = typer.Option(
        Path("."),
        "--repo-root",
        help="Repository root to read (output-only; nothing is written).",
    ),
    source: str = typer.Option(
        "local_spec",
        "--source",
        help="Ingest source: pr_description, linked_issue, or local_spec.",
    ),
) -> None:
    """List ingested requirements and their states."""
    root = repo_root.expanduser().resolve()
    ingested, requirements = _inspect_repo(repo_root=root, source=source)
    if wants_json_output(ctx, json_flag=False):
        emit_cli_json(
            {
                "source": ingested.source,
                "source_ref": ingested.source_ref,
                "states": sorted(REQUIREMENT_STATES),
                "requirements": [
                    {
                        "id": item.requirement_id,
                        "state": str(item.state),
                        "kind": item.kind,
                        "text": item.text,
                        "source": item.source,
                        "source_ref": item.source_ref,
                        "evidence_paths": list(item.evidence_paths),
                    }
                    for item in requirements
                ],
            }
        )
        return
    typer.echo(_render_inspect(requirements))


@app.command("explain")
def explain_cmd(
    ctx: typer.Context,
    requirement_id: str = typer.Argument(help="Stable requirement id (for example REQ-001)."),
    repo_root: Path = typer.Option(
        Path("."),
        "--repo-root",
        help="Repository root to read (output-only; nothing is written).",
    ),
    source: str = typer.Option(
        "local_spec",
        "--source",
        help="Ingest source used to resolve the id.",
    ),
) -> None:
    """Explain one requirement by id; unknown ids are an error."""
    root = repo_root.expanduser().resolve()
    _ingested, requirements = _inspect_repo(repo_root=root, source=source)
    match = next((item for item in requirements if item.requirement_id == requirement_id), None)
    if match is None:
        cli_bail(f"unknown requirement id {requirement_id}", code=CLI_USAGE_EXIT_CODE)
    if wants_json_output(ctx, json_flag=False):
        emit_cli_json(
            {
                "id": match.requirement_id,
                "state": str(match.state),
                "kind": match.kind,
                "text": match.text,
                "source": match.source,
                "source_ref": match.source_ref,
                "evidence_paths": list(match.evidence_paths),
            }
        )
        return
    typer.echo(_render_explain(match))


__all__ = ["app", "explain_cmd", "inspect_cmd"]
