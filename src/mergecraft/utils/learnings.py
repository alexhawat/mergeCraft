"""Seed and persist local learnings files (no mergecraft.com API)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext

LEARNINGS_FILE_NAME = "mergecraft-learnings.md"
XREPO_LEARNINGS_FILE_NAME = "mergecraft-xrepo-learnings.md"
MAX_LEARNINGS_LENGTH = 100_000


def truncate_at_line_boundary(text: str, max_length: int = MAX_LEARNINGS_LENGTH) -> str:
    if len(text) <= max_length:
        return text
    truncated = text[:max_length]
    last_nl = truncated.rfind("\n")
    if last_nl > max_length // 2:
        return truncated[:last_nl]
    return truncated


def learnings_file_path(tmpdir: str) -> str:
    return str(Path(tmpdir) / LEARNINGS_FILE_NAME)


def xrepo_learnings_file_path(tmpdir: str) -> str:
    return str(Path(tmpdir) / XREPO_LEARNINGS_FILE_NAME)


async def seed_learnings_file(*, tmpdir: str, current: str | None) -> str:
    path = Path(learnings_file_path(tmpdir))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(current or "", encoding="utf-8")
    return str(path)


async def seed_xrepo_learnings_file(*, tmpdir: str, current: str | None) -> str:
    path = Path(xrepo_learnings_file_path(tmpdir))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(current or "", encoding="utf-8")
    return str(path)


async def read_learnings_file(path: str) -> str | None:
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    return truncate_at_line_boundary(raw.strip(), MAX_LEARNINGS_LENGTH)


def _local_persist_path(*, owner: str, name: str, kind: str = "learnings") -> Path:
    workspace = Path(os_environ_workspace())
    if kind == "xrepo":
        return workspace / ".mergecraft" / "xrepo-learnings.md"
    return workspace / ".mergecraft" / "learnings.md"


def os_environ_workspace() -> str:
    import os

    return os.environ.get("GITHUB_WORKSPACE") or os.getcwd()


async def persist_learnings(ctx: ToolContext) -> None:
    """Write agent-edited learnings back to ``.mergecraft/learnings.md`` (local)."""
    file_path = ctx.tool_state.learnings_file_path
    if not file_path or ctx.tool_state.learnings_persist_attempted:
        return
    ctx.tool_state.learnings_persist_attempted = True
    current = await read_learnings_file(file_path)
    if current is None:
        logger.debug("learnings tmpfile missing or unreadable at {} — skipping persist", file_path)
        return
    seed = (ctx.tool_state.learnings_seed or "").strip()
    if current == seed:
        logger.debug("learnings tmpfile unchanged from seed — skipping persist")
        return
    dest = _local_persist_path(owner=ctx.repo.owner, name=ctx.repo.name)
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            current + ("\n" if current and not current.endswith("\n") else ""), encoding="utf-8"
        )
        logger.info("» learnings updated at {}", dest)
    except OSError as exc:
        logger.warning("learnings persist failed: {}", exc)


async def persist_xrepo_learnings(ctx: ToolContext) -> None:
    file_path = ctx.tool_state.xrepo_learnings_file_path
    if not file_path or ctx.tool_state.xrepo_learnings_persist_attempted:
        return
    ctx.tool_state.xrepo_learnings_persist_attempted = True
    current = await read_learnings_file(file_path)
    if current is None:
        return
    seed = (ctx.tool_state.xrepo_learnings_seed or "").strip()
    if current == seed:
        return
    dest = _local_persist_path(owner=ctx.repo.owner, name=ctx.repo.name, kind="xrepo")
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            current + ("\n" if current and not current.endswith("\n") else ""), encoding="utf-8"
        )
        logger.info("» xrepo learnings updated at {}", dest)
    except OSError as exc:
        logger.warning("xrepo learnings persist failed: {}", exc)


__all__ = [
    "LEARNINGS_FILE_NAME",
    "MAX_LEARNINGS_LENGTH",
    "XREPO_LEARNINGS_FILE_NAME",
    "learnings_file_path",
    "persist_learnings",
    "persist_xrepo_learnings",
    "read_learnings_file",
    "seed_learnings_file",
    "seed_xrepo_learnings_file",
    "truncate_at_line_boundary",
    "xrepo_learnings_file_path",
]
