"""``mergecraft findings`` — read and carry forward a pull request's findings.

Two commands over one selection rule. ``export`` reads what a merge would bury
and prints it; ``carryover`` files the survivors as issues. ``export`` never
writes, and ``carryover`` writes only under ``--apply`` — the bare command
prints the plan, so the sweep can be pointed at a repository and inspected
before it is trusted with an automation trigger.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

import typer

from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.exits import (
    CLI_CONFIGURATION_EXIT_CODE,
    CLI_USAGE_EXIT_CODE,
)
from mergecraft.cli.global_surface import emit_cli_json, get_cli_globals, wants_json_output
from mergecraft.findings.select import (
    DEFAULT_LABEL,
    CarryoverFinding,
    carryover_findings,
    issue_title,
)
from mergecraft.findings.sweep import (
    CarryoverOutcome,
    CarryoverPlan,
    apply_carryover,
    plan_carryover,
)
from mergecraft.findings.threads import fetch_review_threads
from mergecraft.scm.github import GitHubScmAdapter
from mergecraft.utils.github import GitHubClient, parse_repo_context
from mergecraft.utils.token import get_job_token

app = typer.Typer(
    help="Inspect and carry forward review findings a merge would otherwise bury.",
    no_args_is_help=True,
)

_REPO_HELP = "Repository as owner/name. Defaults to $GITHUB_REPOSITORY."
_RESOLVED_HELP = "Include threads the author already resolved."
_ANSWERED_HELP = (
    "Include threads a human replied to (skipped by default: a reply means "
    "somebody already ruled on the finding)."
)


def _resolve_repo(repo: str | None) -> tuple[str, str]:
    """Return ``(owner, name)`` from ``--repo`` or the ambient environment."""
    try:
        ctx = parse_repo_context(repo)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(CLI_USAGE_EXIT_CODE) from exc
    return ctx.owner, ctx.name


def _client() -> GitHubClient:
    """Return an authenticated client, or exit with a readable message."""
    try:
        return GitHubClient(get_job_token())
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(CLI_USAGE_EXIT_CODE) from exc


def _finding_payload(finding: CarryoverFinding) -> dict[str, Any]:
    return finding.model_dump(mode="json")


def _render_markdown(findings: list[CarryoverFinding], *, pull_number: int) -> str:
    """Render findings as a review-style markdown digest."""
    if not findings:
        return f"No carryover findings on #{pull_number}."
    lines = [f"# Carryover findings — #{pull_number}", ""]
    for finding in findings:
        anchor = f"{finding.path}:{finding.line}" if finding.line else finding.path
        lines.append(f"## {anchor or '(no file)'}")
        lines.append("")
        if finding.url:
            lines.append(f"[thread]({finding.url}) · `{finding.fingerprint}`")
        else:
            lines.append(f"`{finding.fingerprint}`")
        lines.append("")
        lines.append(finding.body)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


@app.command("export")
def export(
    ctx: typer.Context,
    pr: Annotated[int, typer.Option("--pr", help="Pull request number.")],
    repo: Annotated[str | None, typer.Option("--repo", help=_REPO_HELP)] = None,
    output_format: Annotated[
        str | None,
        typer.Option(
            "--output-format",
            help=(
                "Export payload format: json or markdown (default: markdown). "
                "Root --format json emits JSON when this flag is omitted; "
                "explicit --output-format markdown always renders markdown."
            ),
        ),
    ] = None,
    include_resolved: Annotated[
        bool, typer.Option("--include-resolved", help=_RESOLVED_HELP)
    ] = False,
    include_answered: Annotated[
        bool, typer.Option("--include-answered", help=_ANSWERED_HELP)
    ] = False,
) -> None:
    """Print the findings a merge would bury. Never writes anything."""
    if output_format is not None and output_format not in {"json", "markdown"}:
        console.print("[red]--output-format must be 'json' or 'markdown'[/red]")
        raise typer.Exit(CLI_USAGE_EXIT_CODE)
    emit_json = (
        output_format == "json"
        if output_format is not None
        else get_cli_globals(ctx).format == "json"
    )
    owner, name = _resolve_repo(repo)

    async def _run() -> list[CarryoverFinding]:
        client = _client()
        try:
            page = await fetch_review_threads(
                GitHubScmAdapter(client), owner, name, pr, include_resolved=include_resolved
            )
            if page.truncated:
                console.print(
                    f"[yellow]#{pr} has {page.total_count} review threads; only the "
                    "first page was read.[/yellow]"
                )
            return carryover_findings(
                page.threads,
                include_resolved=include_resolved,
                include_answered=include_answered,
            )
        finally:
            await client.aclose()

    findings = asyncio.run(_run())
    if emit_json:
        emit_cli_json(
            {
                "pull_number": pr,
                "count": len(findings),
                "findings": [_finding_payload(f) for f in findings],
            }
        )
        return
    typer.echo(_render_markdown(findings, pull_number=pr))


def _print_plan(plan: CarryoverPlan) -> None:
    """Print a human-readable dry-run plan."""
    if plan.already_filed:
        console.print(
            f"[dim]{len(plan.already_filed)} finding(s) already have an issue; skipping.[/dim]"
        )
    if not plan.to_file:
        console.print(f"Nothing to carry over from #{plan.pull_number}.")
        return
    console.print(f"[bold]Would file {len(plan.to_file)} issue(s) from #{plan.pull_number}:[/bold]")
    for finding in plan.to_file:
        # markup=False: titles are `[carryover #N] …`, which Rich would eat as a tag.
        console.print(f"  • {issue_title(finding, pull_number=plan.pull_number)}", markup=False)
    console.print("[dim]Re-run with --apply to file them.[/dim]")


@app.command("carryover")
def carryover(
    ctx: typer.Context,
    pr: Annotated[int, typer.Option("--pr", help="Pull request number.")],
    repo: Annotated[str | None, typer.Option("--repo", help=_REPO_HELP)] = None,
    label: Annotated[
        str,
        typer.Option(
            "--label",
            help="Label applied to filed issues, and read back to avoid duplicates.",
        ),
    ] = DEFAULT_LABEL,
    apply: Annotated[
        bool,
        typer.Option("--apply", help="Actually file the issues. Off by default."),
    ] = False,
    include_resolved: Annotated[
        bool, typer.Option("--include-resolved", help=_RESOLVED_HELP)
    ] = False,
    include_answered: Annotated[
        bool, typer.Option("--include-answered", help=_ANSWERED_HELP)
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit the plan or result as JSON on stdout."),
    ] = False,
) -> None:
    """File one issue per unresolved mergeCraft finding. Dry run unless ``--apply``."""
    owner, name = _resolve_repo(repo)

    async def _run() -> tuple[CarryoverPlan, CarryoverOutcome | None]:
        client = _client()
        try:
            plan = await plan_carryover(
                client,
                owner,
                name,
                pr,
                label=label,
                include_resolved=include_resolved,
                include_answered=include_answered,
            )
            if not apply:
                return plan, None
            return plan, await apply_carryover(client, owner, name, plan, label=label)
        finally:
            await client.aclose()

    try:
        plan, outcome = asyncio.run(_run())
    except ValueError as exc:  # truncated read — filing it would drop findings
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(CLI_CONFIGURATION_EXIT_CODE) from exc

    if wants_json_output(ctx, json_flag=json_output):
        emit_cli_json(
            {
                "applied": outcome is not None,
                "pull_number": plan.pull_number,
                "truncated": plan.truncated,
                "to_file": [_finding_payload(f) for f in plan.to_file],
                "already_filed": [_finding_payload(f) for f in plan.already_filed],
                "filed": [i.model_dump(mode="json") for i in (outcome.filed if outcome else [])],
                "failed": [f.model_dump(mode="json") for f in (outcome.failed if outcome else [])],
            }
        )
    elif outcome is None:
        _print_plan(plan)
    elif not outcome.filed and not outcome.failed:
        console.print(f"Nothing to carry over from #{plan.pull_number}.")
    else:
        if outcome.filed:
            console.print(
                f"[green]Filed {len(outcome.filed)} issue(s) from #{plan.pull_number}:[/green]"
            )
            for issue in outcome.filed:
                console.print(f"  • #{issue.number} {issue.title}", markup=False)
        for failure in outcome.failed:
            console.print(f"[red]Could not file:[/red] {failure.title}", markup=False)

    # A partial write must not look like success: the closing event that
    # triggered the sweep does not fire again, so an unfiled finding is lost
    # unless the run is visibly red.
    if outcome is not None and outcome.failed:
        raise typer.Exit(CLI_CONFIGURATION_EXIT_CODE)


__all__ = ["app"]
