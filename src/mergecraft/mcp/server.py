"""FastAPI/Starlette HTTP MCP-like server exposing tools/list and tools/call."""

from __future__ import annotations

import asyncio
import json
import os
import random
import signal
import socket
from typing import TYPE_CHECKING, Any

import uvicorn
from fastapi import FastAPI, Request, Response
from loguru import logger
from starlette.responses import JSONResponse

from mergecraft.analyzers.trust import analyzers_enabled
from mergecraft.mcp.analyzers import analyzer_findings_tool, run_analyzers_tool
from mergecraft.mcp.check_runs import get_check_suite_tool, list_check_runs_tool
from mergecraft.mcp.check_suite import get_check_suite_logs_tool
from mergecraft.mcp.checkout import checkout_pr_tool
from mergecraft.mcp.ci_intelligence import analyze_ci_failures_tool
from mergecraft.mcp.comment import (
    create_issue_comment_tool,
    edit_issue_comment_tool,
    reply_to_review_comment_tool,
    report_progress_tool,
)
from mergecraft.mcp.commit_info import get_commit_info_tool
from mergecraft.mcp.dependencies import (
    await_dependency_installation_tool,
    start_dependency_installation_tool,
)
from mergecraft.mcp.git import (
    commit_changes_tool,
    delete_branch_tool,
    git_fetch_tool,
    git_tool,
    push_branch_tool,
    push_tags_tool,
)
from mergecraft.mcp.issue import close_issue_tool, create_issue_tool, reopen_issue_tool
from mergecraft.mcp.issue_comments import get_issue_comments_tool
from mergecraft.mcp.issue_events import get_issue_events_tool
from mergecraft.mcp.issue_info import get_issue_tool
from mergecraft.mcp.labels import add_labels_tool, remove_labels_tool
from mergecraft.mcp.output import set_output_tool
from mergecraft.mcp.pr import (
    close_pull_request_tool,
    create_pull_request_tool,
    update_pull_request_body_tool,
)
from mergecraft.mcp.pr_info import get_pull_request_tool
from mergecraft.mcp.review import create_pull_request_review_tool
from mergecraft.mcp.review_comments import (
    get_review_comments_tool,
    list_pull_request_reviews_tool,
    resolve_review_thread_tool,
)
from mergecraft.mcp.select_mode import select_mode_tool
from mergecraft.mcp.shared import JsonSchema, ToolResult, ToolSpec
from mergecraft.mcp.shell import kill_background_tool, shell_tool
from mergecraft.mcp.static_checks import run_static_checks_tool
from mergecraft.mcp.upload import upload_file_tool
from mergecraft.mcp.xrepo import checkout_repo_tool, list_repos_tool
from mergecraft.types import MERGECRAFT_MCP_NAME

if TYPE_CHECKING:
    from collections.abc import Callable

    from mergecraft.mcp.context import ToolContext

MCP_PORT_START = 3764
MCP_PORT_ATTEMPTS = 100
MCP_HOST = "127.0.0.1"
MCP_ENDPOINT = "/mcp"


def build_common_tools(ctx: ToolContext, output_schema: JsonSchema | None = None) -> list[ToolSpec]:
    tools: list[ToolSpec] = [
        start_dependency_installation_tool(ctx),
        await_dependency_installation_tool(ctx),
        create_issue_comment_tool(ctx),
        edit_issue_comment_tool(ctx),
        reply_to_review_comment_tool(ctx),
        create_issue_tool(ctx),
        close_issue_tool(ctx),
        reopen_issue_tool(ctx),
        get_issue_tool(ctx),
        get_issue_comments_tool(ctx),
        get_issue_events_tool(ctx),
        create_pull_request_review_tool(ctx),
        get_pull_request_tool(ctx),
        get_commit_info_tool(ctx),
        checkout_pr_tool(ctx),
        get_review_comments_tool(ctx),
        list_pull_request_reviews_tool(ctx),
        resolve_review_thread_tool(ctx),
        get_check_suite_logs_tool(ctx),
        list_check_runs_tool(ctx),
        get_check_suite_tool(ctx),
        analyze_ci_failures_tool(ctx),
        add_labels_tool(ctx),
        remove_labels_tool(ctx),
        git_tool(ctx),
        git_fetch_tool(ctx),
        upload_file_tool(ctx),
    ]
    if ctx.static_checks_enabled:
        tools.append(run_static_checks_tool(ctx))
    if analyzers_enabled(ctx):
        tools.extend([run_analyzers_tool(ctx), analyzer_findings_tool(ctx)])
    if ctx.xrepo is not None:
        tools.extend([list_repos_tool(ctx), checkout_repo_tool(ctx)])
    is_standalone = ctx.payload.event.trigger == "unknown"
    if is_standalone or output_schema is not None:
        tools.append(set_output_tool(ctx, output_schema))
    if ctx.payload.shell == "restricted":
        tools.extend([shell_tool(ctx), kill_background_tool(ctx)])
    return tools


def build_orchestrator_tools(
    ctx: ToolContext, output_schema: JsonSchema | None = None
) -> list[ToolSpec]:
    tools = [
        *build_common_tools(ctx, output_schema),
        report_progress_tool(ctx),
        select_mode_tool(ctx),
        push_branch_tool(ctx),
        push_tags_tool(ctx),
        delete_branch_tool(ctx),
        create_pull_request_tool(ctx),
        update_pull_request_body_tool(ctx),
        close_pull_request_tool(ctx),
    ]
    if ctx.signed_commits:
        tools.append(commit_changes_tool(ctx))
    return tools


def _read_env_port() -> int | None:
    raw = os.environ.get("MERGECRAFT_MCP_PORT")
    if not raw:
        return None
    try:
        parsed = int(raw)
    except ValueError as err:
        msg = f"invalid MERGECRAFT_MCP_PORT: {raw}"
        raise ValueError(msg) from err
    if parsed <= 0 or parsed > 65535:
        msg = f"invalid MERGECRAFT_MCP_PORT: {raw}"
        raise ValueError(msg)
    return parsed


def _port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((MCP_HOST, port))
        except OSError:
            return False
    return True


def _select_port() -> int:
    requested = _read_env_port()
    if requested is not None and _port_available(requested):
        return requested
    offset0 = random.randint(0, 49)
    for offset in range(MCP_PORT_ATTEMPTS):
        port = MCP_PORT_START + offset0 + offset
        if _port_available(port):
            return port
    msg = f"could not find available mcp port starting at {MCP_PORT_START}"
    raise RuntimeError(msg)


def _tool_result_to_rpc(result: ToolResult | Any) -> dict[str, Any]:
    if isinstance(result, ToolResult):
        out: dict[str, Any] = {"content": result.content}
        if result.is_error:
            out["isError"] = True
        return out
    if isinstance(result, dict) and "content" in result:
        return result
    return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}


def create_mcp_app(tools: list[ToolSpec]) -> FastAPI:
    by_name = {t.name: t for t in tools}
    app = FastAPI(title=MERGECRAFT_MCP_NAME, version="0.0.1")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    async def handle_rpc(body: dict[str, Any]) -> dict[str, Any]:
        req_id = body.get("id")
        method = body.get("method")
        params = body.get("params") or {}
        if method in {"initialize", "notifications/initialized"}:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": MERGECRAFT_MCP_NAME, "version": "0.0.1"},
                },
            }
        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": [t.list_entry() for t in tools]},
            }
        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") or {}
            if not isinstance(name, str):
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": "tools/call requires string name"},
                }
            if not isinstance(arguments, dict):
                arguments = {}
            tool = by_name.get(name)
            if tool is None:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Unknown tool: {name}"},
                }
            result = await tool.execute(arguments)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": _tool_result_to_rpc(result),
            }
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    @app.api_route(MCP_ENDPOINT, methods=["GET", "POST", "DELETE"])
    async def mcp_endpoint(request: Request) -> Response:
        if request.method == "GET":
            # Streamable HTTP / SSE clients may probe with GET — reply with tool list.
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "result": {"tools": [t.list_entry() for t in tools]},
                }
            )
        if request.method == "DELETE":
            return Response(status_code=204)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "error": {"code": -32700, "message": "Parse error"},
                },
                status_code=400,
            )
        if isinstance(body, list):
            results = [await handle_rpc(item) for item in body]
            return JSONResponse(results)
        return JSONResponse(await handle_rpc(body))

    return app


async def _kill_background_processes(ctx: ToolContext) -> None:
    procs = ctx.tool_state.background_processes
    if not procs:
        return
    for proc in list(procs.values()):
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError, PermissionError, OSError:
            pass
    await asyncio.sleep(0.2)
    for proc in list(procs.values()):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError, PermissionError, OSError:
            pass
    procs.clear()


def start_mcp_http_server(
    ctx: ToolContext,
    *,
    output_schema: JsonSchema | None = None,
) -> tuple[str, Callable[[], None]]:
    """Start the MCP HTTP server.

    Returns ``(url, stop)`` where ``stop`` is an idempotent disposer.
    """
    tools = build_orchestrator_tools(ctx, output_schema)
    port = _select_port()
    app = create_mcp_app(tools)
    config = uvicorn.Config(
        app,
        host=MCP_HOST,
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    loop = asyncio.new_event_loop()

    def _run() -> None:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(server.serve())

    import threading

    thread = threading.Thread(target=_run, name="mergecraft-mcp", daemon=True)
    thread.start()

    # Wait briefly for bind
    for _ in range(50):
        if getattr(server, "started", False):
            break
        # uvicorn sets started after startup; also probe the port
        if not _port_available(port):
            # port is in use by our server (or something) — good enough after thread start
            try:
                with socket.create_connection((MCP_HOST, port), timeout=0.1):
                    break
            except OSError:
                pass
        import time

        time.sleep(0.05)

    url = f"http://{MCP_HOST}:{port}{MCP_ENDPOINT}"
    ctx.mcp_server_url = url
    logger.info("MCP HTTP server listening at {}", url)

    disposed = False

    def stop() -> None:
        nonlocal disposed
        if disposed:
            return
        disposed = True
        try:
            loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(_kill_background_processes(ctx), loop=loop)
            )
        except Exception:
            pass
        server.should_exit = True
        thread.join(timeout=5)

    return url, stop
