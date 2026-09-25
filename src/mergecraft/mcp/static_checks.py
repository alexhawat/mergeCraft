"""run_static_checks tool — run the repo's own mechanical gates over a diff."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.analyzers.sandbox_failures import classify_unambiguous_sandbox_failure_detail
from mergecraft.ci.evidence import (
    declared_gate_findings,
    record_ci_findings,
    record_gate_substitutions,
    substitute_declared_gates,
)
from mergecraft.mcp.shared import ToolClass, execute, tool
from mergecraft.mcp.tool_state import primary_repo_state
from mergecraft.review_checks import declared_cannot_run_outcomes, plan_checks, run_checks

if TYPE_CHECKING:
    from mergecraft.ci.evidence import GateSubstitution
    from mergecraft.mcp.context import ToolContext
    from mergecraft.review_checks import StaticCheck, StaticCheckOutcome


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
        listed = await ctx.scm.list_check_runs_for_ref(ctx.repo.owner, ctx.repo.name, ref)
    except Exception as err:
        logger.warning("ci evidence: could not read check runs for {} — {}", ref, err)
        return outcomes, []

    if listed.incomplete:
        logger.warning(
            "ci evidence: check-run listing for {} incomplete — skipping gate substitution",
            ref,
        )
        return outcomes, []

    check_runs = listed.items
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


_UNAVAILABLE_REASON = (
    "every gate this repo declares is unavailable here — the "
    "executables are not installed in this environment. Report the "
    "Mechanical gates pre-merge check as skipped. This is not a "
    "finding about the diff, and it is not a reason to run a linter "
    "or interpreter of your own."
)


def _withheld_reason(ctx: ToolContext) -> str:
    """The declared-but-cannot-run wording for a withheld gate, keyed on provenance."""
    if ctx.static_checks:
        return (
            "staticChecks are configured but cannot run in this environment — "
            "sandbox isolation is unavailable for untrusted static checks"
        )
    return (
        "this repo declares no `staticChecks`; its mechanical gates were "
        "discovered from the Makefile, and they cannot run in this "
        "environment — sandbox isolation is unavailable for untrusted static "
        "checks, where the Makefile is itself part of the diff under review"
    )


def _sandbox_scratch_dir(ctx: ToolContext) -> Path:
    return Path(ctx.tmpdir) / "static-checks-scratch"


def _sandbox_scratch_env(scratch_dir: Path) -> dict[str, str]:
    """Writable scratch ``HOME``/``XDG_CACHE_HOME``/``TMPDIR`` for a sandboxed gate (SX-D7).

    A gate dropped to the agent user cannot write the runner-owned ``HOME`` it
    would otherwise inherit; pointing these at scratch keeps a cache write from
    reading as a finding (P-8).
    """
    home = scratch_dir / "home"
    cache = scratch_dir / "cache"
    tmp = scratch_dir / "tmp"
    for path in (home, cache, tmp):
        path.mkdir(parents=True, exist_ok=True)
    return {"HOME": str(home), "XDG_CACHE_HOME": str(cache), "TMPDIR": str(tmp)}


def _classify_sandbox_failures(outcomes: list[StaticCheckOutcome]) -> list[StaticCheckOutcome]:
    """Turn sandbox-caused failures into ``declared-but-cannot-run`` (SX-D7 / P-8).

    A non-zero exit whose output is *unambiguously* sandbox-caused produced no
    verdict about the diff, so it is not a finding. The matched line is kept
    beside the reason; a real diagnostic printed next to incidental sandbox
    noise keeps the gate's real result (P-8 inverse).
    """
    classified: list[StaticCheckOutcome] = []
    for outcome in outcomes:
        if outcome.status == "failed":
            detail = classify_unambiguous_sandbox_failure_detail(outcome.output)
            if detail is not None:
                logger.info(
                    "static check {} failed inside the sandbox: {}",
                    outcome.name,
                    detail.reason,
                )
                output = f"{detail.reason}: {detail.line}" if detail.line else detail.reason
                classified.append(replace(outcome, status="declared-but-cannot-run", output=output))
                continue
        classified.append(outcome)
    return classified


async def _run_untrusted_checks(
    ctx: ToolContext, *, checks: list[StaticCheck], root: Path
) -> tuple[list[StaticCheckOutcome], list[GateSubstitution], str]:
    """Run untrusted gates inside the untrusted sandbox, or withhold them (SX-D7).

    Returns ``(outcomes, substitutions, reason)``. When isolation is available
    the checkout is presented as a disposable copy-on-write view and
    sandbox-caused failures are classified. When it is not, a shell-disabled run
    withholds with a declared-but-cannot-run row; an available shell keeps the
    existing bare execution, since the shell permission is the execution opt-in.
    """
    from mergecraft.analyzers.sandbox import plan_sandbox

    scratch_dir = _sandbox_scratch_dir(ctx)
    plan = plan_sandbox(
        repo_root=root,
        scratch_dir=scratch_dir,
        tier="untrusted",
        copy_on_write_repo=True,
    )
    if plan.can_run and plan.context is not None:
        outcomes = run_checks(
            checks,
            root=root,
            tier="untrusted",
            sandbox_context=plan.context,
            env_overrides=_sandbox_scratch_env(scratch_dir),
        )
        outcomes = _classify_sandbox_failures(outcomes)
        outcomes, substitutions = await _apply_ci_evidence(ctx, outcomes)
        executed = [o for o in outcomes if o.ran]
        logger.info(
            "static checks: {} executed in the untrusted sandbox, {} failing, {} unavailable",
            len(executed),
            sum(1 for o in executed if not o.passed),
            len(outcomes) - len(executed),
        )
        return outcomes, substitutions, _UNAVAILABLE_REASON

    if ctx.payload.shell == "disabled":
        reason = _withheld_reason(ctx)
        declared = declared_cannot_run_outcomes(checks, reason=reason)
        outcomes, substitutions = await _apply_ci_evidence(ctx, declared)
        return outcomes, substitutions, reason

    outcomes = run_checks(checks, root=root, tier="untrusted")
    outcomes, substitutions = await _apply_ci_evidence(ctx, outcomes)
    executed = [o for o in outcomes if o.ran]
    logger.info(
        "static checks: {} executed, {} failing, {} unavailable",
        len(executed),
        sum(1 for o in executed if not o.passed),
        len(outcomes) - len(executed),
    )
    return outcomes, substitutions, _UNAVAILABLE_REASON


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

        # The withhold decision is about execution, not provenance: a gate
        # discovered from the repo's Makefile shell-executes exactly like a
        # declared one, and on an untrusted event that Makefile is part of the
        # diff under review. Both route through the untrusted sandbox; only the
        # wording differs when isolation is unavailable.
        tier = ctx.trust_tier
        if tier == "untrusted":
            outcomes, substitutions, reason = await _run_untrusted_checks(
                ctx, checks=checks, root=root
            )
            return _report(ctx, outcomes, substitutions, reason=reason)

        outcomes = run_checks(checks, root=root, tier=tier)
        outcomes, substitutions = await _apply_ci_evidence(ctx, outcomes)
        executed = [o for o in outcomes if o.ran]
        logger.info(
            "static checks: {} executed, {} failing, {} unavailable",
            len(executed),
            sum(1 for o in executed if not o.passed),
            len(outcomes) - len(executed),
        )
        return _report(ctx, outcomes, substitutions, reason=_UNAVAILABLE_REASON)

    return tool(
        name="run_static_checks",
        tool_class=ToolClass.ANALYSIS,
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
