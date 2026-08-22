"""CLI analyze-stage helpers for offline review."""

from __future__ import annotations

import asyncio
from functools import partial
from typing import TYPE_CHECKING, Literal

from loguru import logger

from mergecraft.analyzers.budget import default_inline_budget
from mergecraft.analyzers.pipeline import run_analyzer_pipeline
from mergecraft.config import load_repo_settings
from mergecraft.mcp.checkout import changed_paths_in_diff
from mergecraft.mcp.tool_state import AnalyzerRunState, analyzer_run_key

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.types import ShellPermission
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
    shell: ShellPermission = "disabled",
    analyzers_enabled: bool = True,
) -> AnalyzerRunState | None:
    """Run the catalog analyzer pipeline and return its state for the driver.

    ``shell`` is the operator-resolved shell permission for this run (``--shell``
    on ``mergecraft review``). It defaults to ``disabled``, which withholds every
    ``runtime: repo-native`` manifest (see
    :func:`mergecraft.analyzers.trust.evaluate_manifest_for_shell`); raising it
    lets those analyzers execute repo-provided tooling.

    The returned state carries an :class:`~mergecraft.mcp.tool_state.AnalyzerRunKey`
    describing the inputs it was computed from, so the ``run_analyzers`` MCP tool
    can reuse this run instead of executing every analyzer a second time over the
    same diff. A run that failed carries no key — reusing a failure would deny the
    reviewing agent a retry that might succeed.
    """
    if not analyzers_enabled or materialization.empty:
        return None
    diff_text = materialization.path.read_text(encoding="utf-8")
    changed_files = changed_paths_in_diff(diff_text)
    tier = _as_trust_tier(trust_tier)
    pipeline = partial(
        run_analyzer_pipeline,
        repo_root=cwd,
        changed_files=changed_files,
        tier=tier,
        diff_text=diff_text,
        offline=True,
        base_ref=materialization.base_ref,
        shell=shell,
        mode="auto",
    )
    try:
        state = await asyncio.to_thread(pipeline)
    except Exception as exc:
        logger.warning("offline analyze: pipeline failed — {}", exc)
        return AnalyzerRunState(ran=False, reason=str(exc))
    # ``inline_budget`` is left unset above, so record the budget the pipeline
    # itself resolves — the tool passes ``settings.inline_budget`` explicitly and
    # the two only agree when that value is truthy.
    settings = load_repo_settings(root=cwd, load_learnings_files=False).analyzers
    state.key = analyzer_run_key(
        repo_root=cwd,
        changed_files=changed_files,
        tier=tier,
        shell=str(shell),
        mode="auto",
        inline_budget=settings.inline_budget or default_inline_budget(),
        offline=True,
        base_ref=materialization.base_ref,
        diff_text=diff_text,
    )
    return state
