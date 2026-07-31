"""Seed and persist local learnings files (no mergecraft.com API)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext
    from mergecraft.mcp.tool_state import ToolState

LEARNINGS_FILE_NAME = "mergecraft-learnings.md"
XREPO_LEARNINGS_FILE_NAME = "mergecraft-xrepo-learnings.md"
MAX_LEARNINGS_LENGTH = 100_000

_EPHEMERAL_LEARNINGS_WARNING = (
    "learnings written to checkout workspace at {} — this will not survive an "
    "ephemeral CI runner unless the repo commits `.mergecraft/learnings.md`"
)
_EPHEMERAL_XREPO_LEARNINGS_WARNING = (
    "xrepo learnings written to checkout workspace at {} — this will not survive an "
    "ephemeral CI runner unless the repo commits `.mergecraft/xrepo-learnings.md`"
)


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


def _has_durable_persist_path() -> bool:
    """Contents-API auto-commit path (D7 — deferred)."""
    return False


def persist_is_ephemeral() -> bool:
    """True when only workspace-local persist is available (e.g. Action checkout)."""
    return not _has_durable_persist_path()


def _local_persist_path(*, kind: str = "learnings") -> Path:
    workspace = Path(os_environ_workspace())
    if kind == "xrepo":
        return workspace / ".mergecraft" / "xrepo-learnings.md"
    return workspace / ".mergecraft" / "learnings.md"


def os_environ_workspace() -> str:
    import os

    return os.environ.get("GITHUB_WORKSPACE") or os.getcwd()


def build_learnings_review_delta(*, before: str, after: str) -> str:
    """Before→after block for PR/review output when persistence is ephemeral."""
    return (
        "### Learnings delta\n\n"
        "Copy the **After** block into `.mergecraft/learnings.md` "
        "(this run could not persist durably):\n\n"
        f"**Before:**\n\n{before.rstrip()}\n\n"
        f"**After:**\n\n{after.rstrip()}"
    )


def merge_learnings_delta_into_review_body(tool_state: ToolState, body: str) -> str:
    """Append ephemeral learnings delta to review or PR-comment bodies."""
    delta = tool_state.learnings_review_delta
    if not delta or not delta.strip():
        return body
    cleaned = body.rstrip()
    if "### Learnings delta" in cleaned:
        return cleaned
    return f"{cleaned}\n\n{delta.rstrip()}"


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
    dest = _local_persist_path()
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            current + ("\n" if current and not current.endswith("\n") else ""), encoding="utf-8"
        )
        if persist_is_ephemeral():
            logger.warning(_EPHEMERAL_LEARNINGS_WARNING, dest)
            ctx.tool_state.learnings_review_delta = build_learnings_review_delta(
                before=seed,
                after=current,
            )
        else:
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
    dest = _local_persist_path(kind="xrepo")
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            current + ("\n" if current and not current.endswith("\n") else ""), encoding="utf-8"
        )
        if persist_is_ephemeral():
            logger.warning(_EPHEMERAL_XREPO_LEARNINGS_WARNING, dest)
        else:
            logger.info("» xrepo learnings updated at {}", dest)
    except OSError as exc:
        logger.warning("xrepo learnings persist failed: {}", exc)


__all__ = [
    "LEARNINGS_FILE_NAME",
    "MAX_LEARNINGS_LENGTH",
    "XREPO_LEARNINGS_FILE_NAME",
    "build_learnings_review_delta",
    "learnings_file_path",
    "merge_learnings_delta_into_review_body",
    "persist_is_ephemeral",
    "persist_learnings",
    "persist_xrepo_learnings",
    "read_learnings_file",
    "seed_learnings_file",
    "seed_xrepo_learnings_file",
    "truncate_at_line_boundary",
    "xrepo_learnings_file_path",
]
