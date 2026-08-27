"""Pull request create/update/close tools."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.mcp.comment import add_footer
from mergecraft.mcp.shared import ToolClass, execute, tool
from mergecraft.utils.git_hardening import git_argv

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext


def _current_branch(cwd: str) -> str:
    return subprocess.check_output(
        git_argv(["rev-parse", "--abbrev-ref", "HEAD"]),
        cwd=cwd,
        text=True,
        timeout=10,
    ).strip()


def create_pull_request_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        cwd = primary_dir(ctx)
        head = _current_branch(cwd)
        body = add_footer(ctx, str(params["body"]))
        result = await ctx.scm.post(
            f"/repos/{ctx.repo.owner}/{ctx.repo.name}/pulls",
            json={
                "title": str(params["title"]),
                "body": body,
                "head": head,
                "base": str(params["base"]),
                "draft": bool(params.get("draft", False)),
            },
        )
        logger.info("created PR #{}", result.get("number"))
        reviewer = ctx.payload.triggerer
        if reviewer:
            try:
                await ctx.scm.post(
                    f"/repos/{ctx.repo.owner}/{ctx.repo.name}/pulls/{result['number']}/requested_reviewers",
                    json={"reviewers": [reviewer]},
                )
            except Exception:
                logger.info("failed to request review from {}", reviewer)
        return {
            "success": True,
            "pullRequestId": result.get("id"),
            "number": result.get("number"),
            "url": result.get("html_url"),
            "title": result.get("title"),
            "head": (result.get("head") or {}).get("ref"),
            "base": (result.get("base") or {}).get("ref"),
        }

    return tool(
        name="create_pull_request",
        tool_class=ToolClass.GITHUB_MUTATION,
        mutates=True,
        description="Create a pull request from the current branch",
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body": {"type": "string"},
                "base": {"type": "string"},
                "draft": {"type": "boolean"},
                "repo": {"type": "string"},
            },
            "required": ["title", "body", "base"],
            "additionalProperties": False,
        },
        execute=execute(_run, "create_pull_request"),
    )


def update_pull_request_body_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        body = add_footer(ctx, str(params["body"]))
        result = await ctx.scm.update_pull(
            ctx.repo.owner,
            ctx.repo.name,
            int(params["pull_number"]),
            body=body,
        )
        ctx.tool_state.was_updated = True
        return {
            "success": True,
            "number": result.get("number"),
            "url": result.get("html_url"),
        }

    return tool(
        name="update_pull_request_body",
        tool_class=ToolClass.GITHUB_MUTATION,
        mutates=True,
        description="Update the body/description of an existing pull request",
        input_schema={
            "type": "object",
            "properties": {
                "pull_number": {"type": "number"},
                "body": {"type": "string"},
            },
            "required": ["pull_number", "body"],
            "additionalProperties": False,
        },
        execute=execute(_run, "update_pull_request_body"),
    )


def close_pull_request_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        result = await ctx.scm.update_pull(
            ctx.repo.owner,
            ctx.repo.name,
            int(params["pull_number"]),
            state="closed",
        )
        ctx.tool_state.was_updated = True
        return {
            "success": True,
            "number": result.get("number"),
            "url": result.get("html_url"),
            "state": result.get("state"),
        }

    return tool(
        name="close_pull_request",
        tool_class=ToolClass.GITHUB_MUTATION,
        mutates=True,
        description="Close an open pull request WITHOUT merging it.",
        input_schema={
            "type": "object",
            "properties": {"pull_number": {"type": "number"}},
            "required": ["pull_number"],
            "additionalProperties": False,
        },
        execute=execute(_run, "close_pull_request"),
    )


def primary_dir(ctx: ToolContext) -> str:
    from mergecraft.mcp.tool_state import primary_repo_state

    return primary_repo_state(ctx.tool_state).dir
