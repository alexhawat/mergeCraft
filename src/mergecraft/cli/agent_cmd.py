"""``mergecraft agent`` — roster authoring for named agents (wave plan 11 / W3+W4)."""

from __future__ import annotations

import re
from enum import StrEnum
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
from mergecraft.cli.config_precedence import (
    committed_config_path,
    load_layered_config_dict,
    local_config_path,
    merge_config_dicts,
)
from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.errors import cli_bail
from mergecraft.cli.init_cmd import _ensure_gitignore_line
from mergecraft.cli.provider_cmd import (
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
from mergecraft.config.io import config_path_for_root, load_config_dict
from mergecraft.config.roster_graph import AfterEdge, dispatch_levels
from mergecraft.config.settings import load_repo_settings
from mergecraft.models import parse_model
from mergecraft.workflow.auth_manifest import (
    DEFAULT_WORKFLOW_RELATIVE_PATH,
    WorkflowAuthManifestError,
    parse_auth_manifest,
)

_AGENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_REQUIRED_ROLES = frozenset({AgentRole.reviewer.value, AgentRole.verifier.value})
_LOCAL_CONFIG_GITIGNORE_LINE = ".mergecraft/config.local.yaml"


class AgentRosterTarget(StrEnum):
    """Which on-disk config file roster authoring commands mutate."""

    COMMITTED = "committed"
    LOCAL = "local"


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


def _scope_config_path(target_dir: Path, target: AgentRosterTarget) -> Path:
    if target == AgentRosterTarget.COMMITTED:
        return config_path_for_root(target_dir)
    return local_config_path(target_dir)


def _ensure_committed_config(target_dir: Path) -> Path:
    config_path = config_path_for_root(target_dir)
    if not config_path.is_file():
        cli_bail(f"no config at {config_path} — run mergecraft init first")
    return config_path


def _ensure_local_gitignore(target_dir: Path) -> None:
    _ensure_gitignore_line(target_dir, _LOCAL_CONFIG_GITIGNORE_LINE)


def _load_scope_raw(target_dir: Path, target: AgentRosterTarget) -> tuple[Path, dict[str, Any]]:
    _ensure_committed_config(target_dir)
    config_path = _scope_config_path(target_dir, target)
    if target == AgentRosterTarget.LOCAL:
        _ensure_local_gitignore(target_dir)
        raw = load_config_dict(config_path) if config_path.is_file() else {}
    else:
        raw = load_config_dict(config_path)
    return config_path, raw


def _load_agents_block(
    target_dir: Path, target: AgentRosterTarget
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    config_path, raw = _load_scope_raw(target_dir, target)
    agents = raw.setdefault("agents", {})
    if not isinstance(agents, dict):
        cli_bail("agents block must be a mapping")
    return config_path, raw, agents


def _merged_raw_for_validation(target_dir: Path, scope_raw: dict[str, Any]) -> dict[str, Any]:
    committed = load_config_dict(config_path_for_root(target_dir))
    return merge_config_dicts(committed, scope_raw)


def _is_role_named_agent(name: str) -> bool:
    try:
        AgentRole(name)
    except ValueError:
        return False
    return True


def _agent_entry(
    agents: dict[str, Any],
    name: str,
    *,
    target: AgentRosterTarget,
    create_if_missing: bool = False,
) -> dict[str, Any]:
    entry = agents.get(name)
    if isinstance(entry, dict):
        return entry
    if create_if_missing or target == AgentRosterTarget.LOCAL:
        created: dict[str, Any] = {}
        agents[name] = created
        return created
    cli_bail(f"unknown agent {name!r}")
    return {}  # unreachable — cli_bail exits


def _model_chain_from_entry(entry: dict[str, Any]) -> list[str]:
    chain = entry.get("modelChain")
    if chain is None:
        return []
    if not isinstance(chain, list):
        cli_bail("modelChain must be a list")
    return [str(item) for item in chain]


def _validate_slug(
    target_dir: Path,
    target: AgentRosterTarget,
    raw: dict[str, Any],
    slug: str,
) -> str:
    try:
        provider, model_id = parse_model(slug)
    except ValueError as exc:
        cli_bail(str(exc))
    validation_raw = (
        _merged_raw_for_validation(target_dir, raw) if target == AgentRosterTarget.LOCAL else raw
    )
    models = validation_raw.get("models")
    if isinstance(models, list) and slug in [str(item) for item in models]:
        return slug
    return validate_registered_model_slug(validation_raw, provider, model_id)


def _ensure_provider_wired_in_workflow(
    target_dir: Path,
    target: AgentRosterTarget,
    slug: str,
    *,
    allow_unwired: bool,
) -> None:
    if target == AgentRosterTarget.LOCAL:
        return
    provider, _model_id = parse_model(slug)
    workflow_path = target_dir / DEFAULT_WORKFLOW_RELATIVE_PATH
    if not workflow_path.is_file():
        cli_bail(
            f"provider {provider!r} is not wired in mergecraft.yml — no workflow at "
            f"{workflow_path}; run [cyan]mergecraft workflow provider add --label {provider}[/cyan] "
            "or choose a different model"
        )
    wired = _wired_providers_from_workflow(workflow_path)
    if provider.lower() in wired:
        return
    if allow_unwired:
        console.print(
            f"[yellow]warning:[/yellow] provider {provider!r} has no credential step in "
            f"mergecraft.yml — roster saved, but CI will fail until you run "
            f"[cyan]mergecraft workflow sync --apply[/cyan] or "
            f"[cyan]mergecraft workflow provider add --label {provider}[/cyan]"
        )
        return
    cli_bail(
        f"provider {provider!r} has no credential step in mergecraft.yml — wire it with "
        f"[cyan]mergecraft workflow provider add --label {provider}[/cyan] or choose a different model"
    )


def _persist_entry(
    target_dir: Path,
    target: AgentRosterTarget,
    config_path: Path,
    raw: dict[str, Any],
    agents: dict[str, Any],
    name: str,
    entry: dict[str, Any],
) -> None:
    validate_agent_binding_override(entry)
    agents[name] = entry
    validation_raw = (
        _merged_raw_for_validation(target_dir, raw) if target == AgentRosterTarget.LOCAL else raw
    )
    try:
        load_roster(validation_raw)
    except AgentRosterError as exc:
        cli_bail(str(exc))
    _write_config_dict(config_path, raw)


def _remove_entry(
    target_dir: Path,
    target: AgentRosterTarget,
    config_path: Path,
    raw: dict[str, Any],
    agents: dict[str, Any],
    name: str,
) -> None:
    agents.pop(name, None)
    validation_raw = (
        _merged_raw_for_validation(target_dir, raw) if target == AgentRosterTarget.LOCAL else raw
    )
    try:
        load_roster(validation_raw)
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


def _wired_providers_from_workflow(workflow_path: Path) -> frozenset[str]:
    try:
        return parse_auth_manifest(workflow_path)
    except WorkflowAuthManifestError as exc:
        cli_bail(str(exc))
    return frozenset()  # unreachable — cli_bail exits


def _dispatch_levels(entries: tuple[RosterEntry, ...]) -> dict[str, int]:
    return dispatch_levels(
        tuple(AfterEdge(name=entry.name, after=entry.after) for entry in entries)
    )


def _local_override_slot_indices(
    agent_name: str,
    merged_chain: tuple[str, ...],
    *,
    committed_raw: dict[str, Any],
    local_raw: dict[str, Any],
) -> set[int]:
    committed_agents = committed_raw.get("agents")
    local_agents = local_raw.get("agents")
    if not isinstance(committed_agents, dict):
        committed_agents = {}
    if not isinstance(local_agents, dict):
        local_agents = {}
    local_entry = local_agents.get(agent_name)
    if not isinstance(local_entry, dict):
        return set()
    if agent_name not in committed_agents:
        return set(range(len(merged_chain)))
    if "modelChain" not in local_entry:
        return set()
    committed_entry = committed_agents.get(agent_name)
    committed_chain: list[str] = []
    if isinstance(committed_entry, dict):
        committed_chain = _model_chain_from_entry(committed_entry)
    indices: set[int] = set()
    for index, slug in enumerate(merged_chain):
        if index >= len(committed_chain) or committed_chain[index] != slug:
            indices.add(index)
    return indices


def _format_chain(
    chain: tuple[str, ...] | list[str],
    *,
    local_slots: set[int] | None = None,
) -> str:
    if not chain:
        return "(empty)"
    parts: list[str] = []
    for index, slug in enumerate(chain):
        label = f"p{index} {slug}"
        if local_slots and index in local_slots:
            label = f"{label} (local)"
        parts.append(label)
    return ", ".join(parts)


def _resolve_remove_index(chain: list[str], token: str) -> int:
    try:
        return parse_slot(token)
    except AgentRosterError:
        pass
    if token in chain:
        return chain.index(token)
    cli_bail(f"model {token!r} is not in the chain (expected pN or a chain slug)")
    return -1  # unreachable — cli_bail exits


def create_agent_app(*, target: AgentRosterTarget) -> typer.Typer:
    """Build the ``agent`` or ``agent-local`` Typer app for *target* scope."""
    help_suffix = (
        "Author the committed agent roster and model priority chains."
        if target == AgentRosterTarget.COMMITTED
        else "Author local-only agent roster overrides (gitignored, not read in CI)."
    )
    roster_app = typer.Typer(
        name="agent-local" if target == AgentRosterTarget.LOCAL else "agent",
        help=help_suffix,
        no_args_is_help=True,
    )

    @roster_app.command("list")
    def list_cmd(
        cwd: Path = typer.Option(Path("."), "--cwd", help="Working directory."),
    ) -> None:
        """List every agent, role, model chain, and dispatch level."""
        target_dir = resolve_target_dir(cwd)
        _ensure_committed_config(target_dir)
        merged_raw = load_layered_config_dict(root=target_dir)
        roster = load_roster(merged_raw)
        levels = _dispatch_levels(roster.entries)
        committed_raw = load_config_dict(committed_config_path(target_dir))
        local_raw = load_config_dict(local_config_path(target_dir))

        table = Table(title="Agent roster")
        table.add_column("agent")
        table.add_column("role")
        table.add_column("dispatch level")
        table.add_column("model chain")
        for entry in roster.entries:
            role = entry.role or entry.name
            local_slots = _local_override_slot_indices(
                entry.name,
                entry.model_chain,
                committed_raw=committed_raw,
                local_raw=local_raw,
            )
            table.add_row(
                entry.name,
                role,
                str(levels.get(entry.name, 0)),
                _format_chain(entry.model_chain, local_slots=local_slots),
            )
        console.print(table)

    @roster_app.command("show")
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

    @roster_app.command("create")
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
        config_path, raw, agents = _load_agents_block(target_dir, target)
        merged_agents = (
            _merged_raw_for_validation(target_dir, raw).get("agents", {})
            if target == AgentRosterTarget.LOCAL
            else agents
        )
        if not isinstance(merged_agents, dict):
            merged_agents = {}

        if agent_name in agents or agent_name in merged_agents:
            cli_bail(f"agent {agent_name!r} already exists")

        if role_key == AgentRole.orchestrator.value:
            if agent_name != AgentRole.orchestrator.value:
                cli_bail(
                    "orchestrator role is reserved for the primary agents.orchestrator binding"
                )
            if _orchestrator_exists(merged_agents):
                cli_bail("cannot create a second orchestrator — orchestrator may not be duplicated")

        if after is not None:
            _validate_agent_name(after)
            if after not in merged_agents:
                cli_bail(f"unknown after agent {after!r}")

        entry: dict[str, Any] = {"role": role_key}
        if after is not None:
            entry["after"] = after

        _persist_entry(target_dir, target, config_path, raw, agents, agent_name, entry)
        console.print(f"[green]created agents.{agent_name}[/green]")

    @roster_app.command("delete")
    def delete_cmd(
        name: str = typer.Argument(..., help="Agent name to remove."),
        cwd: Path = typer.Option(Path("."), "--cwd", help="Working directory."),
    ) -> None:
        """Remove an agent binding (refuses the last required reviewer or verifier)."""
        agent_name = _validate_agent_name(name)
        target_dir = resolve_target_dir(cwd)
        config_path, raw, agents = _load_agents_block(target_dir, target)
        merged_agents = _merged_raw_for_validation(target_dir, raw).get("agents", agents)
        if not isinstance(merged_agents, dict):
            merged_agents = agents
        entry = _agent_entry(agents, agent_name, target=target)
        role = _effective_role(agent_name, entry)
        if role in _REQUIRED_ROLES and _count_role_bindings(merged_agents, role) <= 1:
            cli_bail(
                f"cannot delete the last {role!r} binding — the pipeline requires at least one"
            )

        _remove_entry(target_dir, target, config_path, raw, agents, agent_name)
        console.print(f"[green]deleted agents.{agent_name}[/green]")

    @roster_app.command("assign-model")
    def assign_model_cmd(
        name: str = typer.Argument(..., help="Agent name."),
        slot: str = typer.Argument(..., help="Priority slot (p0, p1, …)."),
        slug: str = typer.Argument(..., help="Registered provider/model slug."),
        allow_unwired: bool = typer.Option(
            False,
            "--allow-unwired",
            help="Permit assigning a provider that is not wired into mergecraft.yml (warns).",
        ),
        cwd: Path = typer.Option(Path("."), "--cwd", help="Working directory."),
    ) -> None:
        """Assign a registered model to a positional slot (idempotent, D4)."""
        agent_name = _validate_agent_name(name)
        target_dir = resolve_target_dir(cwd)
        config_path, raw, agents = _load_agents_block(target_dir, target)
        entry = _agent_entry(
            agents,
            agent_name,
            target=target,
            create_if_missing=target == AgentRosterTarget.LOCAL or _is_role_named_agent(agent_name),
        )
        validated_slug = _validate_slug(target_dir, target, raw, slug)
        _ensure_provider_wired_in_workflow(
            target_dir,
            target,
            validated_slug,
            allow_unwired=allow_unwired,
        )

        try:
            index = parse_slot(slot)
            chain, message = assign_slot(_model_chain_from_entry(entry), index, validated_slug)
        except AgentRosterError as exc:
            cli_bail(str(exc))

        entry["modelChain"] = chain
        _persist_entry(target_dir, target, config_path, raw, agents, agent_name, entry)
        console.print(f"[green]{message} on agents.{agent_name}[/green]")

    @roster_app.command("add-model")
    def add_model_cmd(
        name: str = typer.Argument(..., help="Agent name."),
        slug: str = typer.Argument(..., help="Registered provider/model slug."),
        allow_unwired: bool = typer.Option(
            False,
            "--allow-unwired",
            help="Permit appending a provider that is not wired into mergecraft.yml (warns).",
        ),
        cwd: Path = typer.Option(Path("."), "--cwd", help="Working directory."),
    ) -> None:
        """Append a registered model to an agent's chain (no-op when duplicate, D4)."""
        agent_name = _validate_agent_name(name)
        target_dir = resolve_target_dir(cwd)
        config_path, raw, agents = _load_agents_block(target_dir, target)
        entry = _agent_entry(
            agents,
            agent_name,
            target=target,
            create_if_missing=target == AgentRosterTarget.LOCAL or _is_role_named_agent(agent_name),
        )
        validated_slug = _validate_slug(target_dir, target, raw, slug)
        _ensure_provider_wired_in_workflow(
            target_dir,
            target,
            validated_slug,
            allow_unwired=allow_unwired,
        )
        chain, was_duplicate = add_model(_model_chain_from_entry(entry), validated_slug)
        if was_duplicate:
            console.print(
                f"model {validated_slug!r} is already in the chain for agents.{agent_name}"
            )
            return

        entry["modelChain"] = chain
        _persist_entry(target_dir, target, config_path, raw, agents, agent_name, entry)
        console.print(f"[green]appended {validated_slug!r} to agents.{agent_name}[/green]")

    @roster_app.command("remove-model")
    def remove_model_cmd(
        name: str = typer.Argument(..., help="Agent name."),
        token: str = typer.Argument(..., help="Slot (pN) or model slug to remove."),
        cwd: Path = typer.Option(Path("."), "--cwd", help="Working directory."),
    ) -> None:
        """Remove a model slot and compact the chain."""
        agent_name = _validate_agent_name(name)
        target_dir = resolve_target_dir(cwd)
        config_path, raw, agents = _load_agents_block(target_dir, target)
        entry = _agent_entry(agents, agent_name, target=target)
        chain = _model_chain_from_entry(entry)
        try:
            index = _resolve_remove_index(chain, token)
            updated = remove_slot(chain, index)
        except AgentRosterError as exc:
            cli_bail(str(exc))

        entry["modelChain"] = updated
        _persist_entry(target_dir, target, config_path, raw, agents, agent_name, entry)
        console.print(f"[green]removed {token!r} from agents.{agent_name}[/green]")

    @roster_app.command("set-after")
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
        config_path, raw, agents = _load_agents_block(target_dir, target)
        entry = _agent_entry(agents, agent_name, target=target)
        merged_agents = _merged_raw_for_validation(target_dir, raw).get("agents", agents)
        if not isinstance(merged_agents, dict):
            merged_agents = agents

        if after == "--none":
            entry.pop("after", None)
        else:
            after_name = _validate_agent_name(after)
            if after_name not in merged_agents:
                cli_bail(f"unknown after agent {after_name!r}")
            entry["after"] = after_name

        _persist_entry(target_dir, target, config_path, raw, agents, agent_name, entry)
        if after == "--none":
            console.print(f"[green]cleared after: on agents.{agent_name}[/green]")
        else:
            console.print(f"[green]set agents.{agent_name}.after to {after!r}[/green]")

    return roster_app


app = create_agent_app(target=AgentRosterTarget.COMMITTED)


__all__ = ["AgentRosterTarget", "app", "create_agent_app"]
