"""Seed reviewer p0 after provider authentication (wave plan 11 / W8)."""

from __future__ import annotations

from pathlib import Path

from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.provider_toggle import canonical_provider_label
from mergecraft.config.agent_roster import AgentRosterError, seed_reviewer_p0_if_empty
from mergecraft.config.io import config_path_for_root, load_config_dict, write_config_dict


def seed_reviewer_p0_after_auth(*, cwd: Path, provider_label: str) -> None:
    """Write ``agents.reviewer`` p0 when the chain is empty after auth."""
    repo_root = cwd.resolve()
    config_path = config_path_for_root(repo_root)
    data = load_config_dict(config_path)
    catalog_label = canonical_provider_label(provider_label)
    try:
        slug = seed_reviewer_p0_if_empty(data, catalog_label)
    except AgentRosterError as exc:
        console.print(f"[yellow]warning:[/yellow] could not seed agents.reviewer p0: {exc}")
        return
    if slug is None:
        return
    write_config_dict(config_path, data)
    console.print(
        f"[green]seeded[/green] agents.reviewer p0 with [cyan]{slug}[/cyan] "
        f"in {config_path.relative_to(repo_root)}"
    )


__all__ = ["seed_reviewer_p0_after_auth"]
