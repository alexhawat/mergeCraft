"""``mergecraft eval gate`` — structural bank integrity and release regression checks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.errors import cli_bail
from mergecraft.cli.eval_cli_output import default_permanent_dir
from mergecraft.cli.exits import CLI_CONFIGURATION_EXIT_CODE
from mergecraft.cli.global_surface import emit_cli_json, wants_json_output
from mergecraft.evals.gate import DEFAULT_GATE_TOLERANCE, eval_gate, load_result_set
from mergecraft.evals.store import (
    CASE_FILE_SUFFIX,
    DEFAULT_BANK_DIR,
    load_case,
    permanent_test_path,
)


def _bank_dir(bank: Path | None) -> Path:
    return bank if bank is not None else DEFAULT_BANK_DIR


def register_gate_command(app: typer.Typer) -> None:
    """Attach the ``gate`` subcommand to the eval Typer app."""

    @app.command("gate")
    def gate(
        ctx: typer.Context,
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
        baseline: Path | None = typer.Option(
            None,
            "--baseline",
            help="Baseline benchmark result set (JSON) for the release regression gate (EV3).",
        ),
        candidate: Path | None = typer.Option(
            None,
            "--candidate",
            help="Candidate benchmark result set (JSON) for the release regression gate (EV3).",
        ),
        tolerance: float = typer.Option(
            DEFAULT_GATE_TOLERANCE,
            "--tolerance",
            help="Declared tolerance band for the release regression gate.",
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

        With ``--baseline`` and ``--candidate`` (both required together) the
        command also runs the **release regression gate** (EV3): the candidate
        result set is compared against the published baseline with the declared
        ``--tolerance`` band via ``mergecraft.evals.gate.eval_gate`` — a metric
        that regresses beyond the band fails the release, noise inside it passes.
        """
        if (baseline is None) != (candidate is None):
            cli_bail("--baseline and --candidate must be given together")

        gate_report = None
        if baseline is not None and candidate is not None:
            gate_report = eval_gate(
                candidate=load_result_set(candidate),
                baseline=load_result_set(baseline),
                tolerance=tolerance,
            )

        bank_dir = _bank_dir(bank)
        permanent_dir = default_permanent_dir()

        if not bank_dir.is_dir():
            if wants_json_output(ctx, json_flag=json_output):
                emit_cli_json({"status": "empty", "bank": str(bank_dir), "cases": 0})
            else:
                console.print(f"[yellow]eval bank {bank_dir} does not exist yet[/yellow]")
            if gate_report is not None and not gate_report.passed:
                raise typer.Exit(code=CLI_CONFIGURATION_EXIT_CODE)
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
            if not permanent_test_path(permanent_dir, case.id).is_file():
                unpromoted.append(case.id)

        gate_failed = gate_report is not None and not gate_report.passed

        failures = len(broken) + len(duplicates)
        if require_promoted:
            failures += len(unpromoted)
        if gate_failed:
            failures += 1

        if wants_json_output(ctx, json_flag=json_output):
            payload: dict[str, Any] = {
                "status": "fail" if failures else "pass",
                "bank": str(bank_dir),
                "cases": len(paths),
                "loaded": len(seen),
                "broken": broken,
                "duplicates": duplicates,
                "unpromoted": unpromoted,
            }
            if gate_report is not None:
                payload["regression_gate"] = gate_report.model_dump(mode="json")
            emit_cli_json(payload)
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
            if gate_report is not None:
                console.print(
                    f"release regression gate (tolerance {gate_report.tolerance:.2%}): "
                    + ("[green]passed[/green]" if gate_report.passed else "[red]failed[/red]")
                )
                for delta in gate_report.deltas:
                    marker = " [red]REGRESSED[/red]" if delta.regressed else ""
                    console.print(
                        f"  {delta.metric}: {delta.baseline:.2%} → {delta.candidate:.2%} "
                        f"(Δ {delta.delta:+.2%}){marker}"
                    )
            if not paths:
                console.print(
                    "  [yellow]bank is empty — the gate passes, but it is not yet "
                    "measuring anything[/yellow]"
                )
            elif failures == 0:
                console.print("  [green]bank is healthy[/green]")

        if failures:
            raise typer.Exit(code=CLI_CONFIGURATION_EXIT_CODE)


__all__ = ["register_gate_command"]
