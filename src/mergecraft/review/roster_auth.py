"""Roster ↔ workflow auth manifest validation (wave plan 11 / W7, D1a)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.cli.provider_cmd import _config_path, _load_config_dict
from mergecraft.cli.workflow_cmd import parse_auth_manifest
from mergecraft.cli.workflow_wf_yaml import DEFAULT_WORKFLOW_RELATIVE_PATH
from mergecraft.config.agent_roster import load_roster
from mergecraft.models import parse_model

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.config.settings import RepoSettings
    from mergecraft.config.settings_snapshot import RepoSettingsSnapshot


class RosterAuthError(RuntimeError):
    """Raised when roster models reference providers CI cannot authenticate."""


class RosterSecretEmptyError(RuntimeError):
    """Raised when a wired provider's secret is unset at run time."""


def _roster_slugs_from_config(repo_root: Path) -> tuple[str, ...]:
    raw = _load_config_dict(_config_path(repo_root))
    roster = load_roster(raw)
    slugs: list[str] = []
    for entry in roster.entries:
        slugs.extend(entry.model_chain)
    return tuple(slugs)


def _roster_slugs_from_settings(settings: RepoSettings) -> tuple[str, ...]:
    slugs: list[str] = []
    for binding in settings.agents.values():
        chain = binding.model_chain
        if not chain:
            continue
        slugs.extend(chain)
    return tuple(slugs)


def _format_unwired_message(*, agent: str, slot: str, provider: str) -> str:
    return (
        f"provider {provider!r} has no credential step in mergecraft.yml "
        f"(agent {agent!r} slot {slot} is unwired) — wire it with "
        f"`mergecraft workflow provider add --label {provider}` or choose a different model"
    )


def _format_empty_secret_message(*, secret_name: str, provider: str) -> str:
    return (
        f"GitHub Actions secret {secret_name!r} is empty for provider {provider!r} — "
        f"set the secret (for example `mergecraft provider auth {provider}` or "
        f"`gh secret set {secret_name}`)"
    )


def validate_roster_against_auth_manifest(
    *,
    repo_root: Path,
    workflow_path: Path,
    roster_slugs: tuple[str, ...] | None = None,
    empty_secrets: tuple[str, ...] | None = None,
) -> None:
    """Fail closed when the roster names providers absent from the workflow manifest."""
    resolved_root = repo_root.resolve()
    slugs = roster_slugs if roster_slugs is not None else _roster_slugs_from_config(resolved_root)
    if not slugs and empty_secrets is None:
        return

    wired = parse_auth_manifest(workflow_path)
    raw = _load_config_dict(_config_path(resolved_root))
    roster = load_roster(raw)
    agent_slots: list[tuple[str, str, str]] = []
    if roster_slugs is None:
        for entry in roster.entries:
            for index, slug in enumerate(entry.model_chain):
                agent_slots.append((entry.name, f"p{index}", slug))
    else:
        for slug in slugs:
            agent_slots.append(("roster", "p0", slug))

    for agent_name, slot, slug in agent_slots:
        try:
            provider, _model_id = parse_model(slug)
        except ValueError as exc:
            raise RosterAuthError(str(exc)) from exc
        provider_key = provider.lower()
        if provider_key not in wired:
            raise RosterAuthError(
                _format_unwired_message(agent=agent_name, slot=slot, provider=provider_key)
            )

    if empty_secrets:
        for secret_name in empty_secrets:
            provider = _provider_for_secret(secret_name)
            raise RosterSecretEmptyError(
                _format_empty_secret_message(secret_name=secret_name, provider=provider)
            )


def _provider_for_secret(secret_name: str) -> str:
    from mergecraft.cli.workflow_cmd import secret_name_to_provider_label

    label = secret_name_to_provider_label(secret_name)
    return label or secret_name.lower().removesuffix("_api_key")


def validate_roster_at_run_start(
    *,
    snapshot: RepoSettingsSnapshot,
    workflow_path: Path | None = None,
) -> None:
    """Validate snapshot roster slugs against the workflow auth manifest (D9)."""
    resolved_workflow = (
        workflow_path
        if workflow_path is not None
        else snapshot.repo_root / DEFAULT_WORKFLOW_RELATIVE_PATH
    )
    slugs = _roster_slugs_from_settings(snapshot.settings)
    validate_roster_against_auth_manifest(
        repo_root=snapshot.repo_root,
        workflow_path=resolved_workflow,
        roster_slugs=slugs,
    )


__all__ = [
    "RosterAuthError",
    "RosterSecretEmptyError",
    "validate_roster_against_auth_manifest",
    "validate_roster_at_run_start",
]
