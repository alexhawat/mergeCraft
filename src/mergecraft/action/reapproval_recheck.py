"""Deterministic recheck for a re-approval under a changed review policy.

A re-approval (:mod:`mergecraft.classify.reapproval`) proves that the pull request's
own changes are the reviewed ones. When the review policy changed since that review
(a new Action pin, an edit under ``.mergecraft``, a new mergeCraft version), the prior
verdict was decided under different rules, so it does not carry over on the proof
alone. This module re-runs what the new policy can decide without a model: it checks
the new head out, runs the catalog analyzers and the repo's static checks over the
change, and reports whether they were clean.

Clean means nothing spoke against the change: no analyzer finding, no failed or
crashed analyzer, no failing static check. Anything else — a finding, a failure, a
head that could not be materialized, a tool error, a timeout — is "not clean", and the
caller runs the normal review, which handles the finding the usual way. This module
never decides a verdict.

No agent, MCP server or model is involved: the tool bodies are called in-process. The
diff the checkout writes exists for the analyzers only. No reviewer reads it, so on a
clean pass it is withdrawn as a review scope and the run publishes like any other
re-approval, with no coverage accounting of its own.

Exports:
    RecheckOutcome: Whether the deterministic checks were clean, and what ran.
    run_deterministic_recheck: Check the head out and run the checks.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from loguru import logger

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext
    from mergecraft.mcp.shared import ToolSpec

# A tool that declares no timeout of its own gets this one.
_DEFAULT_TOOL_TIMEOUT_S: Final[float] = 600.0
_FAILED_ANALYZER_STATUSES: Final[frozenset[str]] = frozenset({"failed", "tool-error"})
_RAN_ANALYZER_STATUSES: Final[frozenset[str]] = frozenset({"passed", "failed"})


@dataclass(frozen=True, slots=True)
class RecheckOutcome:
    """The result of the deterministic recheck.

    Attributes:
        clean: Every check that ran was clean and none could not run to a result.
        reason: Why the recheck is not clean; empty when it is.
        ran: One stated line per check, for the run record.
    """

    clean: bool
    reason: str = ""
    ran: tuple[str, ...] = ()


class _NotCleanError(Exception):
    """Raised inside the recheck for a not-clean result."""


async def _call(spec: ToolSpec, params: dict[str, Any]) -> dict[str, Any]:
    """Run one tool body in-process and return its JSON payload."""
    timeout_s = (spec.timeout_ms / 1000) if spec.timeout_ms else _DEFAULT_TOOL_TIMEOUT_S
    try:
        result = await asyncio.wait_for(spec.execute(params), timeout=timeout_s)
    except TimeoutError:
        msg = f"{spec.name} timed out"
        raise _NotCleanError(msg) from None
    text = "".join(str(part.get("text") or "") for part in result.content)
    if result.is_error:
        detail = text.strip().splitlines()[0] if text.strip() else "no detail"
        msg = f"{spec.name} failed ({detail})"
        raise _NotCleanError(msg)
    try:
        payload = json.loads(text)
    except ValueError:
        msg = f"{spec.name} returned an unreadable result"
        raise _NotCleanError(msg) from None
    if not isinstance(payload, dict):
        msg = f"{spec.name} returned an unexpected result"
        raise _NotCleanError(msg)
    return payload


async def _checkout(ctx: ToolContext, pull_number: int, head_sha: str) -> tuple[str, list[str]]:
    """Materialize the head; return the diff path and the changed paths."""
    from mergecraft.mcp.checkout import checkout_pr_tool
    from mergecraft.mcp.tool_state import primary_repo_state
    from mergecraft.modes._api_only_scope import API_ONLY_SCOPE
    from mergecraft.review_policy.ignore_paths import filter_diff

    result = await _call(checkout_pr_tool(ctx), {"pull_number": pull_number})
    if result.get("scope") == API_ONLY_SCOPE or result.get("degraded"):
        raise _NotCleanError("the head could not be checked out completely")
    if result.get("diffTruncated") or result.get("unreviewablePaths"):
        raise _NotCleanError("the change could not be read completely")
    checked_out = str(primary_repo_state(ctx.tool_state).checkout_sha or "").lower()
    if checked_out != head_sha.lower():
        raise _NotCleanError("the checked-out revision is not the head under review")
    diff_path = result.get("diffPath")
    if not isinstance(diff_path, str) or not diff_path:
        raise _NotCleanError("the checkout produced no diff")
    try:
        diff_text = Path(diff_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        raise _NotCleanError("the checkout's diff could not be read") from None
    return diff_path, list(filter_diff(diff_text, None).changed_paths)


async def _analyzers(ctx: ToolContext, diff_path: str, changed: list[str]) -> str:
    from mergecraft.analyzers.trust import analyzers_enabled
    from mergecraft.mcp.analyzers import run_analyzers_tool

    if not analyzers_enabled(ctx):
        return "analyzers: not enabled for this run"
    payload = await _call(
        run_analyzers_tool(ctx), {"changed_files": changed, "diff_path": diff_path}
    )
    rows = [row for row in payload.get("analyzers") or [] if isinstance(row, dict)]
    failed = sorted(
        str(row.get("id")) for row in rows if row.get("status") in _FAILED_ANALYZER_STATUSES
    )
    if failed:
        msg = "analyzers reported a failure (" + ", ".join(failed) + ")"
        raise _NotCleanError(msg)
    findings = payload.get("findingCount")
    if not isinstance(findings, int) or isinstance(findings, bool) or findings != 0:
        msg = f"analyzers reported findings ({findings})"
        raise _NotCleanError(msg)
    ran = sum(1 for row in rows if row.get("status") in _RAN_ANALYZER_STATUSES)
    return f"analyzers: {ran} ran, {len(rows) - ran} unavailable, 0 findings"


async def _static_checks(ctx: ToolContext, changed: list[str]) -> str:
    from mergecraft.mcp.static_checks import run_static_checks_tool

    if not ctx.static_checks_enabled:
        return "static checks: not enabled for this run"
    payload = await _call(run_static_checks_tool(ctx), {"changed_files": changed})
    checks = [row for row in payload.get("checks") or [] if isinstance(row, dict)]
    if payload.get("ran") is True:
        if payload.get("allPassed") is not True:
            raise _NotCleanError("a static check failed")
        return f"static checks: {len(checks)} declared, all that ran passed"
    if payload.get("ran") is not False:
        raise _NotCleanError("run_static_checks returned an unexpected result")
    return f"static checks: {len(checks)} declared, none could run here"


def _withdraw_review_scope(ctx: ToolContext) -> None:
    """Drop the checkout's diff as a review scope: no reviewer was handed it."""
    from mergecraft.mcp.tool_state import primary_repo_state

    repo = primary_repo_state(ctx.tool_state)
    repo.diff_path = None
    repo.incremental_diff_path = None
    record = ctx.tool_state.coverage
    record.authoritative_diff = None
    record.unreviewable_paths = []
    record.diff_truncated = False


async def run_deterministic_recheck(
    ctx: ToolContext, *, pull_number: int, head_sha: str
) -> RecheckOutcome:
    """Check ``head_sha`` out and run the analyzers and static checks, with no model.

    Total: any failure is a not-clean outcome with its reason, never an exception, so
    the caller falls through to the normal review.
    """
    ran: list[str] = []
    try:
        diff_path, changed = await _checkout(ctx, pull_number, head_sha)
        ran.append(await _analyzers(ctx, diff_path, changed))
        ran.append(await _static_checks(ctx, changed))
    except _NotCleanError as problem:
        return RecheckOutcome(clean=False, reason=str(problem), ran=tuple(ran))
    except Exception as err:  # the recheck is an optimisation; failing it reviews normally
        logger.warning("re-approval recheck raised {}: {}", type(err).__name__, err)
        return RecheckOutcome(
            clean=False,
            reason=f"the deterministic checks could not run ({type(err).__name__})",
            ran=tuple(ran),
        )
    _withdraw_review_scope(ctx)
    return RecheckOutcome(clean=True, ran=tuple(ran))


__all__ = ["RecheckOutcome", "run_deterministic_recheck"]
