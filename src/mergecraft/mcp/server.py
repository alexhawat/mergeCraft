"""FastAPI/Starlette HTTP MCP-like server exposing tools/list and tools/call."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import threading
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
from mergecraft.mcp.endpoints import (
    MCP_ENDPOINT as MCP_ENDPOINT,
)
from mergecraft.mcp.endpoints import (
    MCP_REVIEWER_ENDPOINT as MCP_REVIEWER_ENDPOINT,
)
from mergecraft.mcp.endpoints import (
    MCP_VERIFIER_ENDPOINT as MCP_VERIFIER_ENDPOINT,
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
from mergecraft.mcp.ports import (
    MCP_HOST as MCP_HOST,
)
from mergecraft.mcp.ports import (
    attach_serve_error_sink,
    resolve_uvicorn_bind_port,
    wait_for_bound_port,
)
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
from mergecraft.mcp.rpc import dispatch_mcp_rpc, package_version
from mergecraft.mcp.rpc_types import json_rpc_parse_error
from mergecraft.mcp.select_mode import select_mode_tool
from mergecraft.mcp.shared import (
    PRIMARY_MUTATING_ALLOWLIST,
    PRIMARY_REVIEWER_ALLOWED_TOOL_CLASSES,
    READONLY_MUTATING_ALLOWLIST,
    VERIFIER_ALLOWED_TOOL_CLASSES,
    JsonSchema,
    ToolClass,
    ToolSpec,
    admits_readonly_role,
)
from mergecraft.mcp.shell import (
    detect_sandbox_method,
    kill_background_tool,
    network_namespace_available,
    shell_tool,
)
from mergecraft.mcp.static_checks import run_static_checks_tool
from mergecraft.mcp.upload import upload_file_tool
from mergecraft.mcp.verdict import establish_review_scope_tool, submit_review_verdict_tool
from mergecraft.mcp.verification import (
    record_finding_verdict_tool,
    verify_agent_findings_tool,
)
from mergecraft.mcp.xrepo import checkout_repo_tool, list_repos_tool
from mergecraft.scm.ingress import accept_webhook
from mergecraft.types import MERGECRAFT_MCP_NAME
from mergecraft.utils.process_group import kill_process_groups

if TYPE_CHECKING:
    from collections.abc import Callable

    from jsonschema.protocols import Validator

    from mergecraft.mcp.context import ToolContext


def _shell_tools_available(ctx: ToolContext) -> bool:
    """Whether restricted shell tools may be registered for this context."""
    if ctx.payload.shell != "restricted":
        return False
    if ctx.trust_tier == "untrusted":
        if detect_sandbox_method() == "none":
            return False
        if not network_namespace_available():
            return False
    return True


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
        establish_review_scope_tool(ctx),
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
        # C6 — agent-authored findings reach the verifier through these two.
        # Registered unconditionally: the reviewer writes findings on every
        # run, including runs where no analyzer matched the diff.
        verify_agent_findings_tool(ctx),
        record_finding_verdict_tool(ctx),
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
    if _shell_tools_available(ctx):
        tools.extend([shell_tool(ctx), kill_background_tool(ctx)])
    return tools


def _filter_tools_by_class(
    tools: list[ToolSpec],
    allowed: frozenset[ToolClass],
    *,
    mutating_allowlist: frozenset[str] = READONLY_MUTATING_ALLOWLIST,
) -> list[ToolSpec]:
    filtered = [
        spec
        for spec in tools
        if admits_readonly_role(spec, allowed, mutating_allowlist=mutating_allowlist)
    ]
    if not filtered:
        msg = "class filter yielded an empty toolset"
        raise RuntimeError(msg)
    return filtered


def build_reviewer_tools(
    ctx: ToolContext,
    output_schema: JsonSchema | None = None,
) -> list[ToolSpec]:
    """Primary reviewer surface — class-filtered with publication admission (D9).

    ``PRIMARY_MUTATING_ALLOWLIST`` explicitly names ``create_pull_request_review``
    (and ``checkout_pr``), plus the three session tools the primary must call:
    ``set_output`` (Action output / offline --json), ``select_mode`` (Step 1 of
    the default procedure), and ``report_progress`` (no-action path).
    REVIEW_WRITE class is shared by several tools so class membership alone would
    leak review-write tools to the reviewer; the named allowlist stays the sole
    gate for D9 publication.  Subagents are denied publication via
    ``gates.subagent_denied_tool_names`` regardless of class.
    """
    return _filter_tools_by_class(
        build_orchestrator_tools(ctx, output_schema),
        PRIMARY_REVIEWER_ALLOWED_TOOL_CLASSES,
        mutating_allowlist=PRIMARY_MUTATING_ALLOWLIST,
    )


def build_verifier_tools(
    ctx: ToolContext,
    output_schema: JsonSchema | None = None,
) -> list[ToolSpec]:
    """Read-only verifier surface — class-filtered, distinct from reviewer (H4)."""
    return _filter_tools_by_class(
        build_orchestrator_tools(ctx, output_schema),
        VERIFIER_ALLOWED_TOOL_CLASSES,
    )


def build_orchestrator_tools(
    ctx: ToolContext, output_schema: JsonSchema | None = None
) -> list[ToolSpec]:
    tools = [
        *build_common_tools(ctx, output_schema),
        report_progress_tool(ctx),
        select_mode_tool(ctx),
        submit_review_verdict_tool(ctx),
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


def _is_notification(message: Any) -> bool:
    return isinstance(message, dict) and "id" not in message


def _register_mcp_route(
    app: FastAPI,
    path: str,
    tools: list[ToolSpec],
    tool_ctx: ToolContext | None,
    auth_token: str | None = None,
    *,
    return_tool_errors: bool = False,
) -> None:
    """Mount one JSON-RPC MCP endpoint with a fixed tool surface."""
    by_name = {t.name: t for t in tools}
    validators: dict[str, Validator] = {}

    async def handle_rpc(body: dict[str, Any], *, agent_id: str | None = None) -> dict[str, Any]:
        req_id = body.get("id")
        method = body.get("method")
        params = body.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        return await dispatch_mcp_rpc(
            req_id,
            method,
            params,
            tools=tools,
            by_name=by_name,
            tool_ctx=tool_ctx,
            validators=validators,
            agent_id=agent_id,
            return_tool_errors=return_tool_errors,
        )

    async def mcp_endpoint(request: Request) -> Response:
        # D15 — auth at request edge: every tools/list and tools/call (including
        # GET probes) requires Bearer token when one was issued at startup.
        # /health stays unauthenticated; x-mergecraft-agent-id is tracing-only.
        if auth_token:
            raw_auth = request.headers.get("Authorization") or ""
            # Use compare_digest to prevent timing-based token oracle attacks.
            if not secrets.compare_digest(raw_auth.encode(), f"Bearer {auth_token}".encode()):
                return JSONResponse(
                    {"jsonrpc": "2.0", "error": {"code": -32600, "message": "Unauthorized"}},
                    status_code=401,
                )
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
            # No envelope id: a parse failure has no request id to echo (see json_rpc_parse_error).
            return JSONResponse(
                json_rpc_parse_error(include_id=False),
                status_code=400,
            )
        items = body if isinstance(body, list) else [body]
        # D10 (OB4) — the dispatch-issued agent id, forwarded by the agent
        # CLI's MCP client config as a header on every call.
        calling_agent_id = request.headers.get("x-mergecraft-agent-id") or None
        # A JSON-RPC message with no `id` is a notification. The streamable-HTTP
        # spec requires 202 with an empty body for a notification-only POST;
        # answering one with a response object (`"id": null`) makes a strict
        # client — Codex's rmcp — fail to deserialize it, kill the transport
        # worker mid-handshake, and report the server as "not ready".
        if all(_is_notification(item) for item in items):
            return Response(status_code=202)
        if isinstance(body, list):
            # Notifications (no ``id``) must not produce a response and must not
            # be dispatched to handle_rpc — a notification-shaped tools/call in a
            # mixed batch would otherwise execute the tool and return id=null.
            return JSONResponse(
                [
                    await handle_rpc(item, agent_id=calling_agent_id)
                    for item in items
                    if not _is_notification(item)
                ]
            )
        return JSONResponse(await handle_rpc(body, agent_id=calling_agent_id))

    app.add_api_route(
        path,
        mcp_endpoint,
        methods=["GET", "POST", "DELETE"],
        name=f"mcp_{path.strip('/').replace('/', '_')}",
    )


def create_mcp_app(
    tools: list[ToolSpec],
    ctx: ToolContext | None = None,
    *,
    role_tools: dict[str, list[ToolSpec]] | None = None,
    auth_token: str | None = None,
    orchestrator_auth_token: str | None = None,
    return_tool_errors: bool = False,
    health_nonce: str | None = None,
) -> FastAPI:
    """Build the MCP app.

    ``ctx`` is optional so a test can stand the app up with bare tool specs;
    when it is supplied — which is what ``start_mcp_http_server`` does on every
    real run — each ``tools/call`` is appended to the run's trajectory record.

    ``role_tools`` mounts extra class-filtered surfaces at ``{MCP_ENDPOINT}/{role}``
    (the reviewer lives at ``MCP_REVIEWER_ENDPOINT``, the verifier at
    ``MCP_VERIFIER_ENDPOINT``). The primary endpoint stays the orchestrator set.

    ``auth_token`` secures reviewer/verifier role routes (and any caller that
    passes only one token). ``orchestrator_auth_token``, when supplied, secures
    the primary ``/mcp`` orchestrator surface separately from the harness token.

    When ``tools`` is empty or ``None``, the ``/mcp`` primary endpoint is omitted
    and only ``/health`` and any ``role_tools`` routes are registered.
    """
    app = FastAPI(title=MERGECRAFT_MCP_NAME, version=package_version())

    @app.get("/health")
    async def health(nonce: str | None = None) -> dict[str, str]:
        if health_nonce is not None and nonce != health_nonce:
            return {"status": "forbidden"}
        payload: dict[str, str] = {"status": "ok"}
        if health_nonce is not None:
            payload["nonce"] = health_nonce
        return payload

    @app.post("/webhooks/{provider}")
    async def inbound_webhook(provider: str, request: Request) -> JSONResponse:
        secret = os.environ.get("MERGECRAFT_WEBHOOK_SECRET", "")
        body = await request.body()
        headers = {key: value for key, value in request.headers.items()}
        try:
            result = accept_webhook(provider, headers=headers, body=body, secret=secret)
        except PermissionError as exc:
            return JSONResponse({"error": str(exc)}, status_code=401)
        except (ValueError, json.JSONDecodeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(
            {
                "result_id": result.result_id,
                "duplicate": result.duplicate,
                "provider": result.provider,
                "event": result.event,
            }
        )

    primary_token = orchestrator_auth_token if orchestrator_auth_token is not None else auth_token
    if tools:
        _register_mcp_route(app, MCP_ENDPOINT, tools, ctx, primary_token)
    for role, role_tool_list in (role_tools or {}).items():
        _register_mcp_route(
            app,
            f"{MCP_ENDPOINT}/{role}",
            role_tool_list,
            ctx,
            auth_token,
            return_tool_errors=return_tool_errors,
        )
    return app


async def _kill_background_processes(ctx: ToolContext) -> None:
    procs = ctx.tool_state.background_processes
    if not procs:
        return
    pids = {proc.pid for proc in list(procs.values()) if isinstance(proc.pid, int)}
    # Off-loop: batch TERM -> one grace -> KILL (avoids N-times sleep on the event loop).
    await asyncio.to_thread(kill_process_groups, pids)
    procs.clear()


def _serve_in_thread(
    config: uvicorn.Config,
    *,
    thread_name: str,
) -> tuple[uvicorn.Server, threading.Thread, asyncio.AbstractEventLoop]:
    """Start a uvicorn server on a new event loop in a daemon thread.

    Returns ``(server, thread, loop)`` so callers can stop the server
    (``server.should_exit = True``), join the thread, and schedule
    cleanup on the loop.
    """
    server = uvicorn.Server(config)
    loop = asyncio.new_event_loop()
    serve_errors = attach_serve_error_sink(server)

    def _run() -> None:
        try:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(server.serve())
        except BaseException as exc:
            serve_errors.append(exc)

    thread = threading.Thread(target=_run, name=thread_name, daemon=True)
    thread.start()
    return server, thread, loop


def start_mcp_http_server(
    ctx: ToolContext,
    *,
    output_schema: JsonSchema | None = None,
) -> tuple[str, Callable[[], None]]:
    """Start the MCP HTTP server.

    Returns ``(url, stop)`` where ``stop`` is an idempotent disposer.
    """
    # D15 — issue per-run secrets at startup. Agent harnesses receive
    # ``mcp_auth_token`` for reviewer/verifier role routes; the orchestrator
    # ``/mcp`` surface gets its own bearer so a leaked harness token cannot
    # call orchestrator-only tools after dispatch.
    agent_token = secrets.token_hex(32)
    orchestrator_token = secrets.token_hex(32)
    health_nonce = secrets.token_hex(16)
    ctx.mcp_auth_token = agent_token
    ctx.mcp_orchestrator_auth_token = orchestrator_token

    tools = build_orchestrator_tools(ctx, output_schema)
    reviewer_tools = build_reviewer_tools(ctx, output_schema)
    verifier_tools = build_verifier_tools(ctx, output_schema)
    app = create_mcp_app(
        tools,
        ctx,
        role_tools={"reviewer": reviewer_tools, "verifier": verifier_tools},
        auth_token=agent_token,
        orchestrator_auth_token=orchestrator_token,
        health_nonce=health_nonce,
    )
    bind_port = resolve_uvicorn_bind_port()
    http_config = uvicorn.Config(
        app,
        host=MCP_HOST,
        port=bind_port,
        log_level="warning",
        access_log=False,
    )
    server, thread, loop = _serve_in_thread(http_config, thread_name="mergecraft-mcp")

    port = wait_for_bound_port(server, bind_port, health_nonce=health_nonce)

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
        except Exception as exc:
            logger.warning("background-process kill scheduling failed: {}", exc)
        server.should_exit = True
        thread.join(timeout=5)

    return url, stop
