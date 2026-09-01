"""Action-side CI SARIF ingest after wait-for-ci completes (D9 / #600)."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from loguru import logger

from mergecraft.ci.intelligence import ingest_ci_sarif_for_head_sha, warn_ci_evidence

if TYPE_CHECKING:
    from mergecraft.main import RunContext
    from mergecraft.mcp.context import ToolContext

_SKIP_INGEST_WAIT_STATES = frozenset({"timeout", "absent", "skipped"})


def ci_wait_inputs_from_env() -> tuple[str, int] | None:
    """Read wait-for-ci outputs forwarded by the consumer workflow into the Action env."""
    state = (os.environ.get("MERGECRAFT_CI_WAIT_STATE") or os.environ.get("CI_STATE") or "").strip()
    if not state:
        return None
    raw_count = (
        os.environ.get("MERGECRAFT_CI_FAILED_COUNT") or os.environ.get("CI_FAILED_COUNT") or "0"
    ).strip()
    try:
        failed_count = int(raw_count)
    except ValueError:
        warn_ci_evidence(
            f"ci evidence: failed to parse CI_FAILED_COUNT env value {raw_count!r} — using 0"
        )
        failed_count = 0
    return state, failed_count


async def ingest_ci_sarif_after_ci_wait(
    ctx: ToolContext,
    *,
    ci_wait_state: str,
    head_sha: str,
    ci_failed_count: int = 0,
) -> None:
    """Ingest declared CI SARIF artifacts after wait-for-ci reaches ``complete``.

    ``complete`` covers green and red CI — ingest runs whenever the wait job
    finished polling, not only when Verify jobs failed. Wait states ``timeout``,
    ``absent``, and ``skipped`` skip ingest. ``workflow_dispatch`` does not
    pre-ingest SARIF because the wait job is PR-only.
    """
    if ci_wait_state != "complete":
        if ci_wait_state in _SKIP_INGEST_WAIT_STATES:
            logger.debug(
                "ci evidence: SARIF ingest skipped — wait state {} does not fetch artifacts",
                ci_wait_state,
            )
        return
    if ci_failed_count:
        logger.info(
            "ci evidence: ingesting declared SARIF after complete wait with {} failed job(s)",
            ci_failed_count,
        )
    await ingest_ci_sarif_for_head_sha(ctx, head_sha)


async def ingest_ci_sarif_from_action_env(ctx: RunContext) -> None:
    """Action-side SARIF ingest lane — not agent-invoked (D9)."""
    assert ctx.tool_context is not None
    wait_inputs = ci_wait_inputs_from_env()
    if wait_inputs is None:
        return
    ci_wait_state, ci_failed_count = wait_inputs
    from mergecraft.config.trust_policy import bound_head_sha

    gh_event = ctx.gh_event or {}
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    head_sha = bound_head_sha(gh_event, event_name=event_name)
    if not head_sha:
        return
    await ingest_ci_sarif_after_ci_wait(
        ctx.tool_context,
        ci_wait_state=ci_wait_state,
        ci_failed_count=ci_failed_count,
        head_sha=head_sha,
    )


__all__ = [
    "ci_wait_inputs_from_env",
    "ingest_ci_sarif_after_ci_wait",
    "ingest_ci_sarif_from_action_env",
]
