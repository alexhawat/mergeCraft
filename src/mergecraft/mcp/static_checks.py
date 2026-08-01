"""run_static_checks tool — run the repo's own mechanical gates over a diff."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.mcp.shared import execute, tool
from mergecraft.mcp.tool_state import primary_repo_state
from mergecraft.review_checks import declared_cannot_run_outcomes, plan_checks, run_checks

if TYPE_CHECKING:
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


def run_static_checks_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
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
            outcomes = declared_cannot_run_outcomes(checks, reason=reason)
            return {
                "ran": False,
                "reason": reason,
                "checks": [_serialize(o) for o in outcomes],
            }

        outcomes = run_checks(checks, root=root)
        executed = [o for o in outcomes if o.ran]
        logger.info(
            "static checks: {} executed, {} failing, {} unavailable",
            len(executed),
            sum(1 for o in executed if not o.passed),
            len(outcomes) - len(executed),
        )
        if not executed:
            return {
                "ran": False,
                "reason": (
                    "every gate this repo declares is unavailable here — the "
                    "executables are not installed in this environment. Report the "
                    "Mechanical gates pre-merge check as skipped. This is not a "
                    "finding about the diff, and it is not a reason to run a linter "
                    "or interpreter of your own."
                ),
                "checks": [_serialize(o) for o in outcomes],
            }
        return {
            "ran": True,
            "allPassed": all(o.passed for o in executed),
            "checks": [_serialize(o) for o in outcomes],
        }

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
            "passed, failed, timed_out, unavailable, or declared-but-cannot-run — "
            "only `failed` says anything about the diff."
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
