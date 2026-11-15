"""Check provider credentials and describe unavailable reviewer slots.

Module: mergecraft.agents.resolution.credentials
Depends: mergecraft.{agents,config,models,security,workflow}

Exports:
    Classes:
        CredentialStatus — Credential presence, provenance, and consulted env names.
    Functions:
        credential_status_for_slug — Check a model's credential routes in precedence order.
        collect_roster_credential_degradations — Describe each unreachable credential slot.
        has_credentials_for_slug — Check model credentials in the current environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from mergecraft.config.env import CUSTOM_PROVIDER_API_KEY_ENV
from mergecraft.models import BEDROCK_MODEL_ID_ENV, VERTEX_MODEL_ID_ENV, get_model_provider

if TYPE_CHECKING:
    from mergecraft.config.settings import RepoSettings


def _has_env(name: str) -> bool:
    val = os.environ.get(name)
    return isinstance(val, str) and bool(val.strip())


def has_claude_code_auth() -> bool:
    return _has_env("CLAUDE_CODE_OAUTH_TOKEN") or _has_env("ANTHROPIC_API_KEY")


def has_bedrock_auth() -> bool:
    return _has_env("AWS_BEARER_TOKEN_BEDROCK") or (
        _has_env("AWS_ACCESS_KEY_ID") and _has_env("AWS_SECRET_ACCESS_KEY")
    )


def has_vertex_auth() -> bool:
    return _has_env("GOOGLE_APPLICATION_CREDENTIALS") or _has_env("VERTEX_SERVICE_ACCOUNT_JSON")


def has_codex_subscription_auth() -> bool:
    raw = os.environ.get("CODEX_AUTH_JSON", "").strip()
    if not raw:
        return False
    from mergecraft.security.broker import subscription_auth_usable

    return subscription_auth_usable(raw)


def has_openai_api_key_auth() -> bool:
    return _has_env("OPENAI_API_KEY")


def has_gemini_auth() -> bool:
    return _has_env("GEMINI_API_KEY") or _has_env("GOOGLE_GENERATIVE_AI_API_KEY")


def has_cursor_auth() -> bool:
    return _has_env("CURSOR_API_KEY")


def has_opencode_zen_auth() -> bool:
    if _has_env("OPENCODE_API_KEY"):
        return True
    raw = os.environ.get("OPENCODE_AUTH_JSON", "").strip()
    if not raw:
        return False
    from mergecraft.security.opencode_auth import opencode_auth_usable

    return opencode_auth_usable(raw)


_BUILTIN_CLI_AUTH_PROVIDERS: frozenset[str] = frozenset(
    {"anthropic", "openai", "google", "cursor", "bedrock", "vertex", "opencode", "opencode-go"}
)


@dataclass(frozen=True, slots=True)
class CredentialStatus:
    """Credential probe result for one model slug (lane B / #552)."""

    available: bool
    source: str | None
    looked_for: tuple[str, ...]


def cli_auth_available(provider: str) -> bool:
    """Return whether the built-in provider has usable CLI credentials."""
    if provider == "anthropic":
        return has_claude_code_auth()
    if provider == "openai":
        return has_codex_subscription_auth() or has_openai_api_key_auth()
    if provider == "google":
        return has_gemini_auth()
    if provider == "cursor":
        return has_cursor_auth()
    if provider == "bedrock":
        return has_bedrock_auth() and bool(os.environ.get(BEDROCK_MODEL_ID_ENV, "").strip())
    if provider == "vertex":
        return has_vertex_auth() and bool(os.environ.get(VERTEX_MODEL_ID_ENV, "").strip())
    if provider in {"opencode", "opencode-go"}:
        return has_opencode_zen_auth()
    return False


def _honours_gateway_env_credentials(provider: str, settings: RepoSettings) -> bool:
    """Return whether singleton/indexed gateway env vars may satisfy *provider*."""
    from mergecraft.agents.openai_compatible_gateways import legacy_gateway_preset_provider_labels

    if provider in legacy_gateway_preset_provider_labels():
        return True
    from mergecraft.config.runtime_provider_registry import lookup_registry_entry

    entry = lookup_registry_entry(settings, provider)
    if entry is not None:
        return entry.harness == "opencode"
    return provider not in _BUILTIN_CLI_AUTH_PROVIDERS


def _credential_looked_for_envs(provider: str, *, settings: RepoSettings) -> tuple[str, ...]:
    from mergecraft.config.runtime_provider_registry import (
        credential_env_keys_for_entry,
        lookup_registry_entry,
    )
    from mergecraft.workflow.auth_manifest import flat_credential_env_keys

    keys: list[str] = []
    entry = lookup_registry_entry(settings, provider)
    if entry is not None:
        keys.extend(credential_env_keys_for_entry(entry))
        workflow_key = f"MERGECRAFT_CUSTOM_PROVIDER_API_KEY_{entry.env_index}"
        if workflow_key not in keys:
            keys.append(workflow_key)
    else:
        keys.extend(flat_credential_env_keys(provider))
    if (
        _honours_gateway_env_credentials(provider, settings)
        and CUSTOM_PROVIDER_API_KEY_ENV not in keys
    ):
        keys.append(CUSTOM_PROVIDER_API_KEY_ENV)
    deduped: list[str] = []
    for key in keys:
        if key not in deduped:
            deduped.append(key)
    return tuple(deduped)


def credential_status_for_slug(
    slug: str,
    *,
    settings: RepoSettings,
    cwd: Path,
    wired: bool,
) -> CredentialStatus:
    """Return credential presence and provenance for *slug* (lane B / #552, lane C #520)."""
    del cwd  # lane C #573 — workflow-local env reads stay in ``provider_status``
    del wired  # wiring vs env gaps are surfaced by :func:`format_credential_gap_message`

    try:
        provider = get_model_provider(slug)
    except ValueError:
        return CredentialStatus(available=False, source=None, looked_for=())

    looked_for = _credential_looked_for_envs(provider, settings=settings)

    from mergecraft.agents.openai_compatible_gateways import (
        has_gateway_env as _gateway_has_env,
    )
    from mergecraft.agents.openai_compatible_gateways import (
        has_legacy_gateway_preset_credentials,
        resolve_indexed_providers,
    )
    from mergecraft.config.runtime_provider_registry import (
        indexed_credential_for_entry,
        lookup_registry_entry,
    )

    entry = lookup_registry_entry(settings, provider)
    if entry is not None and indexed_credential_for_entry(entry):
        return CredentialStatus(
            available=True,
            source="registry-indexed",
            looked_for=looked_for,
        )

    if _honours_gateway_env_credentials(provider, settings) and _gateway_has_env(
        CUSTOM_PROVIDER_API_KEY_ENV
    ):
        return CredentialStatus(
            available=True,
            source="gateway-singleton",
            looked_for=looked_for,
        )

    if _honours_gateway_env_credentials(provider, settings) and resolve_indexed_providers():
        return CredentialStatus(
            available=True,
            source="gateway-singleton",
            looked_for=looked_for,
        )

    if provider in _BUILTIN_CLI_AUTH_PROVIDERS and cli_auth_available(provider):
        return CredentialStatus(available=True, source="cli-auth", looked_for=looked_for)

    if has_legacy_gateway_preset_credentials(provider):
        return CredentialStatus(available=True, source="legacy-env", looked_for=looked_for)

    return CredentialStatus(available=False, source=None, looked_for=looked_for)


def format_credential_gap_message(
    *,
    slug: str,
    wired: bool,
    status: CredentialStatus,
) -> str:
    """Return an operator-facing gap message (D9 — unwired vs empty env stay distinct)."""
    from mergecraft.models import parse_model

    try:
        provider, _model_id = parse_model(slug)
    except ValueError:
        provider = "unknown"
    provider_key = provider.lower()

    if not wired:
        return (
            f"provider {provider_key!r} has no credential step in mergecraft.yml "
            f"for model {slug!r} — wire it with "
            f"`mergecraft workflow provider add --label {provider_key}` "
            "or choose a different model"
        )

    env_hint = (
        ", ".join(status.looked_for) if status.looked_for else "the provider credential env vars"
    )
    return (
        f"no credential in env for {slug!r} (provider {provider_key!r}) — "
        f"consult {env_hint}; set via `mergecraft provider auth {provider_key}` "
        "or `gh secret set`"
    )


def build_missing_credential_degradation(
    *,
    agent_id: str,
    slot: str,
    slug: str,
    wired: bool = True,
    settings: RepoSettings | None = None,
    cwd: Path | None = None,
) -> str:
    """Build a loud degradation line for a roster slot skipped for missing credentials (D10)."""
    from mergecraft.config.settings import load_repo_settings

    root = cwd or Path.cwd()
    resolved_settings = settings or load_repo_settings(root=root, load_learnings_files=False)
    status = credential_status_for_slug(
        slug,
        settings=resolved_settings,
        cwd=root,
        wired=wired,
    )
    try:
        provider = get_model_provider(slug)
    except ValueError:
        provider = "unknown"
    gap = format_credential_gap_message(slug=slug, wired=wired, status=status)
    envs = ", ".join(status.looked_for).lower() if status.looked_for else "credential env vars"
    return (
        f"reviewer {agent_id!r} slot {slot} skipped for missing credentials: "
        f"provider {provider!r}, model {slug!r}; {gap}; looked for {envs}"
    )


def collect_roster_credential_degradations(
    *,
    settings: RepoSettings,
    cwd: Path,
    wired_providers: frozenset[str] | None = None,
    model_head: str | None = None,
    model_pin: bool = False,
) -> tuple[str, ...]:
    """Return loud degradation lines for reviewer slots missing credentials (D10).

    The record follows the chain the run actually executes. ``model_head`` is
    the model the operator named for this run and ``model_pin`` is their "use
    exactly this model" opt-in. When pinned, a default reviewer binding runs
    only its head, so a configured tail it has no credential for is not
    reported as a skipped slot.
    """
    from mergecraft.agents.registry import AgentRole, load_registry
    from mergecraft.config.agent_roster import load_roster
    from mergecraft.config.io import config_path_for_root, load_config_dict
    from mergecraft.workflow.auth_manifest import (
        DEFAULT_WORKFLOW_RELATIVE_PATH,
        WorkflowAuthManifestError,
        parse_auth_manifest,
    )

    registry = load_registry(settings=settings, repo_root=cwd, model_head=model_head)
    raw = load_config_dict(config_path_for_root(cwd))
    load_roster(raw)
    wired = wired_providers
    if wired is None:
        workflow_path = cwd / DEFAULT_WORKFLOW_RELATIVE_PATH
        if workflow_path.is_file():
            try:
                wired = parse_auth_manifest(workflow_path)
            except WorkflowAuthManifestError:
                wired = frozenset()
        else:
            wired = frozenset()

    pinned_head = model_head if model_pin and model_head else None
    degradations: list[str] = []
    for agent_key, binding in registry.ordered_role_entries(AgentRole.reviewer):
        chain: tuple[str, ...] = binding.model_chain
        if pinned_head is not None and agent_key not in registry.configured_keys:
            # A pinned run executes exactly the named head, so the default
            # binding's configured tail is not a slot this run can reach.
            chain = (pinned_head,)
        for index, slug in enumerate(chain):
            try:
                provider = get_model_provider(slug)
            except ValueError:
                continue
            provider_key = provider.lower()
            is_wired = provider_key in wired
            status = credential_status_for_slug(
                slug,
                settings=settings,
                cwd=cwd,
                wired=is_wired,
            )
            if status.available:
                continue
            degradations.append(
                build_missing_credential_degradation(
                    agent_id=agent_key,
                    slot=f"p{index}",
                    slug=slug,
                    wired=is_wired,
                    settings=settings,
                    cwd=cwd,
                )
            )
    return tuple(degradations)


def has_credentials_for_slug(slug: str) -> bool:
    """Return whether the current environment has credentials for ``slug``."""
    from mergecraft.config.settings import load_repo_settings

    settings = load_repo_settings(root=Path.cwd(), load_learnings_files=False)
    return credential_status_for_slug(
        slug,
        settings=settings,
        cwd=Path.cwd(),
        wired=True,
    ).available


__all__ = [
    "CredentialStatus",
    "build_missing_credential_degradation",
    "cli_auth_available",
    "collect_roster_credential_degradations",
    "credential_status_for_slug",
    "format_credential_gap_message",
    "has_bedrock_auth",
    "has_claude_code_auth",
    "has_codex_subscription_auth",
    "has_credentials_for_slug",
    "has_cursor_auth",
    "has_gemini_auth",
    "has_openai_api_key_auth",
    "has_opencode_zen_auth",
    "has_vertex_auth",
]
