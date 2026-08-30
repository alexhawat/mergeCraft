"""get_commit_info tool."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.mcp.shared import ToolClass, execute, tool
from mergecraft.mcp.tool_state import primary_repo_state

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext


def get_commit_info_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        sha = str(params["sha"])
        data = await ctx.scm.get_commit(ctx.repo.owner, ctx.repo.name, sha)
        files = data.get("files") or []
        parts: list[str] = []
        for f in files:
            parts.append(f"--- a/{f.get('filename')}\n+++ b/{f.get('filename')}\n")
            if f.get("patch"):
                parts.append(f.get("patch") + "\n")
        content = "".join(parts)
        temp = os.environ.get("MERGECRAFT_TEMP_DIR") or ctx.tmpdir
        diff_file = str(Path(temp) / f"commit-{sha[:7]}.diff")
        Path(diff_file).write_text(content, encoding="utf-8")
        logger.debug("wrote commit diff to {} ({} bytes)", diff_file, len(content))
        primary = primary_repo_state(ctx.tool_state)
        pr_head = (primary.checkout_sha or "").strip().lower()
        if pr_head and sha.strip().lower() == pr_head:
            from mergecraft.mcp.verdict import register_review_scope, validate_review_scope_evidence

            await validate_review_scope_evidence(ctx, diff_path=diff_file, head_sha=sha)
            register_review_scope(
                ctx.tool_state,
                diff_path=diff_file,
                provenance="commit-info",
                review_scope=ctx.tool_state.review_scope,
            )
        stats = data.get("stats") or {}
        return {
            "sha": data.get("sha"),
            "message": (data.get("commit") or {}).get("message"),
            "author": (data.get("author") or {}).get("login"),
            "committer": (data.get("committer") or {}).get("login"),
            "date": ((data.get("commit") or {}).get("author") or {}).get("date")
            or ((data.get("commit") or {}).get("committer") or {}).get("date")
            or "",
            "url": data.get("html_url"),
            "parents": [p.get("sha") for p in (data.get("parents") or [])],
            "stats": {
                "additions": stats.get("additions", 0),
                "deletions": stats.get("deletions", 0),
                "total": stats.get("total", 0),
            },
            "fileCount": len(files),
            "diffFile": diff_file,
        }

    return tool(
        name="get_commit_info",
        tool_class=ToolClass.REPOSITORY_READ,
        description=(
            "Retrieve commit metadata and diff via GitHub API. Returns diffFile "
            "pointing to formatted diff."
        ),
        input_schema={
            "type": "object",
            "properties": {"sha": {"type": "string"}},
            "required": ["sha"],
            "additionalProperties": False,
        },
        execute=execute(_run, "get_commit_info"),
    )
