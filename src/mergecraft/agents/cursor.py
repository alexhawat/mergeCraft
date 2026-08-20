"""Cursor Cloud Agent harness — launches a cloud agent via the Cursor API."""

from __future__ import annotations

import asyncio
import os
from typing import Any
from urllib.parse import urlparse

from loguru import logger

from mergecraft.agents.post_run import finalize_agent_result
from mergecraft.agents.shared import (
    AgentResult,
    AgentRunContext,
    AgentUsage,
    agent,
    log_token_table,
    mcp_auth_headers,
    payload_event_branch,
)
from mergecraft.integrations.cursor_cloud.client import (
    CURSOR_API_KEY_ENV,
    CursorCloudClient,
    resolve_cursor_api_key,
)
from mergecraft.mcp.tool_state import primary_repo_state
from mergecraft.types import MERGECRAFT_MCP_NAME

_TERMINAL_STATUSES = frozenset(
    {
        "completed",
        "complete",
        "finished",
        "failed",
        "failure",
        "cancelled",
        "canceled",
        "error",
        "COMPLETED",
        "FINISHED",
        "FAILED",
        "CANCELLED",
        "ERROR",
        "EXPIRED",
        "expired",
    }
)
_POLL_INTERVAL_S = 5.0
_DEFAULT_CLOUD_MODEL = "composer-2"


def _strip_provider_prefix(specifier: str) -> str:
    slash = specifier.find("/")
    return specifier[slash + 1 :] if slash > 0 else specifier


def _resolve_cloud_model_id(ctx: AgentRunContext) -> str:
    if not ctx.resolved_model:
        return _DEFAULT_CLOUD_MODEL
    slug = _strip_provider_prefix(ctx.resolved_model)
    if slug in {"", "cloud-agent", "default"}:
        return _DEFAULT_CLOUD_MODEL
    return slug


def _repo_url_from_ctx(ctx: AgentRunContext) -> str:
    repo = primary_repo_state(ctx.tool_state)
    return f"https://github.com/{repo.owner}/{repo.name}"


def _starting_ref_from_ctx(ctx: AgentRunContext) -> str:
    branch = payload_event_branch(ctx)
    if branch:
        return branch
    repo = primary_repo_state(ctx.tool_state)
    push_dest = repo.push_dest
    if push_dest is not None and push_dest.remote_branch.strip():
        return push_dest.remote_branch.strip()
    if repo.initial_head and repo.initial_head.kind == "branch":
        return repo.initial_head.name
    if repo.default_branch:
        return repo.default_branch
    return "main"


def _build_review_prompt(ctx: AgentRunContext, *, subagent_block: str | None = None) -> str:
    parts: list[str] = []
    system = getattr(ctx.instructions, "system", "")
    if isinstance(system, str) and system.strip():
        parts.append(system.strip())
    if subagent_block:
        parts.append(subagent_block)
    user = getattr(ctx.instructions, "user", "")
    if isinstance(user, str) and user.strip():
        parts.append(user.strip())
    return "\n\n".join(parts) if parts else "Review this pull request."


def _mcp_url_unreachable_from_cloud(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in {"127.0.0.1", "localhost", "::1"} or host.startswith("127.")


def _build_mcp_servers(ctx: AgentRunContext) -> list[dict[str, Any]]:
    if not ctx.mcp_server_url:
        return []
    if _mcp_url_unreachable_from_cloud(ctx.mcp_server_url):
        logger.warning(
            "cursor cloud agent cannot reach mergeCraft MCP at {} — "
            "MCP tools are omitted; the cloud run uses the review prompt only",
            ctx.mcp_server_url,
        )
        return []
    server_entry: dict[str, Any] = {
        "name": MERGECRAFT_MCP_NAME,
        "type": "sse",
        "url": ctx.mcp_server_url,
    }
    auth = mcp_auth_headers(ctx)
    if auth:
        server_entry["headers"] = auth
    return [server_entry]


def _is_terminal_status(status: str) -> bool:
    return status.strip() in _TERMINAL_STATUSES


def _parse_usage(run: dict[str, object]) -> AgentUsage | None:
    usage_raw = run.get("usage")
    if not isinstance(usage_raw, dict):
        return None
    input_tokens = int(usage_raw.get("input_tokens") or usage_raw.get("inputTokens") or 0)
    output_tokens = int(usage_raw.get("output_tokens") or usage_raw.get("outputTokens") or 0)
    if input_tokens == 0 and output_tokens == 0:
        return None
    log_token_table(
        input_tokens=input_tokens,
        cache_read=0,
        cache_write=0,
        output=output_tokens,
    )
    return AgentUsage(agent="cursor", input_tokens=input_tokens, output_tokens=output_tokens)


def _result_text_from_run(run: dict[str, object]) -> str:
    result = run.get("result")
    if isinstance(result, str) and result.strip():
        return result.strip()
    summary = run.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    return ""


async def _poll_run_to_terminal(
    client: CursorCloudClient,
    *,
    run_id: str,
) -> dict[str, object]:
    timeout_s = float(os.environ.get("MERGECRAFT_AGENT_TIMEOUT", "3600"))
    deadline = asyncio.get_running_loop().time() + timeout_s
    last: dict[str, object] = {}

    while asyncio.get_running_loop().time() < deadline:
        last = await client.get_run(run_id)
        status = str(last.get("status") or "")
        if _is_terminal_status(status):
            return last
        await asyncio.sleep(_POLL_INTERVAL_S)

    msg = (
        f"cursor cloud agent run {run_id!r} did not reach a terminal status within {timeout_s:.0f}s"
    )
    raise TimeoutError(msg)


async def _run_cursor_once(
    *,
    ctx: AgentRunContext,
    subagent_block: str | None = None,
) -> AgentResult:
    api_key = resolve_cursor_api_key()
    if not api_key:
        return AgentResult(
            success=False,
            error=(
                f"{CURSOR_API_KEY_ENV} is not set. Configure a Cursor API key secret "
                "or run `mergecraft auth cursor`."
            ),
        )

    client = CursorCloudClient(api_key=api_key)
    prompt = _build_review_prompt(ctx, subagent_block=subagent_block)
    repo_url = _repo_url_from_ctx(ctx)
    starting_ref = _starting_ref_from_ctx(ctx)
    model_id = _resolve_cloud_model_id(ctx)

    logger.info(
        "launching Cursor Cloud agent (repo={}, ref={}, model={})",
        repo_url,
        starting_ref,
        model_id,
    )

    try:
        created = await client.create_cloud_agent(
            prompt=prompt,
            repo_url=repo_url,
            starting_ref=starting_ref,
            model=model_id,
            auto_create_pr=False,
            mcp_servers=_build_mcp_servers(ctx),
        )
    except (RuntimeError, ValueError) as exc:
        return AgentResult(success=False, error=str(exc))

    run_id = str(created.get("run_id") or created.get("id") or "")
    dashboard_url = str(created.get("dashboard_url") or "")
    if dashboard_url:
        logger.info("cursor cloud dashboard: {}", dashboard_url)

    if not run_id:
        return AgentResult(
            success=False,
            error="cursor cloud agent create response missing run id",
            metadata={"dashboard_url": dashboard_url} if dashboard_url else {},
        )

    try:
        run = await _poll_run_to_terminal(client, run_id=run_id)
    except TimeoutError as exc:
        return AgentResult(
            success=False,
            error=str(exc),
            metadata={"dashboard_url": dashboard_url} if dashboard_url else {},
        )
    except RuntimeError as exc:
        return AgentResult(
            success=False,
            error=str(exc),
            metadata={"dashboard_url": dashboard_url} if dashboard_url else {},
        )

    try:
        await client.list_artifacts(run_id)
    except RuntimeError as exc:
        logger.warning("cursor cloud artifact listing failed (run already terminal): {}", exc)

    status = str(run.get("status") or "")
    output = _result_text_from_run(run)
    usage = _parse_usage(run)
    metadata: dict[str, Any] = {}
    if dashboard_url:
        metadata["dashboard_url"] = dashboard_url

    if status.upper() in {"FAILED", "FAILURE", "ERROR", "CANCELLED", "CANCELED", "EXPIRED"}:
        detail = str(run.get("error") or run.get("message") or status)
        return AgentResult(
            success=False,
            output=output or None,
            error=f"cursor cloud agent failed: {detail}",
            metadata=metadata,
            usage=usage,
        )

    return AgentResult(
        success=True,
        output=output or None,
        metadata=metadata,
        usage=usage,
    )


async def _install(_token: str | None = None) -> str:
    if resolve_cursor_api_key():
        return "cursor-cloud"
    msg = (
        f"{CURSOR_API_KEY_ENV} is not set. Configure a Cursor API key secret "
        "or run `mergecraft auth cursor`."
    )
    raise FileNotFoundError(msg)


async def _run(ctx: AgentRunContext) -> AgentResult:
    from mergecraft.agents.harness_render import merge_manifest_metadata, render_for_run

    try:
        await _install(None)
    except FileNotFoundError as err:
        return AgentResult(success=False, error=str(err))

    render_result = render_for_run(ctx, "cursor")
    subagent_block = render_result.payload if isinstance(render_result.payload, str) else None
    result = await _run_cursor_once(ctx=ctx, subagent_block=subagent_block)
    finalized = await finalize_agent_result(ctx, result)
    return merge_manifest_metadata(finalized, render_result)


cursor = agent(name="cursor", install=_install, run=_run)
