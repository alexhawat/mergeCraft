"""``mergecraft provider status`` — roster credential and wiring inspection (#520).

Read-only operator view of what CI will run: per-reviewer ``modelChain`` slots,
credential presence, workflow wiring, dispatch levels, and optional GitHub
secret presence via ``--github``.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from mergecraft.agents.registry import AgentRole, RegistryValidationError, load_registry
from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.errors import cli_bail
from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE
from mergecraft.cli.provider_cmd import (
    _config_path,
    _env_path,
    _read_env_map,
    load_provider_registry,
    resolve_indexed_credential,
)
from mergecraft.cli.provider_toggle import resolve_provider_secrets
from mergecraft.cli.target_dir import target_dir as resolve_target_dir
from mergecraft.config.runtime_provider_registry import (
    credential_env_keys_for_entry,
    lookup_registry_entry,
)
from mergecraft.config.settings import load_repo_settings
from mergecraft.models import parse_model
from mergecraft.workflow.auth_manifest import (
    DEFAULT_WORKFLOW_RELATIVE_PATH,
    WorkflowAuthManifestError,
    flat_credential_env_keys,
    parse_auth_manifest,
)

STATUS_JSON_SCHEMA_VERSION = 1

STATUS_JSON_SCHEMA: dict[str, Any] = {
    "version": STATUS_JSON_SCHEMA_VERSION,
    "description": (
        "Roster view of reviewer agents, modelChain slots, credential presence, "
        "workflow wiring, dispatch levels, and optional GitHub secret presence."
    ),
    "required": ["schemaVersion", "reviewers"],
    "properties": {
        "schemaVersion": {"type": "integer", "const": STATUS_JSON_SCHEMA_VERSION},
        "headline": {"type": "string"},
        "skipped": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["agentId", "slot", "reason"],
            },
        },
        "reviewers": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["agentId", "slots"],
                "properties": {
                    "agentId": {"type": "string"},
                    "after": {"type": ["string", "null"]},
                    "dispatchLevel": {"type": "integer"},
                    "enabled": {"type": "boolean"},
                    "slots": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["slot", "model", "provider", "credential", "wired"],
                        },
                    },
                },
            },
        },
        "github": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "message": {"type": "string"},
                "secrets": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["name", "present"],
                    },
                },
            },
        },
    },
}


@dataclass(frozen=True, slots=True)
class CredentialStatus:
    """Credential probe result for one model slug (lane B adapter surface)."""

    available: bool
    source: str
    looked_for: str


def credential_status_for_slug(
    slug: str,
    *,
    settings: Any,
    cwd: Path,
    wired: bool,
) -> CredentialStatus:
    """Return credential presence for *slug* without printing secret material."""
    import importlib

    try:
        lane_b_module = importlib.import_module("mergecraft.utils.agent_resolve")
        lane_b_status = getattr(lane_b_module, "credential_status_for_slug", None)
    except ImportError:
        lane_b_status = None
    if lane_b_status is not None:
        try:
            status = lane_b_status(slug, settings=settings, cwd=cwd, wired=wired)
        except TypeError:
            pass
        else:
            return CredentialStatus(
                available=bool(status.available),
                source=str(status.source),
                looked_for=str(status.looked_for),
            )

    return _local_credential_status(slug, settings=settings, cwd=cwd, wired=wired)


def _local_credential_status(
    slug: str,
    *,
    settings: Any,
    cwd: Path,
    wired: bool,
) -> CredentialStatus:
    del wired  # unwired slots still report which env var would be consulted
    try:
        provider, _model_id = parse_model(slug)
    except ValueError:
        return CredentialStatus(available=False, source="unknown", looked_for="")

    provider_key = provider.lower()
    env_map = _read_env_map(_env_path(cwd))
    entry = lookup_registry_entry(settings, provider_key)
    keys: tuple[str, ...]
    if entry is not None:
        keys = credential_env_keys_for_entry(entry)
        if resolve_indexed_credential(
            {
                "label": entry.label,
                "envIndex": entry.env_index,
                "authKind": entry.auth_kind,
            },
            cwd=cwd,
        ):
            primary = keys[0] if keys else f"LLM_PROVIDER_{entry.env_index}_API_KEY"
            return CredentialStatus(available=True, source="env", looked_for=primary)
    else:
        keys = flat_credential_env_keys(provider_key)

    if not keys:
        keys = flat_credential_env_keys(provider_key)

    for key in keys:
        if env_map.get(key, "").strip() or os.environ.get(key, "").strip():
            return CredentialStatus(available=True, source="env", looked_for=key)

    looked_for = keys[0] if keys else f"{provider_key.upper()}_API_KEY"
    return CredentialStatus(available=False, source="env", looked_for=looked_for)


def _provider_disabled(label: str, entry: dict[str, Any] | None, *, cwd: Path) -> bool:
    secrets = resolve_provider_secrets(label, entry)
    if not secrets.local:
        return False
    env_map = _read_env_map(_env_path(cwd))
    has_blank = any(key in env_map and not env_map[key].strip() for key in secrets.local)
    has_value = any(
        env_map.get(key, "").strip() or os.environ.get(key, "").strip() for key in secrets.local
    )
    return has_blank and not has_value


def _wired_providers(workflow_path: Path) -> frozenset[str]:
    if not workflow_path.is_file():
        return frozenset()
    try:
        return parse_auth_manifest(workflow_path)
    except WorkflowAuthManifestError:
        return frozenset()


def _dispatch_level_map(registry: Any) -> dict[str, int]:
    levels = registry.resolve_role_levels(AgentRole.reviewer)
    mapping: dict[str, int] = {}
    for level_index, batch in enumerate(levels):
        for binding in batch:
            mapping[binding.agent_id] = level_index
    return mapping


def _github_token() -> str | None:
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


def list_repo_secrets(repo_slug: str) -> list[str]:
    """Return Actions secret names on *repo_slug* (empty when ``gh`` is unavailable)."""
    try:
        completed = subprocess.run(  # nosec B603 B607 — fixed argv, gh binary
            ["gh", "secret", "list", "--repo", repo_slug, "--json", "name", "-q", ".[].name"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return []
    if completed.returncode != 0:
        return []
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def secret_is_present(repo_slug: str, name: str) -> bool:
    """Return whether *name* exists as an Actions secret on *repo_slug*."""
    return name in list_repo_secrets(repo_slug)


def _resolve_repo_slug(cwd: Path) -> str:
    """Return ``owner/repo`` for *cwd*, or a placeholder when origin is unreadable."""
    import re

    from mergecraft.utils.git_hardening import read_remote_origin_url

    resolved = cwd.resolve()
    try:
        url = read_remote_origin_url(str(resolved))
    except (RuntimeError, OSError):
        return "local/unknown"
    match = re.search(r"github\.com(?::\d+)?[:/]+([^/]+)/(.+?)(?:\.git)?(?:/)?$", url)
    if not match:
        return "local/unknown"
    return f"{match.group(1)}/{match.group(2)}"


def _collect_github_secrets(
    *,
    cwd: Path,
    registry_data: Any,
    wired: frozenset[str],
) -> dict[str, Any]:
    token = _github_token()
    if token is None:
        return {
            "status": "unknown",
            "message": (
                "GitHub secret presence unknown — set GH_TOKEN or GITHUB_TOKEN "
                "(repo scope: read:repo or admin:repo_hook) and re-run with --github"
            ),
        }

    repo_slug = _resolve_repo_slug(cwd)
    if repo_slug == "local/unknown":
        return {
            "status": "unknown",
            "message": (
                "GitHub secret presence unknown — could not resolve owner/repo from "
                f"git origin at {cwd.resolve()}"
            ),
        }

    present_names = set(list_repo_secrets(repo_slug))
    provider_registry = load_provider_registry(_config_path(cwd))
    provider_entry_by_label = {
        str(row.get("label", "")).lower(): row for row in provider_registry.entries
    }
    required: list[str] = []
    seen: set[str] = set()
    for binding in registry_data.resolve_roles(AgentRole.reviewer):
        for slug in binding.model_chain:
            try:
                provider, _ = parse_model(slug)
            except ValueError:
                continue
            provider_key = provider.lower()
            if provider_key not in wired:
                continue
            registry_entry = provider_entry_by_label.get(provider_key)
            secrets = resolve_provider_secrets(provider_key, registry_entry)
            for name in secrets.github:
                if name not in seen:
                    seen.add(name)
                    required.append(name)

    secret_rows = [{"name": name, "present": name in present_names} for name in sorted(required)]
    return {"status": "ok", "repo": repo_slug, "secrets": secret_rows}


def build_status_payload(
    *,
    cwd: Path,
    github: bool = False,
) -> dict[str, Any]:
    target = resolve_target_dir(cwd)
    settings = load_repo_settings(root=target, load_learnings_files=False)
    try:
        registry = load_registry(settings=settings, repo_root=target)
    except RegistryValidationError as exc:
        cli_bail(str(exc))

    workflow_path = target / DEFAULT_WORKFLOW_RELATIVE_PATH
    wired = _wired_providers(workflow_path)
    provider_registry = load_provider_registry(_config_path(target))
    dispatch_levels = _dispatch_level_map(registry)

    reviewers_payload: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    provider_entry_by_label = {
        str(row.get("label", "")).lower(): row for row in provider_registry.entries
    }

    for binding in registry.resolve_roles(AgentRole.reviewer):
        slots_payload: list[dict[str, Any]] = []
        agent_enabled = True

        for index, slug in enumerate(binding.model_chain):
            slot_name = f"p{index}"
            try:
                provider, _model_id = parse_model(slug)
            except ValueError:
                provider = "unknown"
            provider_key = provider.lower()
            registry_entry = provider_entry_by_label.get(provider_key)
            disabled = _provider_disabled(provider_key, registry_entry, cwd=target)
            if disabled:
                agent_enabled = False
            is_wired = provider_key in wired
            credential = credential_status_for_slug(
                slug,
                settings=settings,
                cwd=target,
                wired=is_wired,
            )
            slot_payload = {
                "slot": slot_name,
                "model": slug,
                "provider": provider_key,
                "wired": is_wired,
                "credential": {
                    "available": credential.available,
                    "looked_for": credential.looked_for,
                    "source": credential.source,
                },
                "disabled": disabled,
            }
            slots_payload.append(slot_payload)

            if disabled:
                skipped.append(
                    {
                        "agentId": binding.agent_id,
                        "slot": slot_name,
                        "reason": f"provider {provider_key!r} is disabled",
                    }
                )
            elif not is_wired:
                skipped.append(
                    {
                        "agentId": binding.agent_id,
                        "slot": slot_name,
                        "reason": f"provider {provider_key!r} is not wired in mergecraft.yml",
                    }
                )
            elif not credential.available:
                skipped.append(
                    {
                        "agentId": binding.agent_id,
                        "slot": slot_name,
                        "reason": (f"credential not available (consult {credential.looked_for})"),
                    }
                )

        reviewers_payload.append(
            {
                "agentId": binding.agent_id,
                "after": binding.after,
                "dispatchLevel": dispatch_levels.get(binding.agent_id, 0),
                "enabled": agent_enabled,
                "slots": slots_payload,
            }
        )

    runnable = [
        row
        for reviewer in reviewers_payload
        for row in reviewer["slots"]
        if row["wired"] and row["credential"]["available"] and not row.get("disabled")
    ]
    headline = (
        f"{len(runnable)} slot(s) will run in CI"
        if runnable
        else "no roster slots are fully runnable in CI"
    )

    payload: dict[str, Any] = {
        "schemaVersion": STATUS_JSON_SCHEMA_VERSION,
        "headline": headline,
        "skipped": skipped,
        "reviewers": reviewers_payload,
    }
    if github:
        payload["github"] = _collect_github_secrets(
            cwd=target,
            registry_data=registry,
            wired=wired,
        )
    return payload


def _render_text(payload: dict[str, Any]) -> None:
    headline = payload.get("headline", "")
    console.print(Panel(Text(headline, style="bold"), title="What will CI run?"))

    skipped = payload.get("skipped") or []
    if skipped:
        skip_table = Table(title="Skipped slots", show_header=True, header_style="bold")
        skip_table.add_column("agent")
        skip_table.add_column("slot")
        skip_table.add_column("reason")
        for row in skipped:
            skip_table.add_row(row["agentId"], row["slot"], row["reason"])
        console.print(skip_table)

    for reviewer in payload.get("reviewers", []):
        agent_id = reviewer["agentId"]
        after = reviewer.get("after")
        level = reviewer.get("dispatchLevel", 0)
        title = f"{agent_id} (dispatch level {level}"
        if after:
            title += f", after {after}"
        title += ")"

        table = Table(title=title, show_header=True, header_style="bold")
        table.add_column("slot")
        table.add_column("model")
        table.add_column("provider")
        table.add_column("wired")
        table.add_column("credential")
        table.add_column("state")

        for slot in reviewer.get("slots", []):
            cred = slot["credential"]
            if slot.get("disabled"):
                state = "disabled"
            elif not slot["wired"]:
                state = "not wired"
            elif cred["available"]:
                state = "ready"
            else:
                state = "not available"

            wired_label = "wired" if slot["wired"] else "not wired"
            if cred["available"]:
                cred_label = "available"
            else:
                cred_label = f"not available ({cred['looked_for']})"

            table.add_row(
                slot["slot"],
                slot["model"],
                slot["provider"],
                wired_label,
                cred_label,
                state,
            )
        console.print(table)

    github = payload.get("github")
    if github is not None:
        status = github.get("status", "unknown")
        if status == "unknown":
            console.print(f"[yellow]GitHub secrets: unknown[/yellow] — {github.get('message', '')}")
        else:
            secret_table = Table(title="GitHub Actions secrets", show_header=True)
            secret_table.add_column("secret")
            secret_table.add_column("present")
            for row in github.get("secrets", []):
                present = row.get("present")
                label = "present" if present else "absent"
                secret_table.add_row(row.get("name", ""), label)
            console.print(secret_table)


def provider_status_cmd(
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root."),
    github: bool = typer.Option(
        False,
        "--github",
        help="Also report whether required Actions secrets exist on the repo.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Show the reviewer roster, credentials, wiring, and dispatch order."""
    payload = build_status_payload(cwd=cwd, github=github)
    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        raise typer.Exit(CLI_SUCCESS_EXIT_CODE)
    _render_text(payload)


def register(provider_app: typer.Typer) -> None:
    """Attach ``status`` to the ``provider`` Typer app."""
    provider_app.command("status")(provider_status_cmd)


__all__ = [
    "STATUS_JSON_SCHEMA",
    "STATUS_JSON_SCHEMA_VERSION",
    "CredentialStatus",
    "build_status_payload",
    "credential_status_for_slug",
    "list_repo_secrets",
    "provider_status_cmd",
    "register",
    "secret_is_present",
]
