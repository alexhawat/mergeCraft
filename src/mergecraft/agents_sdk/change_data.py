"""Workspace change materialization for Agents SDK review tools."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mergecraft.review.offline_result import OfflineReviewResult

from mergecraft.mcp.checkout import changed_paths_in_diff
from mergecraft.utils.source_resolve import (
    SourceResolverSpec,
    confine_path,
    filter_confined_paths,
    resolve_workspace,
)


def _validate_change_inputs(
    repo_root: Path,
    *,
    diff: str | None,
    base: str | None,
    head: str | None,
) -> tuple[Path | None, dict[str, Any] | None]:
    """Validate diff path and git refs the same way as public MCP ``review_change``."""
    from mergecraft.mcp.public import _validate_optional_git_ref

    for field, value in (("base", base), ("head", head)):
        ref_error = _validate_optional_git_ref(value, field=field, repo_root=repo_root)
        if ref_error is not None:
            return None, {"error": ref_error}
    diff_path: Path | None = None
    if diff is not None:
        confined = confine_path(repo_root, diff)
        if confined is None:
            return None, {"error": "diff path must be inside the workspace"}
        diff_path = confined
    return diff_path, None


def _confine_diff_paths(repo_root: Path, diff_text: str) -> tuple[str, list[str]]:
    """Drop diff hunks whose paths escape the workspace (D7 / offline review parity)."""
    paths = changed_paths_in_diff(diff_text)
    kept = filter_confined_paths(repo_root, paths)
    if kept == paths:
        return diff_text, sorted(kept)
    from mergecraft.offline_review import _filter_diff_to_paths

    filtered = _filter_diff_to_paths(diff_text, kept)
    return filtered, sorted(kept)


async def _read_text(path: Path) -> str:
    return await asyncio.to_thread(path.read_text, encoding="utf-8")


async def materialize_workspace_change(
    repo_root: Path,
    *,
    allowed_paths: frozenset[str] | None = None,
    diff: str | None = None,
    base: str | None = None,
    head: str | None = None,
) -> dict[str, Any]:
    """Return diff text, changed paths, and file contents for review grounding."""
    root = await asyncio.to_thread(repo_root.resolve)
    diff_path, error = _validate_change_inputs(root, diff=diff, base=base, head=head)
    if error is not None:
        return error

    spec = SourceResolverSpec(cwd=root, invocation_root=root, base=base, head=head)
    diff_text = ""
    changed_paths: list[str] = []

    if diff_path is not None:
        diff_text = await _read_text(diff_path)
        diff_text, changed_paths = _confine_diff_paths(root, diff_text)
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
                diff_file=diff_path,
                dry_run=True,
                invocation_root=root,
                source_spec=spec,
                engine=engine,
            )
            if result.success and result.diff_path:
                materialized = Path(result.diff_path)
                if await asyncio.to_thread(materialized.is_file):
                    diff_text = await _read_text(materialized)
                    diff_text, changed_paths = _confine_diff_paths(root, diff_text)

    if not changed_paths and allowed_paths:
        changed_paths = sorted(allowed_paths)

    scope = allowed_paths if allowed_paths else frozenset(changed_paths)
    files: dict[str, str] = {}
    for rel in changed_paths:
        if (
            scope
            and rel not in scope
            and not any(rel == root_path or rel.startswith(f"{root_path}/") for root_path in scope)
        ):
            continue
        confined = confine_path(root, rel)
        if confined is None or not await asyncio.to_thread(confined.is_file):
            continue
        files[rel] = await _read_text(confined)

    if not files and allowed_paths:
        for rel in sorted(allowed_paths):
            confined = confine_path(root, rel)
            if confined is None or not await asyncio.to_thread(confined.is_file):
                continue
            files[rel] = await _read_text(confined)

    return {
        "diff": diff_text,
        "changed_paths": changed_paths,
        "files": files,
    }


__all__ = ["materialize_workspace_change"]
