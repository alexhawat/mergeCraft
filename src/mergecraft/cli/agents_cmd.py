"""``mergecraft agents`` — registry inspection and per-agent overrides (AP1)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
from rich.table import Table

from mergecraft.agents.registry import (
    AgentRole,
    RegistryValidationError,
    load_registry,
    resolve_prompt_text,
)
from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.errors import cli_bail
from mergecraft.cli.model_cmd import (
    _find_provider_index,
    _model_id_from_row,
    _model_rows,
    _registered_labels,
    _unknown_provider_message,
)
from mergecraft.cli.provider_cmd import (
    _config_path,
    _load_config_dict,
    _provider_entries,
)
from mergecraft.cli.target_dir import target_dir as resolve_target_dir
from mergecraft.config.agent_roster import model_chain_from_entry
from mergecraft.config.io import write_config_dict
from mergecraft.config.model_registry import normalize_model_id
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


def _tool_ctx(target_dir: Path) -> ToolContext:
    state = init_tool_state(owner="acme", name="demo", dir=str(target_dir))
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
        tmpdir=str(target_dir),
        signed_commits=True,
        xrepo=XrepoConfig(mode="explicit", read=[], write=[]),
        static_checks_enabled=True,
    )


def _known_roles_message() -> str:
    return ", ".join(item.value for item in AgentRole)


def _validate_role_key(role: str) -> str:
    role_key = role.strip().lower()
    try:
        AgentRole(role_key)
    except ValueError:
        cli_bail(f"unknown role: {role!r} (expected one of: {_known_roles_message()})")
    return role_key


def _replace_primary_in_entry(entry: dict[str, Any], new_primary: str) -> None:
    chain = model_chain_from_entry(entry)
    if chain:
        entry["modelChain"] = [new_primary, *chain[1:]]
    else:
        entry["modelChain"] = [new_primary]


def format_model_slug(provider_label: str, model_id: str) -> str:
    """Return ``provider/model`` slug for agent ``modelChain`` entries (#480)."""
    return f"{provider_label.strip().lower()}/{model_id}"


def validate_registered_model_slug(
    data: dict[str, Any],
    provider_label: str,
    model_id: str,
) -> str:
    """Validate *provider_label* / *model_id* against the operator registry (#480)."""
    entries = _provider_entries(data)
    labels = _registered_labels(entries)
    provider_label = provider_label.strip()
    provider_idx = _find_provider_index(entries, provider_label)
    if provider_idx is None:
        cli_bail(_unknown_provider_message(provider_label, labels))

    entry = entries[provider_idx]
    provider_name = str(entry.get("label", provider_label))
    normalised_id = normalize_model_id(provider_name, model_id)
    if not normalised_id:
        cli_bail("model id must not be empty")

    for row in _model_rows(entry):
        if _model_id_from_row(row) == normalised_id:
            return format_model_slug(provider_name, normalised_id)

    msg = (
        f"unregistered model {normalised_id!r} on provider {provider_name!r} — "
        "run mergecraft model add first"
    )
    cli_bail(msg)
    return ""  # unreachable — cli_bail exits


def validate_agent_binding_override(entry: dict[str, Any]) -> AgentBindingOverride:
    """Round-trip *entry* through Pydantic before persisting agent overrides."""
    return AgentBindingOverride.model_validate(entry)


def _load_agents_block(config_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    if not config_path.is_file():
        cli_bail(f"no config at {config_path} — run mergecraft init first")
    raw = _load_config_dict(config_path)
    agents = raw.setdefault("agents", {})
    if not isinstance(agents, dict):
        cli_bail("agents block must be a mapping")
    return raw, agents


def _agent_entry(agents: dict[str, Any], role_key: str) -> dict[str, Any]:
    entry = agents.setdefault(role_key, {})
    if not isinstance(entry, dict):
        cli_bail(f"agents.{role_key} must be a mapping")
    return entry


@app.command("list")
def list_cmd(
    cwd: Path = typer.Option(Path("."), "--cwd", help="Working directory."),
) -> None:
    """List agent bindings with model chain, prompt id, and tool count."""
    target_dir = resolve_target_dir(cwd)
    settings = load_repo_settings(root=target_dir)
    try:
        registry = load_registry(settings=settings, repo_root=target_dir)
    except RegistryValidationError as exc:
        cli_bail(str(exc))
    ctx = _tool_ctx(target_dir)

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
    cwd: Path = typer.Option(Path("."), "--cwd", help="Working directory."),
) -> None:
    """Show resolved prompt text and MCP tool names for one role."""
    target_dir = resolve_target_dir(cwd)
    try:
        AgentRole(role)
    except ValueError:
        cli_bail(f"unknown role: {role!r}")

    settings = load_repo_settings(root=target_dir)
    try:
        registry = load_registry(settings=settings, repo_root=target_dir)
        binding = registry.resolve_role(role)
    except RegistryValidationError as exc:
        cli_bail(str(exc))
    except KeyError:
        cli_bail(f"unknown role: {role!r}")

    prompt = resolve_prompt_text(binding.prompt_id, version=binding.prompt_version)
    tools = registry.resolve_tool_names(binding, _tool_ctx(target_dir))

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
    cwd: Path = typer.Option(Path("."), "--cwd", help="Working directory."),
) -> None:
    """Write a single agent binding override into ``.mergecraft/config.yaml``."""
    if model is None:
        cli_bail("pass at least one override flag (e.g. --model)")

    role_key = _validate_role_key(role)
    target_dir = resolve_target_dir(cwd)
    config_path = _config_path(target_dir)
    raw, agents = _load_agents_block(config_path)
    entry = _agent_entry(agents, role_key)

    if model is not None:
        _replace_primary_in_entry(entry, model)

    validate_agent_binding_override(entry)
    write_config_dict(config_path, raw)
    console.print(f"[green]updated agents.{role_key} in {config_path}[/green]")


__all__ = [
    "app",
    "format_model_slug",
    "validate_agent_binding_override",
    "validate_registered_model_slug",
]
