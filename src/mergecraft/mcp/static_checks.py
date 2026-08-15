"""run_static_checks tool — run the repo's own mechanical gates over a diff."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.ci.evidence import (
    declared_gate_findings,
    record_ci_findings,
    record_gate_substitutions,
    substitute_declared_gates,
)
from mergecraft.mcp.shared import execute, tool
from mergecraft.mcp.tool_state import primary_repo_state
from mergecraft.review_checks import declared_cannot_run_outcomes, plan_checks, run_checks

if TYPE_CHECKING:
    from mergecraft.ci.evidence import GateSubstitution
    from mergecraft.mcp.context import ToolContext
    from mergecraft.review_checks import StaticCheckOutcome


def _serialize(outcome: StaticCheckOutcome) -> dict[str, Any]:
    return {
        "name": outcome.name,
        "command": outcome.command,
        "status": outcome.status,
        "exitCode": outcome.exit_code,
        "output": outcome.output,
    }


def _persist_static_checks(ctx: ToolContext, outcomes: list[StaticCheckOutcome]) -> None:
    """Update ``ToolState.static_checks`` with this run's rows.

    Same-name outcomes replace prior rows. Prior ``failed`` rows whose gate was
    not in this plan stay — a suffix-filtered or partial rerun must not clear an
    earlier failure the session already recorded.
    """
    incoming = {
        outcome.name: {"name": outcome.name, "status": outcome.status} for outcome in outcomes
    }
    retained_failed = [
        row
        for row in ctx.tool_state.static_checks
        if isinstance(row, dict)
        and row.get("status") == "failed"
        and row.get("name") not in incoming
    ]
    ctx.tool_state.static_checks = [*retained_failed, *incoming.values()]


def _report(
    ctx: ToolContext,
    outcomes: list[StaticCheckOutcome],
    substitutions: list[GateSubstitution],
    *,
    reason: str,
) -> dict[str, Any]:
    """Render the tool payload from whatever verdicts this run ended up with.

    ``ran`` asks whether any gate produced a verdict about the diff — a gate a
    declared CI check run proved counts, which is exactly how #36 removes the
    duplicate ``unavailable`` row without inventing a second reporting shape.
    """
    _persist_static_checks(ctx, outcomes)
    executed = [outcome for outcome in outcomes if outcome.ran]
    payload: dict[str, Any] = {"checks": [_serialize(o) for o in outcomes]}
    if substitutions:
        payload["ciEvidence"] = [substitution.as_row() for substitution in substitutions]
    if not executed:
        payload["ran"] = False
        payload["reason"] = reason
        return payload
    payload["ran"] = True
    payload["allPassed"] = all(outcome.passed for outcome in executed)
    return payload


async def _apply_ci_evidence(
    ctx: ToolContext,
    outcomes: list[StaticCheckOutcome],
) -> tuple[list[StaticCheckOutcome], list[GateSubstitution]]:
    """Let the consumer's finished CI speak for gates this environment cannot run.

    Best-effort and declared-only (#36 / D10):

    * no declared mapping ⇒ GitHub is never even asked;
    * no head SHA ⇒ nothing to read CI for;
    * an API error ⇒ the gate report is returned exactly as it was.

    Failing here must never degrade the honest ``unavailable`` report that
    already works, so every failure path returns the untouched outcomes.
    """
    mapping = ctx.ci_gate_checks
    if not mapping or not outcomes:
        return outcomes, []
    ref = primary_repo_state(ctx.tool_state).checkout_sha
    if not ref:
        logger.debug("ci evidence: no checkout SHA on this run — skipping gate substitution")
        return outcomes, []
    try:
        payload = await ctx.github.list_check_runs_for_ref(ctx.repo.owner, ctx.repo.name, ref)
    except Exception as err:
        logger.warning("ci evidence: could not read check runs for {} — {}", ref, err)
        return outcomes, []

    check_runs = [run for run in (payload.get("check_runs") or []) if isinstance(run, dict)]
    if not check_runs:
        return outcomes, []

    findings = declared_gate_findings(outcomes, mapping=mapping, check_runs=check_runs)
    if findings:
        record_ci_findings(ctx.tool_state, findings)
    updated, substitutions = substitute_declared_gates(
        outcomes, mapping=mapping, check_runs=check_runs
    )
    if substitutions:
        record_gate_substitutions(ctx.tool_state, substitutions)
    return updated, substitutions


def run_static_checks_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        # Recorded before the early returns: a repo that declares no gate still
        # completed the deterministic pass, and the D14 ordering gate asks
        # whether that pass happened, not whether it found anything.
        ctx.tool_state.static_checks_ran = True
        state = primary_repo_state(ctx.tool_state)
        root = Path(state.dir)
        changed = [str(f) for f in (params.get("changed_files") or [])]

        checks = plan_checks(
            root=root,
            configured=ctx.static_checks,
            changed_files=changed,
        )
        if not checks:
            return {
                "ran": False,
                "reason": (
                    "this repo declares no mechanical gate — no `staticChecks` in "
                    ".mergecraft/config.yaml and no lint/typecheck target in a Makefile. "
                    "Report the Mechanical gates pre-merge check as skipped; do not "
                    "substitute your own linter or interpreter."
                ),
                "checks": [],
            }

        if ctx.payload.shell == "disabled" and ctx.static_checks and ctx.trust_tier != "trusted":
            reason = (
                "staticChecks are configured but cannot run in this environment — "
                "shell is disabled on pull-request events"
            )
            declared = declared_cannot_run_outcomes(checks, reason=reason)
            outcomes, substitutions = await _apply_ci_evidence(ctx, declared)
            return _report(ctx, outcomes, substitutions, reason=reason)

        outcomes = run_checks(checks, root=root)
        outcomes, substitutions = await _apply_ci_evidence(ctx, outcomes)
        executed = [o for o in outcomes if o.ran]
        logger.info(
            "static checks: {} executed, {} failing, {} unavailable",
            len(executed),
            sum(1 for o in executed if not o.passed),
            len(outcomes) - len(executed),
        )
        return _report(
            ctx,
            outcomes,
            substitutions,
            reason=(
                "every gate this repo declares is unavailable here — the "
                "executables are not installed in this environment. Report the "
                "Mechanical gates pre-merge check as skipped. This is not a "
                "finding about the diff, and it is not a reason to run a linter "
                "or interpreter of your own."
            ),
        )

    return tool(
        name="run_static_checks",
        timeout_ms=600_000,
        description=(
            "Run the reviewed repo's own mechanical gates (declared `staticChecks`, "
            "else discovered Makefile lint/typecheck targets) and return each gate's "
            "status and output. Use during review to turn a style observation into a "
            "named failing gate. Returns ran:false when the repo declares no gate, or "
            "when none of its gates are installed in this environment; either way "
            "report the check as skipped rather than running a linter or interpreter "
            "of your own, whose version may not match the repo's. Per-gate status is "
            "passed, failed, timed_out, unavailable, declared-but-cannot-run, or "
            "satisfied-by-ci — only `failed` says anything about the diff. "
            "`satisfied-by-ci` means the repo declared a CI check run as proof of that "
            "gate and it passed; cite the check run from `ciEvidence` and report the "
            "gate as green, not skipped."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "changed_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Repo-relative paths changed by the PR. Used to skip gates "
                        "whose declared suffixes match nothing in this diff."
                    ),
                }
            },
            "additionalProperties": False,
        },
        execute=execute(_run, "run_static_checks"),
    )


__all__ = ["run_static_checks_tool"]
