"""CLI analyze-stage helpers for offline review."""

from __future__ import annotations

import asyncio
from functools import partial
from typing import TYPE_CHECKING, Literal

from loguru import logger

from mergecraft.analyzers.pipeline import run_analyzer_pipeline
from mergecraft.mcp.checkout import changed_paths_in_diff
from mergecraft.mcp.tool_state import AnalyzerRunState

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.utils.offline_diff import DiffMaterialization

TrustTier = Literal["trusted", "untrusted"]


def _as_trust_tier(raw: str) -> TrustTier:
    if raw == "trusted":
        return "trusted"
    return "untrusted"


async def run_offline_analyze(
    *,
    cwd: Path,
    materialization: DiffMaterialization,
    trust_tier: str,
    analyzers_enabled: bool = True,
) -> AnalyzerRunState | None:
    """Run the catalog analyzer pipeline and return its state for the driver."""
    if not analyzers_enabled or materialization.empty:
        return None
    diff_text = materialization.path.read_text(encoding="utf-8")
    pipeline = partial(
        run_analyzer_pipeline,
        repo_root=cwd,
        changed_files=changed_paths_in_diff(diff_text),
        tier=_as_trust_tier(trust_tier),
        diff_text=diff_text,
        offline=True,
        base_ref=materialization.base_ref,
        shell="disabled",
        mode="auto",
    )
    try:
        return await asyncio.to_thread(pipeline)
    except Exception as exc:
        logger.warning("offline analyze: pipeline failed — {}", exc)
        return AnalyzerRunState(ran=False, reason=str(exc))
