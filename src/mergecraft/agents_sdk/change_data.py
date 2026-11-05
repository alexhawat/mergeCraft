"""Workspace change materialization for Agents SDK review tools."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mergecraft.review.offline_result import OfflineReviewResult

from mergecraft.mcp.checkout import changed_paths_in_diff
from mergecraft.utils.source_resolve import SourceResolverSpec, resolve_workspace


async def _read_text(path: Path) -> str:
    return await asyncio.to_thread(path.read_text, encoding="utf-8")


async def materialize_workspace_change(
    repo_root: Path,
    *,
    allowed_paths: frozenset[str] | None = None,
    diff_file: Path | None = None,
    base: str | None = None,
    head: str | None = None,
) -> dict[str, Any]:
    """Return diff text, changed paths, and file contents for review grounding."""
    root = await asyncio.to_thread(repo_root.resolve)
    spec = SourceResolverSpec(cwd=root, invocation_root=root, base=base, head=head)
    diff_text = ""
    changed_paths: list[str] = []

    if diff_file is not None:
        diff_text = await _read_text(diff_file)
        changed_paths = sorted(changed_paths_in_diff(diff_text))
    elif await asyncio.to_thread((root / ".git").is_dir):
        try:
            workspace = resolve_workspace(spec)
        except (OSError, RuntimeError, ValueError):
            workspace = None
        if workspace is not None:
            from mergecraft.offline_review import run_offline_diff_review
            from mergecraft.review.engine import ReviewEngine
            from mergecraft.review.snapshot import canonical_review_snapshot

            snapshot = canonical_review_snapshot(entry="cli", source=str(root))
            engine: ReviewEngine[OfflineReviewResult] = ReviewEngine(snapshot=snapshot)
            result = await run_offline_diff_review(
                cwd=root,
                base=base,
                dry_run=True,
                invocation_root=root,
                source_spec=spec,
                engine=engine,
            )
            if result.success and result.diff_path:
                diff_path = Path(result.diff_path)
                if await asyncio.to_thread(diff_path.is_file):
                    diff_text = await _read_text(diff_path)
                    changed_paths = sorted(changed_paths_in_diff(diff_text))

    if not changed_paths and allowed_paths:
        changed_paths = sorted(allowed_paths)

    scope = allowed_paths if allowed_paths else frozenset(changed_paths)
    files: dict[str, str] = {}
    for rel in changed_paths:
        if scope and rel not in scope and not any(
            rel == root_path or rel.startswith(f"{root_path}/") for root_path in scope
        ):
            continue
        confined = root / rel
        if await asyncio.to_thread(confined.is_file):
            files[rel] = await _read_text(confined)

    if not files and allowed_paths:
        for rel in sorted(allowed_paths):
            confined = root / rel
            if await asyncio.to_thread(confined.is_file):
                files[rel] = await _read_text(confined)

    return {
        "diff": diff_text,
        "changed_paths": changed_paths,
        "files": files,
    }


__all__ = ["materialize_workspace_change"]
