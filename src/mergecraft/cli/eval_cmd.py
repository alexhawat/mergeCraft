"""``mergecraft eval`` — file-backed Failure Memory and Eval Bank (#51).

The CLI is the **I/O shell** around the pure store at
``mergecraft.evals.store``. It owns the prompt for the ``add`` flow,
the file walking for ``list``, and the deterministic ``replay`` rule.
The replay engine itself is a pure function the caller can drive from
tests; the CLI hands the rule the verdict the running code produced.

Subcommands:

- ``add`` — capture a new case from a merge-evidence packet.
- ``list`` — list cases, with optional filters and JSON output.
- ``replay`` — re-run a case and report the diff vs. the recorded
  expected decision.

The bank is **local** (D13) — no database, no hosted service. The
default path is the ``evals/cases/`` directory that PR #54 first
scaffolded; the CLI accepts an override so tests can use a tmpdir.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

import typer
from pydantic import ValidationError
from rich.console import Console

from mergecraft.evals.store import (
    CASE_FILE_SUFFIX,
    DEFAULT_BANK_DIR,
    Case,
    ReplayDiff,
    add_case,
    list_cases,
    load_case,
    replay_case,
)
from mergecraft.utils.learnings import LearningProvenance

app = typer.Typer(
    help=(
        "Manage the file-backed Failure Memory and Eval Bank. "
        "Cases live under evals/cases/ by default (D13)."
    ),
    no_args_is_help=True,
)
console = Console()


# ── helpers ────────────────────────────────────────────────────────────


def _bail(msg: str) -> NoReturn:
    console.print(f"[red]{msg}[/red]")
    raise typer.Exit(1)


def _bank_dir(bank: Path | None) -> Path:
    """Return the resolved bank directory (default = ``evals/cases/``)."""
    return bank if bank is not None else DEFAULT_BANK_DIR


def _case_path(bank_dir: Path, case_id: str) -> Path:
    """Return the on-disk path for ``case_id`` under ``bank_dir``."""
    if not case_id or not case_id.replace("-", "").replace("_", "").replace(".", "").isalnum():
        _bail(f"invalid case id: {case_id!r}")
    return bank_dir / f"{case_id}{CASE_FILE_SUFFIX}"


def _case_to_json(case: Case) -> dict[str, Any]:
    """Return the JSON-safe dict representation of a case."""
    return case.model_dump(mode="json")


def _format_human(case: Case) -> str:
    """Render a case as a one-line human-readable summary."""
    pr_part = f" pr=#{case.pr_number}" if case.pr_number is not None else ""
    return (
        f"- {case.id} [{case.category}] {case.title} "
        f"(submitted={case.submitted_at.isoformat()}{pr_part}, "
        f"expected={case.expected_decision})"
    )


def _format_diff_human(diff: ReplayDiff) -> str:
    """Render a :class:`ReplayDiff` as a human-readable text block."""
    lines = [
        f"case: {diff.case_id}",
        f"expected: {diff.expected_decision}",
        f"current:  {diff.current_decision or '(unavailable)'}",
        f"status:   {diff.status}",
    ]
    if diff.notes:
        lines.append(f"notes:    {diff.notes}")
    return "\n".join(lines)


def _format_diff_json(diff: ReplayDiff) -> str:
    """Render a :class:`ReplayDiff` as JSON."""
    return json.dumps(diff.model_dump(mode="json"), indent=2, sort_keys=True)


def _resolve_synthetic_provenance(
    *,
    run_id: str,
    pr_number: int | None,
    author: str,
    trust_tier: str,
) -> LearningProvenance:
    """Build a synthetic provenance record for the ``add`` flow.

    The CLI prompts for the fields it does not have a default for. The
    default is a *trusted* synthetic record so the test suite can drop
    cases in without an actual GitHub run. Operators in production use
    the same CLI by passing ``--author`` and ``--pr-number`` to override
    the synthetic defaults.
    """
    return LearningProvenance(
        run_id=run_id,
        pr_number=pr_number,
        source_field="eval_bank",
        author_login=author,
        author_association="OWNER",
        trust_tier=trust_tier,  # type: ignore[arg-type]
        timestamp=datetime.now(UTC),
    )


# ── add ────────────────────────────────────────────────────────────────


@app.command("add")
def add(
    case_id: str = typer.Option(
        ...,
        "--id",
        help="Stable identifier for the case (e.g. 'synthetic-001').",
    ),
    title: str = typer.Option(
        ...,
        "--title",
        help="Short, operator-readable description of the failure.",
    ),
    category: str = typer.Option(
        ...,
        "--category",
        help="Failure category (e.g. 'missed_finding', 'false_positive').",
    ),
    failure_mode: str = typer.Option(
        ...,
        "--failure-mode",
        help="What went wrong (e.g. 'missed_finding', 'ignored_tool_error').",
    ),
    expected_finding: str = typer.Option(
        ...,
        "--expected-finding",
        help="The finding the merge evidence packet should have produced.",
    ),
    expected_decision: str = typer.Option(
        ...,
        "--expected-decision",
        help="The verdict the packet should have produced (block, auto_merge, ...).",
    ),
    run_id: str = typer.Option(
        "synthetic",
        "--run-id",
        help="The run id the case came from (default 'synthetic').",
    ),
    pr_number: int | None = typer.Option(
        None,
        "--pr-number",
        help="Optional PR number the case is attached to.",
    ),
    author: str = typer.Option(
        "synthetic",
        "--author",
        help="Author login to record in the provenance (default 'synthetic').",
    ),
    trust_tier: str = typer.Option(
        "trusted",
        "--trust-tier",
        help="Trust tier for the provenance record (default 'trusted').",
    ),
    body: str = typer.Option(
        "",
        "--body",
        help="Free-form description of the failure mode (markdown).",
    ),
    bank: Path | None = typer.Option(
        None,
        "--bank",
        help="Bank directory (default: evals/cases/).",
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="Overwrite an existing case with the same id.",
    ),
) -> None:
    """Add a case to the bank.

    Validates the front-matter against the schema (D13) and the
    embedded :class:`LearningProvenance` (D5). Prompts are not used:
    every flag is supplied so the add flow is non-interactive and
    automatable.

    The script-friendly flags match the ``render_case_text`` shape
    one-to-one; the rendered file is the audit record.
    """
    bank_dir = _bank_dir(bank)
    provenance = _resolve_synthetic_provenance(
        run_id=run_id,
        pr_number=pr_number,
        author=author,
        trust_tier=trust_tier,
    )
    try:
        case = Case(
            id=case_id,
            title=title,
            category=category,
            submitted_at=datetime.now(UTC),
            run_id=run_id,
            pr_number=pr_number,
            failure_mode=failure_mode,
            expected_finding=expected_finding,
            expected_decision=expected_decision,
            replay_command=f"mergecraft eval replay {case_id}",
            provenance=provenance,
            body=body,
        )
    except ValidationError as exc:
        _bail(f"case failed validation: {exc}")
    try:
        target = add_case(bank_dir, case, overwrite=overwrite)
    except FileExistsError:
        _bail(f"case {case_id!r} already exists at {bank_dir}; use --overwrite to replace")
    except OSError as exc:
        _bail(f"could not write case to {bank_dir}: {exc}")
    console.print(f"[green]added case {case_id}[/green] → {target}")


# ── list ───────────────────────────────────────────────────────────────


@app.command("list")
def list_cmd(
    category: str | None = typer.Option(
        None,
        "--category",
        help="Filter by exact category.",
    ),
    since: str | None = typer.Option(
        None,
        "--since",
        help="Filter by submitted_at >= ISO-8601 timestamp (e.g. 2026-08-01).",
    ),
    id_prefix: str | None = typer.Option(
        None,
        "--id-prefix",
        help="Filter by case id prefix (e.g. 'synthetic').",
    ),
    bank: Path | None = typer.Option(
        None,
        "--bank",
        help="Bank directory (default: evals/cases/).",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit JSON instead of a human-readable listing.",
    ),
) -> None:
    """List cases in the bank.

    Filters are optional; without them the command lists every case.
    The listing is sorted by ``submitted_at`` ascending. The JSON
    output mirrors the case schema one-to-one.
    """
    bank_dir = _bank_dir(bank)
    since_dt: datetime | None = None
    if since is not None:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError:
            _bail(f"--since must be an ISO-8601 timestamp; got {since!r}")
    cases = list_cases(
        bank_dir,
        category=category,
        since=since_dt,
        id_prefix=id_prefix,
    )
    if json_output:
        payload = [_case_to_json(c) for c in cases]
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    if not cases:
        console.print(f"[yellow]no cases in {bank_dir}[/yellow]")
        return
    for case in cases:
        console.print(_format_human(case))


# ── replay ─────────────────────────────────────────────────────────────


@app.command("replay")
def replay(
    case_id: str = typer.Argument(..., help="Case id to replay."),
    current_decision: str | None = typer.Option(
        None,
        "--current-decision",
        help=(
            "The verdict the current code produced. When omitted, the replay "
            "marks the case as 'blocked' (the replay engine cannot compute a "
            "verdict without one)."
        ),
    ),
    bank: Path | None = typer.Option(
        None,
        "--bank",
        help="Bank directory (default: evals/cases/).",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit the diff as JSON.",
    ),
) -> None:
    """Replay a case and report the diff.

    The function is deterministic: the current verdict is an operator
    input. The replay engine (``mergecraft.evals.store.replay_case``) is
    pure and side-effect-free; the CLI is the I/O shell that asks the
    caller for the verdict, looks up the case, and prints the diff.
    """
    bank_dir = _bank_dir(bank)
    case_path = _case_path(bank_dir, case_id)
    if not case_path.is_file():
        _bail(f"case {case_id!r} not found at {case_path}")
    try:
        case = load_case(case_path)
    except Exception as exc:
        _bail(f"could not load case {case_id!r}: {exc}")
    diff = replay_case(case, current_decision=current_decision)
    if json_output:
        typer.echo(_format_diff_json(diff))
    else:
        console.print(_format_diff_human(diff))
    if diff.status == "regression":
        # Exit non-zero so a CI loop can latch on the regression.
        raise typer.Exit(2)


__all__ = ["app"]
