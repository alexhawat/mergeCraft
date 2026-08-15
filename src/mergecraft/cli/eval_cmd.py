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

from mergecraft.evals.benchmark import (
    DEFAULT_BENCHMARK_PROVIDERS,
    DEFAULT_RESULTS_DIR,
    replay_bank,
    write_result_set,
)
from mergecraft.evals.live_run import (
    DEFAULT_DETECTION_CORPUS_DIR,
    run_full_benchmark,
)
from mergecraft.evals.scoring import (
    DEFAULT_LINE_SLACK,
    format_report,
    load_baseline_issues,
    load_reported_findings,
    score_findings,
)
from mergecraft.evals.store import (
    CASE_FILE_SUFFIX,
    CATEGORY_REJECTED,
    CATEGORY_REVERTED,
    DEFAULT_BANK_DIR,
    FAILURE_CATEGORIES,
    PERMANENT_TEST_DIR_NAME,
    Case,
    ReplayDiff,
    add_case,
    list_cases,
    load_case,
    permanent_test_path,
    replay_case,
    write_permanent_test,
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
    from_packet: Path | None = typer.Option(
        None,
        "--from-packet",
        help=(
            "Merge evidence packet (JSON) to record as the case's replay input. "
            "Without it the case cannot be re-decided and a promoted test only "
            "checks that the case still parses."
        ),
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
    recorded_findings: list[dict[str, Any]] | None = None
    run_succeeded = True
    trust_tier_recorded = "trusted"
    if from_packet is not None:
        recorded_findings, run_succeeded, trust_tier_recorded = _replay_inputs_from_packet(
            from_packet
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
            recorded_findings=recorded_findings,
            run_succeeded=run_succeeded,
            trust_tier=trust_tier_recorded,
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


# ── promote ────────────────────────────────────────────────────────────


def _default_permanent_dir() -> Path:
    """Return the default permanent-test target directory.

    Resolves against the current working directory so the CLI works
    regardless of where it is invoked from. Tests pass an explicit
    ``--target-dir`` to override.
    """
    return Path("tests") / "evals" / PERMANENT_TEST_DIR_NAME


@app.command("promote")
def promote(
    case_id: str = typer.Argument(
        ...,
        help="Case id to promote into a permanent pytest test.",
    ),
    target_dir: Path | None = typer.Option(
        None,
        "--target-dir",
        help=("Directory to write the promoted test into (default: tests/evals/permanent/)."),
    ),
    bank: Path | None = typer.Option(
        None,
        "--bank",
        help="Bank directory (default: evals/cases/).",
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="Overwrite an existing permanent test for the same case.",
    ),
) -> None:
    """Promote a case into a permanent pytest test file (#44, W12.1).

    The promoted test re-runs the case against the current code via
    ``mergecraft.evals.store.replay_case`` and fails when the replay
    verdict drifts from the case's recorded expected decision. The
    default replay verdict is ``None`` so a fresh promotion does not
    break the suite; operators wire the running code's verdict via
    the ``MERGECRAFT_PERMANENT_CURRENT_DECISION`` env var to surface
    drift.
    """
    bank_dir = _bank_dir(bank)
    case_path = _case_path(bank_dir, case_id)
    if not case_path.is_file():
        _bail(f"case {case_id!r} not found at {case_path}")
    try:
        case = load_case(case_path)
    except Exception as exc:
        _bail(f"could not load case {case_id!r}: {exc}")
    out_dir = target_dir if target_dir is not None else _default_permanent_dir()
    try:
        target = write_permanent_test(out_dir, case, overwrite=overwrite)
    except FileExistsError:
        _bail(
            f"permanent test for case {case_id!r} already exists at {out_dir}; "
            "use --overwrite to replace"
        )
    except ValueError as exc:
        _bail(str(exc))
    except OSError as exc:
        _bail(f"could not write permanent test to {out_dir}: {exc}")
    console.print(f"[green]promoted case {case_id}[/green] → {target}")


def _replay_inputs_from_packet(path: Path) -> tuple[list[dict[str, Any]], bool, str]:
    """Extract ``decide_approval()``'s three inputs from a merge evidence packet.

    Returns ``(findings_rows, run_succeeded, trust_tier)``. The rows are stored
    verbatim rather than re-validated here: a schema change that invalidates
    them should surface at replay time as "cannot decide", not be silently
    dropped at capture time.
    """
    if not path.is_file():
        _bail(f"{path} is not a file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _bail(f"could not read packet {path}: {exc}")
    if not isinstance(payload, dict):
        _bail(f"{path}: expected a merge evidence packet object")
    rows = payload.get("findings")
    if not isinstance(rows, list):
        _bail(f"{path}: packet has no 'findings' array")
    findings = [row for row in rows if isinstance(row, dict)]
    run = payload.get("run")
    run_succeeded = True
    if isinstance(run, dict) and isinstance(run.get("succeeded"), bool):
        run_succeeded = bool(run["succeeded"])
    tier = "trusted"
    for holder in (payload, run if isinstance(run, dict) else {}):
        value = holder.get("trust_tier") if isinstance(holder, dict) else None
        if value in {"trusted", "untrusted"}:
            tier = str(value)
            break
    return findings, run_succeeded, tier


def _read_json_or_jsonl(path: Path) -> Any:
    """Decode a corpus file that may be JSON or JSON Lines.

    Benchmark corpora ship both shapes — a ``findings`` envelope for Harbor task
    fixtures, and one-object-per-line ``baseline.jsonl`` for promoted baselines —
    so the reader accepts either rather than making the caller know which.
    """
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        rows = [
            json.loads(line)
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("//")
        ]
        if not rows:
            raise
        return rows


# ── replay-bank ────────────────────────────────────────────────────────


@app.command("replay-bank")
def replay_bank_cmd(
    bank: Path | None = typer.Option(
        None,
        "--bank",
        help="Bank directory (default: evals/cases/).",
    ),
    results_dir: Path | None = typer.Option(
        None,
        "--results-dir",
        help="Directory for result sets (default: evals/results/).",
    ),
    provider: list[str] = typer.Option(
        list(DEFAULT_BENCHMARK_PROVIDERS),
        "--provider",
        help="Providers to pin in the result set (repeatable; default claude+openai).",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit the result set as JSON on stdout.",
    ),
    gate: bool = typer.Option(
        False,
        "--gate",
        help="Also print the directional gate matrix (unsafe-approval / clean-block rates).",
    ),
) -> None:
    """Replay the eval bank and write a versioned benchmark result set (#140).

    Structural replay is deterministic and keyless — every replayable case is
    re-decided by the current ``decide_approval`` gate. Finding-location
    precision/recall/F1 against live providers is a separate future path and is
    not recorded by structural replay.
    """
    bank_dir = _bank_dir(bank)
    out_dir = results_dir if results_dir is not None else DEFAULT_RESULTS_DIR
    providers = tuple(provider) if provider else DEFAULT_BENCHMARK_PROVIDERS
    result, path = replay_bank(bank_dir, results_dir=out_dir, providers=providers)
    if json_output:
        typer.echo(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))
    else:
        console.print(f"[green]benchmark result set[/green] → {path}")
        console.print(f"  cases     : {result.metrics.cases_total}")
        console.print(f"  replayable: {result.metrics.cases_replayable}")
        console.print(f"  passed    : {result.metrics.cases_passed}")
        console.print(f"  regression: {result.metrics.cases_regression}")
        console.print(f"  blocked   : {result.metrics.cases_blocked}")
        console.print(f"  pass rate : {result.metrics.decision_replay_pass_rate:.2%}")
        console.print(f"  corpus @  : {result.pins.corpus_commit[:12]}")
        console.print(f"  rubric    : {result.pins.rubric_version}")
        if gate:
            matrix = result.metrics.gate_matrix
            console.print("  gate matrix (directional, #140):")
            console.print(
                f"    buggy : {matrix.buggy_total} total, "
                f"{matrix.buggy_correct_block} correctly blocked, "
                f"{matrix.buggy_unsafe_approval} unsafe approvals, "
                f"{matrix.buggy_inconclusive} inconclusive"
            )
            console.print(
                f"    clean : {matrix.clean_total} total, "
                f"{matrix.clean_correct_approval} correctly approved, "
                f"{matrix.clean_unsafe_block} unsafe blocks, "
                f"{matrix.clean_inconclusive} inconclusive"
            )
            console.print(f"  unsafe approval rate: {result.metrics.unsafe_approval_rate:.2%}")
            console.print(f"  clean block rate    : {result.metrics.clean_block_rate:.2%}")
            console.print(f"  inconclusive rate   : {result.metrics.inconclusive_rate:.2%}")


# ── bench ──────────────────────────────────────────────────────────────


@app.command("bench")
def bench_cmd(
    bank: Path | None = typer.Option(
        None,
        "--bank",
        help="Bank directory for structural replay (default: evals/cases/).",
    ),
    detection_corpus: Path = typer.Option(
        DEFAULT_DETECTION_CORPUS_DIR,
        "--detection-corpus",
        help="Patch-bearing detection-corpus directory.",
    ),
    results_dir: Path | None = typer.Option(
        None,
        "--results-dir",
        help="Directory for result sets (default: evals/results/).",
    ),
    provider: str = typer.Option(
        "claude",
        "--provider",
        help="Provider name recorded on the detection result (structural replay always pins both).",
    ),
    model: str = typer.Option(
        "claude-sonnet-5",
        "--model",
        help="Model slug to check credentials for and drive live detection with.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit the joined result set as JSON on stdout.",
    ),
) -> None:
    """Join structural decision replay with a live finding-location run (#140, B3).

    Structural replay (keyless) always runs. Live detection additionally runs
    ``diff-review`` against the patch-bearing detection corpus, if credentials
    for ``--model`` are available and the corpus is non-empty — otherwise the
    ``detection`` section is omitted and the reason is reported, never
    fabricated (see ``evals/README.md``).
    """
    bank_dir = _bank_dir(bank)
    out_dir = results_dir if results_dir is not None else DEFAULT_RESULTS_DIR
    result = run_full_benchmark(
        bank_dir,
        detection_corpus_dir=detection_corpus,
        results_dir=out_dir,
        providers=DEFAULT_BENCHMARK_PROVIDERS,
        detection_provider=provider,
        detection_model=model,
    )
    path = write_result_set(result, results_dir=out_dir)
    if json_output:
        typer.echo(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))
        return

    console.print(f"[green]benchmark result set[/green] → {path}")
    console.print(f"  structural cases: {result.metrics.cases_total}")
    console.print(f"  pass rate       : {result.metrics.decision_replay_pass_rate:.2%}")
    if result.detection is not None:
        det = result.detection
        console.print(f"  detection cases : {det.cases_run}")
        console.print(f"  recall          : {det.aggregate.recall:.2%}")
        console.print(f"  precision       : {det.aggregate.corpus_confirmed_precision:.2%}")
        console.print(f"  f1              : {det.aggregate.f1:.2%}")
        console.print(f"  raw findings @  : {det.raw_findings_dir}")
    else:
        console.print(f"[yellow]detection skipped[/yellow]: {result.skipped_reason}")


# ── gate ───────────────────────────────────────────────────────────────


@app.command("gate")
def gate(
    bank: Path | None = typer.Option(
        None,
        "--bank",
        help="Bank directory (default: evals/cases/).",
    ),
    require_promoted: bool = typer.Option(
        False,
        "--require-promoted",
        help="Also fail when a case has no permanent test (default: warn only).",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit the result as JSON.",
    ),
) -> None:
    """Check the eval bank's integrity — the CI-safe half of the eval loop.

    This gate is **structural, not behavioural**. It proves every durable case
    still parses against the current schema and provenance model, that ids are
    unique, and (optionally) that each case has been promoted into a permanent
    test. It deliberately does **not** replay verdicts: ``replay_case()`` is a
    pure function that takes the current decision as an *input*, so replaying in
    CI would require a live agent run per case — non-deterministic, key-bearing,
    and far too slow for a per-PR gate.

    The behavioural regression signal is ``mergecraft eval promote``: a promoted
    case becomes a permanent pytest that ``make test`` already runs. This gate's
    job is to stop the bank itself from silently rotting in the meantime.

    An empty bank passes with a notice, so the target can be wired into CI now
    and grow teeth as cases accumulate.
    """
    bank_dir = _bank_dir(bank)
    permanent_dir = _default_permanent_dir()

    if not bank_dir.is_dir():
        if json_output:
            typer.echo(json.dumps({"status": "empty", "bank": str(bank_dir), "cases": 0}, indent=2))
        else:
            console.print(f"[yellow]eval bank {bank_dir} does not exist yet[/yellow]")
        return

    paths = sorted(bank_dir.glob(f"*{CASE_FILE_SUFFIX}"))
    broken: list[dict[str, str]] = []
    seen: dict[str, str] = {}
    duplicates: list[dict[str, str]] = []
    unpromoted: list[str] = []

    for path in paths:
        try:
            case = load_case(path)
        except Exception as exc:  # any parse failure is itself the finding
            broken.append({"path": str(path), "error": str(exc)})
            continue
        if case.id in seen:
            duplicates.append({"id": case.id, "path": str(path), "first": seen[case.id]})
        else:
            seen[case.id] = str(path)
        # Ask the store for the path rather than rebuilding the name here —
        # reconstructing it got the `test_permanent_` prefix wrong and reported
        # every promoted case as unpromoted.
        if not permanent_test_path(permanent_dir, case.id).is_file():
            unpromoted.append(case.id)

    failures = len(broken) + len(duplicates)
    if require_promoted:
        failures += len(unpromoted)

    if json_output:
        typer.echo(
            json.dumps(
                {
                    "status": "fail" if failures else "pass",
                    "bank": str(bank_dir),
                    "cases": len(paths),
                    "loaded": len(seen),
                    "broken": broken,
                    "duplicates": duplicates,
                    "unpromoted": unpromoted,
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        console.print(f"eval bank: {bank_dir}")
        console.print(f"  cases    : {len(paths)}")
        console.print(f"  loaded   : {len(seen)}")
        for row in broken:
            console.print(f"  [red]unparsable[/red]: {row['path']} — {row['error']}")
        for row in duplicates:
            console.print(
                f"  [red]duplicate id[/red]: {row['id']} in {row['path']} "
                f"(first seen {row['first']})"
            )
        if unpromoted:
            colour = "red" if require_promoted else "yellow"
            console.print(f"  [{colour}]not promoted[/{colour}]: {', '.join(unpromoted)}")
        if not paths:
            console.print(
                "  [yellow]bank is empty — the gate passes, but it is not yet "
                "measuring anything[/yellow]"
            )
        elif failures == 0:
            console.print("  [green]bank is healthy[/green]")

    if failures:
        raise typer.Exit(code=1)


# ── score ──────────────────────────────────────────────────────────────


@app.command("score")
def score(
    actual: Path = typer.Argument(..., help="JSON findings a review run produced."),
    expected: Path = typer.Argument(..., help="JSON baseline issues to score against."),
    min_recall: float = typer.Option(
        0.0,
        "--min-recall",
        help="Exit non-zero when recall falls below this fraction (0.0-1.0).",
    ),
    slack: int = typer.Option(
        DEFAULT_LINE_SLACK,
        "--slack",
        help="Line distance still counted as locating a baseline issue.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit the score report as JSON.",
    ),
) -> None:
    """Score review findings against a frozen benchmark baseline.

    A baseline issue counts as located when a reported finding overlaps its line
    range in the same file — **not** when the two rows are equal. Equality
    scoring fails a run for paraphrasing a finding it genuinely found, and it
    cannot pass at all against a corpus whose rows carry their own ``rule_id``
    and ``fingerprint``.

    Severity and category agreement are reported alongside each match, never as
    conditions for it.
    """
    for path in (actual, expected):
        if not path.is_file():
            _bail(f"{path} is not a file")
    try:
        actual_payload = _read_json_or_jsonl(actual)
        expected_payload = _read_json_or_jsonl(expected)
    except (OSError, json.JSONDecodeError) as exc:
        _bail(f"could not read scoring inputs: {exc}")

    issues = load_baseline_issues(expected_payload)
    findings = load_reported_findings(actual_payload)
    report = score_findings(issues, findings, slack=slack)

    if json_output:
        typer.echo(
            json.dumps(
                {
                    "total_issues": report.total_issues,
                    "total_reported": report.total_reported,
                    "found": report.found,
                    "recall": report.recall,
                    "precision": report.precision,
                    "severity_agreement": report.severity_agreement,
                    "missed_issue_ids": report.missed_issue_ids,
                    "matches": [m.model_dump() for m in report.matches],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        console.print(format_report(report, corpus=expected))

    if report.recall < min_recall:
        console.print(
            f"[red]recall {report.recall:.2%} is below the required {min_recall:.2%}[/red]"
        )
        raise typer.Exit(code=1)


__all__ = ["CATEGORY_REJECTED", "CATEGORY_REVERTED", "FAILURE_CATEGORIES", "app"]
