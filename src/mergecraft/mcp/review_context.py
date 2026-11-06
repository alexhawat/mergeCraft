"""Checkout-time review context hydration — ledger, bounds, promotion (RC4, RC9, RC12)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from mergecraft.types import INCREMENTAL_REVIEW_MODE

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mergecraft.mcp.context import ToolContext


async def hydrate_review_context(
    ctx: ToolContext,
    *,
    round_index: int,
    incremental_changed_paths: Sequence[str] | None = None,
) -> None:
    """Hydrate ledger state, round bounds, and incremental deferred promotion.

    Complement lens routing (RC9) is prompt-only: the incremental checklist
    reads prior review metadata and tells the orchestrator which lenses to
    dispatch; this hook does not pre-dispatch lenses at checkout.
    """
    from mergecraft.config.settings_snapshot import repo_settings_from_context
    from mergecraft.findings.ledger import (
        ensure_finding_ledger,
        hydrate_finding_ledger_from_progress_comment,
    )
    from mergecraft.modes._incremental_promotion import (
        deferred_rows_from_ledger,
        promote_deferred_for_incremental_paths,
    )
    from mergecraft.utils.run_bounds import resolve_run_bounds

    if ctx.budget_tracker is not None:
        # Checkout rebaselines the config integrity hash while retaining the
        # operator's settings. Head YAML must not replace those run limits.
        ctx.budget_tracker.bounds = resolve_run_bounds(
            settings=repo_settings_from_context(ctx),
            round_index=round_index,
        )

    await hydrate_finding_ledger_from_progress_comment(ctx)

    if ctx.tool_state.selected_mode == INCREMENTAL_REVIEW_MODE and incremental_changed_paths:
        from datetime import UTC, datetime

        ledger = ensure_finding_ledger(ctx.tool_state)
        deferred_rows = deferred_rows_from_ledger(ledger)
        stamp = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        promoted = promote_deferred_for_incremental_paths(
            ledger,
            deferred_findings=deferred_rows,
            incremental_changed_paths=incremental_changed_paths,
            round_index=round_index,
            recorded_at=stamp,
        )
        if promoted:
            logger.info(
                "promoted {} deferred finding(s) for incremental paths",
                len(promoted),
            )


__all__ = ["hydrate_review_context"]
