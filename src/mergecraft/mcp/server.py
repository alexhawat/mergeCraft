"""FastAPI/Starlette HTTP MCP-like server exposing tools/list and tools/call."""

from __future__ import annotations

import asyncio
import json
import os
import random
import socket
from math import isfinite
from typing import TYPE_CHECKING, Any, NamedTuple

import uvicorn
from fastapi import FastAPI, Request, Response
from jsonschema import SchemaError
from jsonschema.exceptions import best_match
from jsonschema.validators import validator_for
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
from mergecraft.mcp.shared import (
    PRIMARY_MUTATING_ALLOWLIST,
    PRIMARY_REVIEWER_ALLOWED_TOOL_CLASSES,
    VERIFIER_ALLOWED_TOOL_CLASSES,
    JsonSchema,
    ToolClass,
    ToolResult,
    ToolSpec,
    admits_readonly_role,
)
from mergecraft.mcp.shell import detect_sandbox_method, kill_background_tool, shell_tool
from mergecraft.mcp.static_checks import run_static_checks_tool
from mergecraft.mcp.upload import upload_file_tool
from mergecraft.mcp.verdict import submit_review_verdict_tool
from mergecraft.mcp.verification import (
    record_finding_verdict_tool,
    verify_agent_findings_tool,
)
from mergecraft.mcp.xrepo import checkout_repo_tool, list_repos_tool
from mergecraft.tracing._tool_attrs import (
    emit_verb_subevent,
    enrich_tool_request,
    enrich_tool_response,
)
from mergecraft.tracing.tracer import get_tracer_from_settings
from mergecraft.types import MERGECRAFT_MCP_NAME
from mergecraft.utils.process_group import kill_process_groups

if TYPE_CHECKING:
    from collections.abc import Callable

    from jsonschema.protocols import Validator

    from mergecraft.mcp.context import ToolContext

MCP_PORT_START = 3764
MCP_PORT_ATTEMPTS = 100
MCP_HOST = "127.0.0.1"
MCP_ENDPOINT = "/mcp"
MCP_REVIEWER_ENDPOINT = "/mcp/reviewer"
MCP_VERIFIER_ENDPOINT = "/mcp/verifier"


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
    if ctx.payload.shell == "restricted" and not (
        ctx.trust_tier == "untrusted" and detect_sandbox_method() == "none"
    ):
        tools.extend([shell_tool(ctx), kill_background_tool(ctx)])
    return tools


def _filter_tools_by_class(
    tools: list[ToolSpec],
    allowed: frozenset[ToolClass],
    *,
    mutating_allowlist: frozenset[str] | None = None,
) -> list[ToolSpec]:
    kwargs = {} if mutating_allowlist is None else {"mutating_allowlist": mutating_allowlist}
    filtered = [spec for spec in tools if admits_readonly_role(spec, allowed, **kwargs)]
    if not filtered:
        msg = "class filter yielded an empty toolset"
        raise RuntimeError(msg)
    return filtered


def build_reviewer_tools(
    ctx: ToolContext,
    output_schema: JsonSchema | None = None,
) -> list[ToolSpec]:
    """Primary reviewer surface — includes REVIEW_WRITE for publication (D9)."""
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


def _is_notification(message: Any) -> bool:
    return isinstance(message, dict) and "id" not in message


def _span_tool_call_id() -> str:
    """Generate a stable id for a ``tool.call`` span's ``gen_ai.tool.call.id``.

    The MCP server dispatches each ``tools/call`` synchronously; a fresh uuid
    gives Logfire's GenAI dashboard a unique correlation id without leaking
    any request content.
    """
    import uuid

    return uuid.uuid4().hex


def _charge_tool_call_budget(ctx: ToolContext | None) -> None:
    """Increment the per-run tool-call budget before executing an MCP tool."""
    if ctx is None or ctx.budget_tracker is None:
        return
    ctx.budget_tracker.record_tool_call()


def _record_trajectory(
    ctx: ToolContext | None,
    name: str,
    arguments: dict[str, Any],
    *,
    ok: bool,
    result: Any = None,
    error: str | None = None,
) -> None:
    """Record one mediated tool call on the run's trajectory (#43, D8).

    This handler is the only door every agent tool call goes through, which is
    what makes the trajectory record self-contained — no tracing sinks, no
    #56. Recording is strictly best-effort: an audit trail must never be able
    to turn a working tool call into a failed one, so every error is swallowed.
    """
    if ctx is None:
        return
    try:
        from mergecraft.evidence.trajectory import outcome_ok_from_result, record_tool_call

        record_tool_call(
            ctx.tool_state,
            tool=name,
            arguments=arguments,
            ok=ok,
            outcome_ok=outcome_ok_from_result(result) if ok else None,
            error=error,
        )
    except Exception as exc:  # an audit trail never breaks a tool call
        logger.debug("trajectory: failed to record {} — {}", name, exc)


class RpcError(NamedTuple):
    """A JSON-RPC error code/message pair, before it is wrapped in an envelope."""

    code: int
    message: str


def _rpc_error(req_id: Any, error: RpcError) -> dict[str, Any]:
    """Wrap ``error`` in the JSON-RPC response envelope for ``req_id``."""
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": error.code, "message": error.message},
    }


# The JSON vocabulary and its two string encodings, nothing invented: a model
# writing `yes` has not written a boolean any JSON Schema consumer recognises.
_TRUE_STRINGS = frozenset({"true", "1"})
_FALSE_STRINGS = frozenset({"false", "0"})


def _declared_types(schema: JsonSchema | None) -> frozenset[str]:
    """Return the ``type`` keywords a property schema declares."""
    declared = schema.get("type") if schema is not None else None
    if isinstance(declared, str):
        return frozenset({declared})
    if isinstance(declared, list):
        return frozenset(item for item in declared if isinstance(item, str))
    return frozenset()


def _coerce_scalar(value: object, types: frozenset[str]) -> object:
    """Read a string-encoded scalar as the type the schema declares, or leave it."""
    if not isinstance(value, str) or "string" in types:
        return value
    text = value.strip()
    if "integer" in types:
        try:
            return int(text)
        except ValueError:
            return value
    if "number" in types:
        try:
            number = int(text) if text.lstrip("+-").isdigit() else float(text)
        except ValueError:
            return value
        # `inf`/`nan` satisfy jsonschema's `number`, so coercing them would swap
        # a clean -32602 for an OverflowError inside the tool body. Only floats
        # can be non-finite, and asking `isfinite` about a wide `int` raises the
        # very OverflowError this guard exists to avoid — this runs outside the
        # `tools/call` try block, so it would escape as a 500 with no envelope.
        if isinstance(number, float) and not isfinite(number):
            return value
        return number
    if "boolean" in types:
        folded = text.casefold()
        if folded in _TRUE_STRINGS:
            return True
        if folded in _FALSE_STRINGS:
            return False
    return value


def _coerce_arguments(arguments: dict[str, Any], schema: JsonSchema) -> dict[str, Any]:
    """Absorb the loosely-typed scalars models routinely send.

    Around 37 tool bodies call ``int(params[...])`` / ``bool(params[...])``
    against schemas declaring ``number`` / ``boolean`` precisely because models
    send them as strings — ``.github/workflows/mergecraft.yml`` instructs the
    agent to call ``get_check_suite_logs`` with a bare number quoted in prose,
    which arrives JSON-encoded as a string often enough to matter. Rejecting
    those at the boundary turns a tolerated shape into a hard ``-32602`` and
    silently degrades CI-log grounding, so they are coerced here instead and
    the typed value is what the tool receives.

    Only top-level scalars whose declared type they can actually satisfy are
    touched, and a union that already admits ``string`` is left alone. A value
    that cannot be read as the declared type falls through unchanged and is
    still reported as the schema violation it is.

    The ~38 in-body casts this makes redundant are not deleted yet; why, and in
    what order they can go, is under "Deferred designs the review rounds
    declined" in ``docs/test-plans/open-issues-sweep-2026-08-19.md``.
    """
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return arguments
    coerced = dict(arguments)
    for key, value in arguments.items():
        declared = properties.get(key)
        types = _declared_types(declared if isinstance(declared, dict) else None)
        if types:
            coerced[key] = _coerce_scalar(value, types)
    return coerced


def _argument_schema_error(
    tool: ToolSpec,
    arguments: dict[str, Any],
    cache: dict[str, Validator],
) -> RpcError | None:
    """Check ``arguments`` against ``tool.input_schema``; return an error or ``None``.

    A schema the validator cannot compile is the tool's defect, not the caller's:
    ``set_output`` adopts a consumer-supplied schema verbatim, so an unusable one
    is reachable in production. That case fails closed as ``-32603`` rather than
    mislabelling perfectly good arguments as ``-32602``.
    """
    validator = cache.get(tool.name)
    if validator is None:
        validator_cls = validator_for(tool.input_schema)
        try:
            validator_cls.check_schema(tool.input_schema)
        except SchemaError as exc:
            return RpcError(
                -32603, f"tool {tool.name} declares an invalid input schema: {exc.message}"
            )
        validator = validator_cls(tool.input_schema)
        cache[tool.name] = validator
    error = best_match(validator.iter_errors(arguments))
    if error is None:
        return None
    return RpcError(
        -32602, f"invalid arguments for {tool.name} at {error.json_path}: {error.message}"
    )


def _register_mcp_route(
    app: FastAPI,
    path: str,
    tools: list[ToolSpec],
    tool_ctx: ToolContext | None,
) -> None:
    """Mount one JSON-RPC MCP endpoint with a fixed tool surface."""
    by_name = {t.name: t for t in tools}
    validators: dict[str, Validator] = {}

    async def handle_rpc(body: dict[str, Any], *, agent_id: str | None = None) -> dict[str, Any]:
        req_id = body.get("id")
        method = body.get("method")
        params = body.get("params") or {}
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": MERGECRAFT_MCP_NAME, "version": "0.1.0"},
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
                return _rpc_error(req_id, RpcError(-32602, "tools/call requires string name"))
            if not isinstance(arguments, dict):
                arguments = {}
            tool = by_name.get(name)
            if tool is None:
                return _rpc_error(req_id, RpcError(-32601, f"Unknown tool: {name}"))
            arguments = _coerce_arguments(arguments, tool.input_schema)
            # Validate before charging: a call rejected here never ran, so it
            # costs no tool call — otherwise a schema mismatch the agent keeps
            # retrying burns the run budget with nothing executed. It is still
            # recorded on the trajectory, which is the only place the rejection
            # would otherwise be visible.
            schema_error = _argument_schema_error(tool, arguments, validators)
            if schema_error is not None:
                _record_trajectory(tool_ctx, name, arguments, ok=False, error=schema_error.message)
                return _rpc_error(req_id, schema_error)
            try:
                from mergecraft.utils.run_bounds import BudgetExhausted

                _charge_tool_call_budget(tool_ctx)
            except BudgetExhausted as exc:
                return _rpc_error(req_id, RpcError(-32000, str(exc)))
            from mergecraft.config.settings import RepoSettings

            tracer = get_tracer_from_settings(RepoSettings())
            call_attrs: dict[str, Any] = {
                "tool.name": name,
                "tool.server": MERGECRAFT_MCP_NAME,
                "gen_ai.operation.name": "execute_tool",
                "gen_ai.tool.name": name,
                "gen_ai.tool.call.id": _span_tool_call_id(),
            }
            # D10 (OB4) — per-agent attribution from the MCP side: the
            # dispatch-issued identity arrives as a request header (the
            # harness subprocess is uninstrumentable), so every tool.call
            # span carries the calling agent's id.
            if agent_id:
                call_attrs["mergecraft.agent.id"] = agent_id
            with tracer.start_span("tool.call", attrs_source=lambda: dict(call_attrs)) as _span:
                enrich_tool_request(_span, arguments=arguments)
                try:
                    result = await tool.execute(arguments)
                except Exception as exc:
                    _span.set_status("error", str(exc))
                    enrich_tool_response(_span, output=None, error=exc)
                    _record_trajectory(tool_ctx, name, arguments, ok=False, error=str(exc))
                    raise
                enrich_tool_response(_span, output=result)
                _record_trajectory(tool_ctx, name, arguments, ok=True, result=result)
                # T1 / D5 — known-verb tools also emit a verb-specific child
                # span (tool.browse for ``browser``, etc.) for finer-grained
                # Logfire grouping. Fire-and-forget; no new bookkeeping.
                emit_verb_subevent(
                    tracer,
                    parent_span_id=_span.span_id,
                    tool_name=name,
                    attrs=call_attrs,
                )
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": _tool_result_to_rpc(result),
                }
        return _rpc_error(req_id, RpcError(-32601, f"Method not found: {method}"))

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
            # No envelope helper here: a parse failure has no request id to echo,
            # so this response deliberately carries no ``id`` field at all.
            return JSONResponse(
                {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}},
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
            return JSONResponse(
                [await handle_rpc(item, agent_id=calling_agent_id) for item in items]
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
) -> FastAPI:
    """Build the MCP app.

    ``ctx`` is optional so a test can stand the app up with bare tool specs;
    when it is supplied — which is what ``start_mcp_http_server`` does on every
    real run — each ``tools/call`` is appended to the run's trajectory record.

    ``role_tools`` mounts extra class-filtered surfaces at ``{MCP_ENDPOINT}/{role}``
    (the reviewer lives at ``MCP_REVIEWER_ENDPOINT``, the verifier at
    ``MCP_VERIFIER_ENDPOINT``). The primary endpoint stays the orchestrator set.
    """
    app = FastAPI(title=MERGECRAFT_MCP_NAME, version="0.1.0")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    _register_mcp_route(app, MCP_ENDPOINT, tools, ctx)
    for role, role_tool_list in (role_tools or {}).items():
        _register_mcp_route(app, f"{MCP_ENDPOINT}/{role}", role_tool_list, ctx)
    return app


async def _kill_background_processes(ctx: ToolContext) -> None:
    procs = ctx.tool_state.background_processes
    if not procs:
        return
    pids = {proc.pid for proc in list(procs.values()) if isinstance(proc.pid, int)}
    # Off-loop: batch TERM -> one grace -> KILL (avoids N-times sleep on the event loop).
    await asyncio.to_thread(kill_process_groups, pids)
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
    reviewer_tools = build_reviewer_tools(ctx, output_schema)
    verifier_tools = build_verifier_tools(ctx, output_schema)
    app = create_mcp_app(
        tools,
        ctx,
        role_tools={"reviewer": reviewer_tools, "verifier": verifier_tools},
    )
    port = _select_port()
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
        except Exception as exc:
            logger.warning("background-process kill scheduling failed: {}", exc)
        server.should_exit = True
        thread.join(timeout=5)

    return url, stop
