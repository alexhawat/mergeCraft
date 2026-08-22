"""Checkout-time review context hydration — ledger, bounds, promotion (RC4, RC9, RC12)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.types import INCREMENTAL_REVIEW_MODE

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mergecraft.mcp.context import ToolContext


async def hydrate_review_context(
    ctx: ToolContext,
    *,
    prior_reviews: list[dict[str, Any]],
    round_index: int,
    incremental_changed_paths: Sequence[str] | None = None,
) -> None:
    """Hydrate ledger state, round bounds, and incremental deferred promotion."""
    from mergecraft.config.settings import load_repo_settings
    from mergecraft.findings.ledger import (
        ensure_finding_ledger,
        hydrate_finding_ledger_from_progress_comment,
    )
    from mergecraft.mcp.convergence_runtime import route_lenses_for_review
    from mergecraft.mcp.tool_state import primary_repo_state, record_lens_execution
    from mergecraft.modes._incremental_promotion import (
        deferred_rows_from_ledger,
        promote_deferred_for_incremental_paths,
    )
    from mergecraft.modes._pr_summary_format import parse_dispatched_lenses_from_review_body
    from mergecraft.review.lens_routing import load_routing_registry
    from mergecraft.utils.run_bounds import resolve_run_bounds

    repo_root = Path(primary_repo_state(ctx.tool_state).dir or Path.cwd())
    repo_settings = load_repo_settings(root=repo_root, load_learnings_files=False)

    if ctx.budget_tracker is not None:
        ctx.budget_tracker.bounds = resolve_run_bounds(
            settings=repo_settings,
            round_index=round_index,
        )

    await hydrate_finding_ledger_from_progress_comment(ctx)

    if ctx.tool_state.selected_mode == INCREMENTAL_REVIEW_MODE:
        prior_body = ""
        for review in reversed(prior_reviews or []):
            body = str(review.get("body") or "")
            if body.strip():
                prior_body = body
                break
        prior_dispatched = parse_dispatched_lenses_from_review_body(prior_body)
        primary = primary_repo_state(ctx.tool_state)
        diff_path = primary.incremental_diff_path or primary.diff_path
        if diff_path and Path(diff_path).is_file():
            from mergecraft.classify.change_classifier import classify_change

            diff_text = Path(diff_path).read_text(encoding="utf-8")
            classification = classify_change(
                {
                    "changed_paths": list(incremental_changed_paths or []),
                    "diff_stats": {"diff": diff_text},
                }
            )
            registry = load_routing_registry(settings=repo_settings, repo_root=repo_root)
            decision = route_lenses_for_review(
                classification,
                registry=registry,
                prior_dispatched_lens_ids=prior_dispatched,
                incremental=True,
            )
            record_lens_execution(
                ctx.tool_state,
                routing_decision=decision,
                dispatched_lens_ids=(),
            )

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
