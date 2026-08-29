"""``mergecraft agent`` — roster authoring for named agents (wave plan 11 / W3)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import typer
from rich.table import Table

from mergecraft.agents.registry import (
    AgentRole,
    RegistryValidationError,
    effective_agent_limits,
    load_registry,
    resolve_agent_model,
)
from mergecraft.cli.agents_cmd import (
    _tool_ctx,
    validate_agent_binding_override,
    validate_registered_model_slug,
)
from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.errors import cli_bail
from mergecraft.cli.provider_cmd import (
    _config_path,
    _load_config_dict,
    _write_config_dict,
)
from mergecraft.cli.target_dir import target_dir as resolve_target_dir
from mergecraft.config.agent_roster import (
    AgentRosterError,
    RosterEntry,
    add_model,
    assign_slot,
    load_roster,
    parse_slot,
    remove_slot,
)
from mergecraft.config.settings import load_repo_settings
from mergecraft.models import parse_model

_AGENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_SLOT_TOKEN_RE = re.compile(r"^p(\d+)$")
_REQUIRED_ROLES = frozenset({AgentRole.reviewer.value, AgentRole.verifier.value})

app = typer.Typer(
    name="agent",
    help="Author the committed agent roster and model priority chains.",
    no_args_is_help=True,
)


def _known_roles_message() -> str:
    return ", ".join(item.value for item in AgentRole)


def _validate_role(role: str) -> str:
    role_key = role.strip().lower()
    try:
        AgentRole(role_key)
    except ValueError:
        cli_bail(f"unknown role: {role!r} (expected one of: {_known_roles_message()})")
    return role_key


def _validate_agent_name(name: str) -> str:
    if not _AGENT_NAME_RE.match(name):
        cli_bail(f"invalid agent name {name!r}: must match pattern ^[a-z][a-z0-9_-]{{0,31}}$ (D11)")
    return name


def _effective_role(agent_name: str, entry: dict[str, Any]) -> str | None:
    role_value = entry.get("role")
    if role_value is not None:
        return str(role_value).lower()
    try:
        AgentRole(agent_name)
    except ValueError:
        return None
    return agent_name.lower()


def _load_agents_block(target_dir: Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    config_path = _config_path(target_dir)
    if not config_path.is_file():
        cli_bail(f"no config at {config_path} — run mergecraft init first")
    raw = _load_config_dict(config_path)
    agents = raw.setdefault("agents", {})
    if not isinstance(agents, dict):
        cli_bail("agents block must be a mapping")
    return config_path, raw, agents


def _agent_entry(agents: dict[str, Any], name: str) -> dict[str, Any]:
    entry = agents.get(name)
    if not isinstance(entry, dict):
        cli_bail(f"unknown agent {name!r}")
    return entry


def _model_chain_from_entry(entry: dict[str, Any]) -> list[str]:
    chain = entry.get("modelChain")
    if chain is None:
        return []
    if not isinstance(chain, list):
        cli_bail("modelChain must be a list")
    return [str(item) for item in chain]


def _validate_slug(data: dict[str, Any], slug: str) -> str:
    try:
        provider, model_id = parse_model(slug)
    except ValueError as exc:
        cli_bail(str(exc))
    return validate_registered_model_slug(data, provider, model_id)


def _persist_entry(
    config_path: Path,
    raw: dict[str, Any],
    agents: dict[str, Any],
    name: str,
    entry: dict[str, Any],
) -> None:
    validate_agent_binding_override(entry)
    agents[name] = entry
    try:
        load_roster(raw)
    except AgentRosterError as exc:
        cli_bail(str(exc))
    _write_config_dict(config_path, raw)


def _remove_entry(
    config_path: Path,
    raw: dict[str, Any],
    agents: dict[str, Any],
    name: str,
) -> None:
    agents.pop(name, None)
    try:
        load_roster(raw)
    except AgentRosterError as exc:
        cli_bail(str(exc))
    _write_config_dict(config_path, raw)


def _count_role_bindings(agents: dict[str, Any], role: str) -> int:
    count = 0
    for agent_name, entry in agents.items():
        if not isinstance(entry, dict):
            continue
        if _effective_role(agent_name, entry) == role:
            count += 1
    return count


def _orchestrator_exists(agents: dict[str, Any]) -> bool:
    return _count_role_bindings(agents, AgentRole.orchestrator.value) > 0


def _dispatch_levels(entries: tuple[RosterEntry, ...]) -> dict[str, int]:
    by_name = {entry.name: entry for entry in entries}
    levels: dict[str, int] = {}

    def level_for(name: str, visiting: set[str]) -> int:
        cached = levels.get(name)
        if cached is not None:
            return cached
        entry = by_name.get(name)
        if entry is None:
            return 0
        if entry.after is None:
            levels[name] = 0
            return 0
        if name in visiting:
            cycle = " -> ".join([*visiting, name])
            msg = f"after: cycle detected: {cycle}"
            raise AgentRosterError(msg)
        visiting.add(name)
        dep_level = level_for(entry.after, visiting)
        result = dep_level + 1
        levels[name] = result
        return result

    for entry in entries:
        level_for(entry.name, set())
    return levels


def _format_chain(chain: tuple[str, ...] | list[str]) -> str:
    if not chain:
        return "(empty)"
    return ", ".join(f"p{index} {slug}" for index, slug in enumerate(chain))


def _resolve_remove_index(chain: list[str], token: str) -> int:
    if _SLOT_TOKEN_RE.match(token):
        return parse_slot(token)
    if token in chain:
        return chain.index(token)
    cli_bail(f"model {token!r} is not in the chain (expected pN or a chain slug)")
    return -1  # unreachable — cli_bail exits


@app.command("list")
def list_cmd(
    cwd: Path = typer.Option(Path("."), "--cwd", help="Working directory."),
) -> None:
    """List every agent, role, model chain, and dispatch level."""
    target_dir = resolve_target_dir(cwd)
    config_path = _config_path(target_dir)
    if not config_path.is_file():
        cli_bail(f"no config at {config_path} — run mergecraft init first")
    raw = _load_config_dict(config_path)
    roster = load_roster(raw)
    levels = _dispatch_levels(roster.entries)

    table = Table(title="Agent roster")
    table.add_column("agent")
    table.add_column("role")
    table.add_column("dispatch level")
    table.add_column("model chain")
    for entry in roster.entries:
        role = entry.role or entry.name
        table.add_row(
            entry.name,
            role,
            str(levels.get(entry.name, 0)),
            _format_chain(entry.model_chain),
        )
    console.print(table)


@app.command("show")
def show_cmd(
    name: str = typer.Argument(..., help="Agent name (e.g. reviewer or reviewer2)."),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Working directory."),
) -> None:
    """Show one agent's chain, resolved model, and effective limits."""
    target_dir = resolve_target_dir(cwd)
    settings = load_repo_settings(root=target_dir)
    try:
        registry = load_registry(settings=settings, repo_root=target_dir)
        binding = registry.resolve_agent_ref(name)
    except (RegistryValidationError, KeyError) as exc:
        cli_bail(str(exc))

    resolved = resolve_agent_model(binding, settings=settings)
    limits = effective_agent_limits(binding, settings=settings)
    tools = registry.resolve_tool_names(binding, _tool_ctx(target_dir))

    console.print(f"[bold]{name}[/bold] (role={binding.role.value})")
    console.print(f"model chain: {_format_chain(binding.model_chain)}")
    console.print(
        f"resolved model: requested={resolved.requested_model} executed={resolved.executed_model}"
    )
    console.print(f"effective limits: budget={limits.budget} timeout_s={limits.timeout_s}")
    console.print(f"prompt: {binding.prompt_id} v{binding.prompt_version}")
    typer.echo("\n--- tools ---\n")
    for tool_name in sorted(tools):
        typer.echo(tool_name)


@app.command("create")
def create_cmd(
    name: str = typer.Argument(..., help="New agent name (D11 pattern)."),
    role: str = typer.Option(..., "--role", help="Agent role for the new binding."),
    after: str | None = typer.Option(
        None,
        "--after",
        help="Run after this agent finishes (D15); omit for parallel dispatch.",
    ),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Working directory."),
) -> None:
    """Create a new roster entry with role defaults."""
    agent_name = _validate_agent_name(name)
    role_key = _validate_role(role)
    target_dir = resolve_target_dir(cwd)
    config_path, raw, agents = _load_agents_block(target_dir)

    if agent_name in agents:
        cli_bail(f"agent {agent_name!r} already exists")

    if role_key == AgentRole.orchestrator.value:
        if agent_name != AgentRole.orchestrator.value:
            cli_bail("orchestrator role is reserved for the primary agents.orchestrator binding")
        if _orchestrator_exists(agents):
            cli_bail("cannot create a second orchestrator — orchestrator may not be duplicated")

    if after is not None:
        _validate_agent_name(after)
        if after not in agents:
            cli_bail(f"unknown after agent {after!r}")

    entry: dict[str, Any] = {"role": role_key}
    if after is not None:
        entry["after"] = after

    _persist_entry(config_path, raw, agents, agent_name, entry)
    console.print(f"[green]created agents.{agent_name}[/green]")


@app.command("delete")
def delete_cmd(
    name: str = typer.Argument(..., help="Agent name to remove."),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Working directory."),
) -> None:
    """Remove an agent binding (refuses the last required reviewer or verifier)."""
    agent_name = _validate_agent_name(name)
    target_dir = resolve_target_dir(cwd)
    config_path, raw, agents = _load_agents_block(target_dir)
    entry = _agent_entry(agents, agent_name)
    role = _effective_role(agent_name, entry)
    if role in _REQUIRED_ROLES and _count_role_bindings(agents, role) <= 1:
        cli_bail(f"cannot delete the last {role!r} binding — the pipeline requires at least one")

    _remove_entry(config_path, raw, agents, agent_name)
    console.print(f"[green]deleted agents.{agent_name}[/green]")


@app.command("assign-model")
def assign_model_cmd(
    name: str = typer.Argument(..., help="Agent name."),
    slot: str = typer.Argument(..., help="Priority slot (p0, p1, …)."),
    slug: str = typer.Argument(..., help="Registered provider/model slug."),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Working directory."),
) -> None:
    """Assign a registered model to a positional slot (idempotent, D4)."""
    agent_name = _validate_agent_name(name)
    target_dir = resolve_target_dir(cwd)
    config_path, raw, agents = _load_agents_block(target_dir)
    entry = _agent_entry(agents, agent_name)
    validated_slug = _validate_slug(raw, slug)

    try:
        index = parse_slot(slot)
        chain, message = assign_slot(_model_chain_from_entry(entry), index, validated_slug)
    except AgentRosterError as exc:
        cli_bail(str(exc))

    entry["modelChain"] = chain
    _persist_entry(config_path, raw, agents, agent_name, entry)
    console.print(f"[green]{message} on agents.{agent_name}[/green]")


@app.command("add-model")
def add_model_cmd(
    name: str = typer.Argument(..., help="Agent name."),
    slug: str = typer.Argument(..., help="Registered provider/model slug."),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Working directory."),
) -> None:
    """Append a registered model to an agent's chain (no-op when duplicate, D4)."""
    agent_name = _validate_agent_name(name)
    target_dir = resolve_target_dir(cwd)
    config_path, raw, agents = _load_agents_block(target_dir)
    entry = _agent_entry(agents, agent_name)
    validated_slug = _validate_slug(raw, slug)
    chain, was_duplicate = add_model(_model_chain_from_entry(entry), validated_slug)
    if was_duplicate:
        console.print(f"model {validated_slug!r} is already in the chain for agents.{agent_name}")
        return

    entry["modelChain"] = chain
    _persist_entry(config_path, raw, agents, agent_name, entry)
    console.print(f"[green]appended {validated_slug!r} to agents.{agent_name}[/green]")


@app.command("remove-model")
def remove_model_cmd(
    name: str = typer.Argument(..., help="Agent name."),
    token: str = typer.Argument(..., help="Slot (pN) or model slug to remove."),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Working directory."),
) -> None:
    """Remove a model slot and compact the chain."""
    agent_name = _validate_agent_name(name)
    target_dir = resolve_target_dir(cwd)
    config_path, raw, agents = _load_agents_block(target_dir)
    entry = _agent_entry(agents, agent_name)
    chain = _model_chain_from_entry(entry)
    try:
        index = _resolve_remove_index(chain, token)
        updated = remove_slot(chain, index)
    except AgentRosterError as exc:
        cli_bail(str(exc))

    entry["modelChain"] = updated
    _persist_entry(config_path, raw, agents, agent_name, entry)
    console.print(f"[green]removed {token!r} from agents.{agent_name}[/green]")


@app.command("set-after")
def set_after_cmd(
    name: str = typer.Argument(..., help="Agent name."),
    after: str = typer.Argument(
        ...,
        help="Agent to run after, or --none to clear sequencing.",
    ),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Working directory."),
) -> None:
    """Change dispatch ordering after agent creation (D15)."""
    agent_name = _validate_agent_name(name)
    target_dir = resolve_target_dir(cwd)
    config_path, raw, agents = _load_agents_block(target_dir)
    entry = _agent_entry(agents, agent_name)

    if after == "--none":
        entry.pop("after", None)
    else:
        after_name = _validate_agent_name(after)
        if after_name not in agents:
            cli_bail(f"unknown after agent {after_name!r}")
        entry["after"] = after_name

    _persist_entry(config_path, raw, agents, agent_name, entry)
    if after == "--none":
        console.print(f"[green]cleared after: on agents.{agent_name}[/green]")
    else:
        console.print(f"[green]set agents.{agent_name}.after to {after!r}[/green]")


__all__ = ["app"]
