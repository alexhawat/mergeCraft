"""Roster ↔ workflow auth manifest validation (wave plan 11 / W7, D1a)."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from mergecraft.config.agent_roster import load_roster
from mergecraft.config.io import config_path_for_root, load_config_dict
from mergecraft.config.roster_unwired import collect_unwired_roster_models, iter_roster_model_slots
from mergecraft.config.runtime_provider_registry import (
    indexed_env_key,
    lookup_registry_entry,
)
from mergecraft.models import parse_model
from mergecraft.workflow.auth_manifest import (
    DEFAULT_WORKFLOW_RELATIVE_PATH,
    WorkflowAuthManifestError,
    parse_auth_manifest,
    secret_name_to_provider_label,
    workflow_secret_bindings,
)

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.config.settings import RepoSettings
    from mergecraft.config.settings_snapshot import RepoSettingsSnapshot


class RosterAuthError(RuntimeError):
    """Raised when roster models reference providers CI cannot authenticate."""


class RosterSecretEmptyError(RuntimeError):
    """Raised when a wired provider's secret is unset at run time."""


def _roster_slugs_from_config(raw: dict[str, object]) -> tuple[str, ...]:
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


def _format_empty_secrets_message(*, entries: tuple[tuple[str, str], ...]) -> str:
    lines = [
        "one or more GitHub Actions secrets required by the roster are empty — "
        "set each secret (for example `mergecraft provider auth <label>` or "
        "`gh secret set <name>`):"
    ]
    for secret_name, provider in entries:
        lines.append(f"- {secret_name!r} (provider {provider!r})")
    return "\n".join(lines)


def _parse_auth_manifest_or_raise(workflow_path: Path) -> frozenset[str]:
    try:
        return parse_auth_manifest(workflow_path)
    except WorkflowAuthManifestError as exc:
        raise RosterAuthError(str(exc)) from exc


def _provider_for_secret(secret_name: str) -> str:
    label = secret_name_to_provider_label(secret_name)
    return label or secret_name.lower().removesuffix("_api_key")


def _required_env_keys_for_slug(
    *,
    settings: RepoSettings,
    slug: str,
    wired: frozenset[str],
) -> tuple[str, ...]:
    try:
        provider, _model_id = parse_model(slug)
    except ValueError as exc:
        raise RosterAuthError(str(exc)) from exc
    provider_key = provider.lower()
    if provider_key not in wired:
        return ()

    entry = lookup_registry_entry(settings, provider_key)
    if entry is not None:
        return (indexed_env_key(entry.env_index, "API_KEY"),)

    from mergecraft.workflow.auth_manifest import flat_credential_env_keys

    return flat_credential_env_keys(provider_key)


def _empty_secrets_for_roster(
    *,
    settings: RepoSettings,
    workflow_path: Path,
    roster_slugs: tuple[str, ...],
    wired: frozenset[str],
) -> tuple[str, ...]:
    env_to_secret = {
        env_key: secret_name for env_key, secret_name in workflow_secret_bindings(workflow_path)
    }
    empty: list[str] = []
    seen: set[str] = set()
    for slug in roster_slugs:
        for env_key in _required_env_keys_for_slug(settings=settings, slug=slug, wired=wired):
            if os.environ.get(env_key, "").strip():
                continue
            secret_name = env_to_secret.get(env_key, env_key)
            if secret_name in seen:
                continue
            seen.add(secret_name)
            empty.append(secret_name)
    return tuple(empty)


def validate_roster_against_auth_manifest(
    *,
    repo_root: Path,
    workflow_path: Path,
    roster_slugs: tuple[str, ...] | None = None,
    empty_secrets: tuple[str, ...] | None = None,
    settings: RepoSettings | None = None,
) -> None:
    """Fail closed when the roster names providers absent from the workflow manifest."""
    resolved_root = repo_root.resolve()
    raw = load_config_dict(config_path_for_root(resolved_root))
    slugs = roster_slugs if roster_slugs is not None else _roster_slugs_from_config(raw)
    if not slugs and empty_secrets is None:
        return

    wired = _parse_auth_manifest_or_raise(workflow_path)
    roster = load_roster(raw)
    if roster_slugs is None:
        try:
            unwired = collect_unwired_roster_models(roster=roster, wired_providers=wired)
        except ValueError as exc:
            raise RosterAuthError(str(exc)) from exc
        for agent_name, slot, _slug, provider_key in unwired:
            raise RosterAuthError(
                _format_unwired_message(agent=agent_name, slot=slot, provider=provider_key)
            )
    else:
        slug_to_slots: dict[str, list[tuple[str, str]]] = {}
        for agent_name, slot, slug in iter_roster_model_slots(roster):
            slug_to_slots.setdefault(slug, []).append((agent_name, slot))
        for slug in slugs:
            try:
                provider, _model_id = parse_model(slug)
            except ValueError as exc:
                raise RosterAuthError(str(exc)) from exc
            provider_key = provider.lower()
            if provider_key in wired:
                continue
            slots = slug_to_slots.get(slug, [("roster", "p0")])
            agent_name, slot = slots[0]
            raise RosterAuthError(
                _format_unwired_message(agent=agent_name, slot=slot, provider=provider_key)
            )

    resolved_empty = empty_secrets
    if resolved_empty is None and settings is not None and roster_slugs is not None:
        resolved_empty = _empty_secrets_for_roster(
            settings=settings,
            workflow_path=workflow_path,
            roster_slugs=roster_slugs,
            wired=wired,
        )

    if resolved_empty:
        entries: list[tuple[str, str]] = []
        for secret_name in resolved_empty:
            provider = _provider_for_secret(secret_name)
            entries.append((secret_name, provider))
        raise RosterSecretEmptyError(_format_empty_secrets_message(entries=tuple(entries)))


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
        settings=snapshot.settings,
    )


__all__ = [
    "RosterAuthError",
    "RosterSecretEmptyError",
    "validate_roster_against_auth_manifest",
    "validate_roster_at_run_start",
]
