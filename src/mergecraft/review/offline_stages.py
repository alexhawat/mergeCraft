"""CLI analyze-stage helpers for offline review."""

from __future__ import annotations

import asyncio
from functools import partial
from typing import TYPE_CHECKING, Literal

from mergecraft.analyzers.pipeline import run_analyzer_pipeline

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.utils.offline_diff import DiffMaterialization

TrustTier = Literal["trusted", "untrusted"]


def changed_paths_from_unified_diff(diff_text: str) -> list[str]:
    """Return ``b/`` paths from ``diff --git`` headers."""
    paths: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("diff --git ") and len(line.split()) >= 4:
            paths.append(line.split()[3].removeprefix("b/"))
    return paths


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
) -> None:
    """Run the catalog analyzer pipeline on the materialized diff."""
    if not analyzers_enabled or materialization.empty:
        return
    diff_text = materialization.path.read_text(encoding="utf-8")
    pipeline = partial(
        run_analyzer_pipeline,
        repo_root=cwd,
        changed_files=changed_paths_from_unified_diff(diff_text),
        tier=_as_trust_tier(trust_tier),
        diff_text=diff_text,
        offline=True,
        base_ref=materialization.base_ref,
        shell="disabled",
        mode="auto",
    )
    await asyncio.to_thread(pipeline)
