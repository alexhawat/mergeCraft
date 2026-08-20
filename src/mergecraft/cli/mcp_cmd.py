"""``mergecraft mcp`` — expose the MCP tool server for external clients (CC4)."""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import typer
import uvicorn
from rich.console import Console

from mergecraft.cli.mcp_serve import (
    _role_endpoint,
    build_mcp_app_from_ctx,
    build_mcp_tool_context,
    resolve_served_tool_names,
)
from mergecraft.cli.profiles import apply_profile_env, resolve_profile
from mergecraft.config.settings import parse_cli_trust_override
from mergecraft.mcp.ports import MCP_HOST, read_env_port, select_port

app = typer.Typer(
    name="mcp",
    help="Serve mergeCraft MCP tools to external clients.",
    no_args_is_help=True,
)
console = Console()
stderr_console = Console(stderr=True)


def _bail(msg: str) -> NoReturn:
    console.print(f"[red]{msg}[/red]")
    raise typer.Exit(1)


@app.command("list")
def list_cmd(
    role: str = typer.Option(
        "reviewer",
        "--role",
        "-r",
        help="Agent role whose tool surface to print (orchestrator, reviewer, verifier).",
    ),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository workspace root."),
    trust: str | None = typer.Option(
        None,
        "--trust",
        help="Explicit trust-tier override (trusted or untrusted).",
    ),
    profile: str | None = typer.Option(
        None,
        "--profile",
        help="Named profile bundle (fast, deep, security).",
    ),
) -> None:
    """Print the resolved MCP tool names for a role."""
    try:
        resolve_profile(profile)
    except ValueError as exc:
        _bail(str(exc))
    try:
        parse_cli_trust_override(trust)
    except ValueError as exc:
        _bail(str(exc))

    with apply_profile_env(resolve_profile(profile)):
        try:
            names = resolve_served_tool_names(
                cwd=cwd,
                role=role,
                trust_override=trust,
            )
        except ValueError as exc:
            _bail(str(exc))

    for name in sorted(names):
        typer.echo(name)


@app.command("serve")
def serve_cmd(
    role: str = typer.Option(
        "reviewer",
        "--role",
        "-r",
        help="Primary role endpoint to advertise (orchestrator, reviewer, verifier).",
    ),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository workspace root."),
    host: str = typer.Option(MCP_HOST, "--host", help="Bind address."),
    port: int | None = typer.Option(
        None,
        "--port",
        "-p",
        help="Listen port (default: MERGECRAFT_MCP_PORT or ephemeral).",
    ),
    trust: str | None = typer.Option(
        None,
        "--trust",
        help="Explicit trust-tier override (trusted or untrusted).",
    ),
    profile: str | None = typer.Option(
        None,
        "--profile",
        help="Named profile bundle (fast, deep, security).",
    ),
) -> None:
    """Start the MCP HTTP server for a resolved workspace and role."""
    try:
        bundle = resolve_profile(profile)
    except ValueError as exc:
        _bail(str(exc))
    try:
        parse_cli_trust_override(trust)
    except ValueError as exc:
        _bail(str(exc))

    with apply_profile_env(bundle):
        try:
            ctx = build_mcp_tool_context(cwd=cwd, trust_override=trust)
            fastapi_app = build_mcp_app_from_ctx(role, ctx)
        except ValueError as exc:
            _bail(str(exc))

        # D9 — print the per-serve Bearer token to stderr so the caller can pin it.
        stderr_console.print(f"MERGECRAFT_MCP_BEARER={ctx.mcp_auth_token}")

        listen_port = port if port is not None else read_env_port() or select_port()
        endpoint = _role_endpoint(
            role.strip().lower()  # type: ignore[arg-type]  # — role.strip().lower() is str; callee expects Literal["orchestrator","reviewer","verifier"]
            if role.strip().lower() in {"orchestrator", "reviewer", "verifier"}
            else "reviewer"
        )
        auth_token = getattr(fastapi_app.state, "mcp_auth_token", None)
        console.print(
            f"[green]MCP server listening on http://{host}:{listen_port}{endpoint}[/green]"
        )
        if isinstance(auth_token, str) and auth_token:
            console.print(
                f"[dim]Authenticated requests require Authorization: Bearer {auth_token}[/dim]"
            )
        config = uvicorn.Config(
            fastapi_app,
            host=host,
            port=listen_port,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(config)
        server.run()
