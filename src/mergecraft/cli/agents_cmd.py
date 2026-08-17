"""``mergecraft agents`` — registry inspection and per-agent overrides (AP1)."""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import typer
import yaml
from rich.console import Console
from rich.table import Table

from mergecraft.agents.registry import (
    AgentRole,
    RegistryValidationError,
    load_registry,
    resolve_prompt_text,
)
from mergecraft.config.settings import AgentBindingOverride, load_repo_settings
from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.types import XrepoConfig
from mergecraft.utils.github import GitHubClient

app = typer.Typer(
    name="agents",
    help="Inspect and override the mergeCraft agent registry.",
    no_args_is_help=True,
)
console = Console()


def _bail(msg: str) -> NoReturn:
    console.print(f"[red]{msg}[/red]")
    raise typer.Exit(1)


def _repo_root(cwd: Path) -> Path:
    return cwd.resolve()


def _tool_ctx(repo_root: Path) -> ToolContext:
    state = init_tool_state(owner="acme", name="demo", dir=str(repo_root))
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="unknown"),
            shell="restricted",
            push="restricted",
        ),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(repo_root),
        signed_commits=True,
        xrepo=XrepoConfig(mode="explicit", read=[], write=[]),
        static_checks_enabled=True,
    )


@app.command("list")
def list_cmd(
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root."),
) -> None:
    """List agent bindings with model chain, prompt id, and tool count."""
    repo_root = _repo_root(cwd)
    settings = load_repo_settings(root=repo_root)
    try:
        registry = load_registry(settings=settings, repo_root=repo_root)
    except RegistryValidationError as exc:
        _bail(str(exc))
    ctx = _tool_ctx(repo_root)

    table = Table(title="Agent registry")
    table.add_column("role")
    table.add_column("model chain")
    table.add_column("prompt")
    table.add_column("tools")
    for binding in sorted(registry.all_bindings(), key=lambda b: b.role.value):
        if binding.lens is not None:
            continue
        chain = ", ".join(binding.model_chain[:2])
        if len(binding.model_chain) > 2:
            chain += ", …"
        tool_count = len(registry.resolve_tool_names(binding, ctx))
        table.add_row(
            binding.role.value,
            chain,
            binding.prompt_id,
            str(tool_count),
        )
    console.print(table)


@app.command("show")
def show_cmd(
    role: str = typer.Argument(..., help="Agent role (e.g. reviewer)."),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root."),
) -> None:
    """Show resolved prompt text and MCP tool names for one role."""
    repo_root = _repo_root(cwd)
    try:
        AgentRole(role)
    except ValueError:
        _bail(f"unknown role: {role!r}")

    settings = load_repo_settings(root=repo_root)
    try:
        registry = load_registry(settings=settings, repo_root=repo_root)
        binding = registry.resolve_role(role)
    except RegistryValidationError as exc:
        _bail(str(exc))
    except KeyError:
        _bail(f"unknown role: {role!r}")

    prompt = resolve_prompt_text(binding.prompt_id, version=binding.prompt_version)
    tools = registry.resolve_tool_names(binding, _tool_ctx(repo_root))

    console.print(f"[bold]{binding.role.value}[/bold] ({binding.agent_id})")
    console.print(f"model chain: {', '.join(binding.model_chain)}")
    console.print(f"prompt: {binding.prompt_id} v{binding.prompt_version}")
    if prompt:
        typer.echo("\n--- prompt ---\n")
        typer.echo(prompt)
    typer.echo("\n--- tools ---\n")
    for name in sorted(tools):
        typer.echo(name)


@app.command("set")
def set_cmd(
    role: str = typer.Argument(..., help="Agent role to override."),
    model: str | None = typer.Option(None, "--model", help="Primary model slug override."),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root."),
) -> None:
    """Write a single agent binding override into ``.mergecraft/config.yaml``."""
    if model is None:
        _bail("pass at least one override flag (e.g. --model)")

    role_key = role.lower()
    try:
        AgentRole(role_key)
    except ValueError:
        known = ", ".join(item.value for item in AgentRole)
        _bail(f"unknown role: {role!r} (expected one of: {known})")

    repo_root = _repo_root(cwd)
    config_path = repo_root / ".mergecraft" / "config.yaml"
    if not config_path.is_file():
        _bail(f"no config at {config_path} — run mergecraft init first")

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        _bail(f"config must be a mapping: {config_path}")

    agents = raw.setdefault("agents", {})
    if not isinstance(agents, dict):
        _bail("agents block must be a mapping")

    entry = agents.setdefault(role_key, {})
    if not isinstance(entry, dict):
        _bail(f"agents.{role_key} must be a mapping")

    if model is not None:
        entry["modelChain"] = [model]

    # Validate the override round-trips through Pydantic before writing.
    AgentBindingOverride.model_validate(entry)
    config_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    console.print(f"[green]updated agents.{role_key} in {config_path}[/green]")
