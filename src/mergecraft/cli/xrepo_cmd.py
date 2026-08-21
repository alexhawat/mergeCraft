"""``mergecraft xrepo`` — explain cross-repo contract findings (#353 / D10).

Output-only (D13): never writes into the reviewed tree.
"""

from __future__ import annotations

from pathlib import Path

import typer

from mergecraft.cli.errors import cli_bail
from mergecraft.cli.exits import CLI_USAGE_EXIT_CODE
from mergecraft.cli.global_surface import emit_cli_json, wants_json_output
from mergecraft.xrepo.review import (
    XrepoFinding,
    XrepoReview,
    review_linked_repos,
)

app = typer.Typer(
    name="xrepo",
    help="Explain cross-repo contract findings from SHA-pinned linked repositories.",
    no_args_is_help=True,
)


def _render_finding(finding: XrepoFinding) -> str:
    impact = finding.impact
    changed = impact.changed_contract
    return "\n".join(
        [
            f"# {finding.finding_id}",
            "",
            f"Consumer: {impact.repo} @ {impact.commit}",
            f"Producer: {changed.repo} @ {changed.commit}",
            f"Contract: {changed.path} ({changed.kind})",
            f"Break: {impact.reason}",
            "",
        ]
    )


def _render_report(review: XrepoReview) -> str:
    if not review.findings:
        producer = review.producer.slug if review.producer is not None else "linked repos"
        return "\n".join(
            [
                "# Cross-repo contract review",
                "",
                f"No consumer breakage detected for {producer}.",
                "",
            ]
        )
    lines = ["# Cross-repo contract review", ""]
    for finding in review.findings:
        lines.append(_render_finding(finding).rstrip())
        lines.append("")
    return "\n".join(lines) + "\n"


def _finding_payload(finding: XrepoFinding) -> dict[str, object]:
    impact = finding.impact
    changed = impact.changed_contract
    return {
        "id": finding.finding_id,
        "consumer": impact.repo,
        "consumer_commit": impact.commit,
        "producer": changed.repo,
        "producer_commit": changed.commit,
        "contract_path": changed.path,
        "kind": changed.kind,
        "reason": impact.reason,
    }


@app.command("explain")
def explain_cmd(
    ctx: typer.Context,
    finding_id: str | None = typer.Argument(
        None,
        help="Stable finding id (for example XR-001). Omit to report producer/consumer breakage.",
    ),
    repo_root: Path = typer.Option(
        Path("."),
        "--repo-root",
        help="Repository root that owns .mergecraft/linked-repos.yaml (output-only).",
    ),
    producer: str | None = typer.Option(
        None,
        "--producer",
        help="Linked producer repo (owner/name or bare name) whose contracts to explain.",
    ),
) -> None:
    """Explain a cross-repo finding, or report producer/consumer contract breakage."""
    root = repo_root.expanduser().resolve()
    review = review_linked_repos(repo_root=root, producer=producer)
    if finding_id is not None:
        match = next((item for item in review.findings if item.finding_id == finding_id), None)
        if match is None:
            cli_bail(f"unknown finding id {finding_id}", code=CLI_USAGE_EXIT_CODE)
        if wants_json_output(ctx, json_flag=False):
            emit_cli_json(_finding_payload(match))
            return
        typer.echo(_render_finding(match))
        return
    if wants_json_output(ctx, json_flag=False):
        emit_cli_json(
            {
                "producer": review.producer.slug if review.producer is not None else None,
                "findings": [_finding_payload(item) for item in review.findings],
            }
        )
        return
    typer.echo(_render_report(review))


__all__ = ["app", "explain_cmd"]
