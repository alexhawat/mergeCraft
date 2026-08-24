"""``mergecraft provider`` — operator provider registry (#477 / BA)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer
import yaml

from mergecraft.agents.openai_compatible_gateways import GATEWAY_PRESETS
from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.errors import cli_bail
from mergecraft.config.provider_registry import (
    BUILTIN_HARNESS_DEFAULTS,
    allocate_env_index,
    default_auth_kind_for_label,
    default_harness_for_label,
    harness_supports_provider,
    list_supported_harnesses,
    supported_harness_names,
    validate_http_url,
)
from mergecraft.config.settings import _DEFAULT_CONFIG_REL
from mergecraft.models import PROVIDERS

app = typer.Typer(
    help="Add, list, edit, and delete LLM providers in the operator registry.",
    no_args_is_help=True,
)


@dataclass(frozen=True, slots=True)
class ProviderRegistry:
    """In-memory view of ``providers:`` from config (no ``PROVIDERS`` consult)."""

    entries: tuple[dict[str, Any], ...]

    def get(self, label: str) -> dict[str, Any] | None:
        return self.lookup(label)

    def lookup(self, label: str) -> dict[str, Any] | None:
        lowered = label.strip().lower()
        for entry in self.entries:
            if str(entry.get("label", "")).lower() == lowered:
                return entry
        return None

    def labels(self) -> list[str]:
        return [str(entry["label"]) for entry in self.entries if entry.get("label")]


def _config_path(cwd: Path) -> Path:
    return (cwd / _DEFAULT_CONFIG_REL).resolve()


def _env_path() -> Path:
    configured = os.environ.get("MERGECRAFT_ENV")
    if configured:
        return Path(configured).resolve()
    return Path.cwd() / ".env"


def _load_config_dict(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        cli_bail(f"config must be a mapping: {path}")
    return loaded


def _write_config_dict(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


def _provider_entries(data: dict[str, Any]) -> list[dict[str, Any]]:
    raw = data.get("providers")
    if raw is None:
        return []
    if not isinstance(raw, list):
        cli_bail("providers must be a list in config")
    return [entry for entry in raw if isinstance(entry, dict)]


def _write_env_label(env_index: int, label: str) -> None:
    from mergecraft.cli.auth_cmd import _write_env_value

    key = f"LLM_PROVIDER_{env_index}"
    _write_env_value(_env_path(), key, label)


def _harness_help_suffix() -> str:
    names = ", ".join(sorted(supported_harness_names()))
    return f"supported harness values: {names}"


def resolve_provider_harness(label: str, *, harness: str | None = None) -> str:
    """Resolve harness for *label*; unknown labels never default to ``opencode`` (D4)."""
    normalised = label.strip().lower()
    if harness is not None:
        harness_value = harness.strip().lower()
        if harness_value not in supported_harness_names():
            msg = f"unknown harness {harness!r}; {_harness_help_suffix()}"
            raise ValueError(msg)
        if not harness_supports_provider(harness_value, normalised):
            msg = (
                f"incompatible harness {harness_value!r} for provider {label!r}; "
                f"{_harness_help_suffix()}"
            )
            raise ValueError(msg)
        return harness_value

    default = default_harness_for_label(normalised)
    if default is not None:
        return default

    msg = f"provider {label!r} requires --harness; {_harness_help_suffix()}"
    raise ValueError(msg)


def load_provider_registry(config_path: Path) -> ProviderRegistry:
    """Load registry entries from *config_path* only (``PROVIDERS`` is seed-only)."""
    data = _load_config_dict(config_path)
    return ProviderRegistry(entries=tuple(_provider_entries(data)))


def _seed_url_for_label(label: str) -> str | None:
    preset = GATEWAY_PRESETS.get(label)
    if preset is not None:
        return preset.default_base_url
    return None


def seed_builtin_providers(config_path: Path) -> None:
    """Import built-in ``PROVIDERS`` catalog rows once (not a reconcile loop)."""
    data = _load_config_dict(config_path)
    if data.get("providersSeeded"):
        return

    entries = _provider_entries(data)
    existing = {str(entry.get("label", "")).lower() for entry in entries}
    next_index = allocate_env_index(entries)

    for label in sorted(PROVIDERS.keys()):
        if label.lower() in existing:
            continue
        harness = default_harness_for_label(label) or "opencode"
        entry: dict[str, Any] = {
            "label": label,
            "harness": harness,
            "envIndex": next_index,
        }
        auth_kind = default_auth_kind_for_label(label)
        if auth_kind is not None:
            entry["authKind"] = auth_kind
        url = _seed_url_for_label(label)
        if url is not None:
            entry["url"] = url
        entries.append(entry)
        next_index += 1

    data["providers"] = entries
    data["providersSeeded"] = True
    _write_config_dict(config_path, data)


@app.command("harnesses")
def harnesses_cmd() -> None:
    """List supported agent harnesses (generated from code)."""
    for row in list_supported_harnesses():
        console.print(f"{row.name}  {row.description}")


@app.command("list")
def list_cmd(
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root."),
) -> None:
    """List registered provider labels."""
    config_path = _config_path(cwd.resolve())
    registry = load_provider_registry(config_path)
    if not registry.labels():
        console.print("no providers registered")
        return
    for label in registry.labels():
        console.print(label)


@app.command("add")
def add_cmd(
    label: str = typer.Option(..., "--label", help="Stable provider handle."),
    url: str | None = typer.Option(None, "--url", help="OpenAI-compatible base URL."),
    harness: str | None = typer.Option(None, "--harness", help="Agent harness for this provider."),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root."),
) -> None:
    """Register a provider in config and allocate an indexed ``.env`` slot."""
    repo_root = cwd.resolve()
    config_path = _config_path(repo_root)
    data = _load_config_dict(config_path)
    entries = _provider_entries(data)

    normalised_label = label.strip()
    if not normalised_label:
        cli_bail("label must not be empty")

    if any(str(entry.get("label", "")).lower() == normalised_label.lower() for entry in entries):
        cli_bail(f"duplicate provider label {normalised_label!r} already registered")

    try:
        resolved_harness = resolve_provider_harness(normalised_label, harness=harness)
    except ValueError as exc:
        cli_bail(str(exc))

    is_builtin_default = normalised_label.lower() in BUILTIN_HARNESS_DEFAULTS
    resolved_url: str | None = None
    if url is not None:
        try:
            resolved_url = validate_http_url(url)
        except ValueError as exc:
            cli_bail(str(exc))
    elif not is_builtin_default:
        cli_bail(f"provider {normalised_label!r} requires --url (absolute http(s) URL)")

    env_index = allocate_env_index(entries)
    entry: dict[str, Any] = {
        "label": normalised_label,
        "harness": resolved_harness,
        "envIndex": env_index,
    }
    if resolved_url is not None:
        entry["url"] = resolved_url

    entries.append(entry)
    data["providers"] = entries
    _write_config_dict(config_path, data)
    _write_env_label(env_index, normalised_label)
    console.print(
        f"registered provider [green]{normalised_label}[/green] "
        f"(envIndex={env_index}, harness={resolved_harness})"
    )


@app.command("edit")
def edit_cmd(
    label: str = typer.Argument(..., help="Provider label to update."),
    url: str | None = typer.Option(None, "--url", help="New OpenAI-compatible base URL."),
    harness: str | None = typer.Option(None, "--harness", help="New agent harness."),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root."),
) -> None:
    """Update an existing provider entry in config."""
    repo_root = cwd.resolve()
    config_path = _config_path(repo_root)
    data = _load_config_dict(config_path)
    entries = _provider_entries(data)

    match_index: int | None = None
    for idx, entry in enumerate(entries):
        if str(entry.get("label", "")).lower() == label.strip().lower():
            match_index = idx
            break
    if match_index is None:
        cli_bail(f"unknown provider label {label!r}")

    updated = dict(entries[match_index])
    if url is not None:
        try:
            updated["url"] = validate_http_url(url)
        except ValueError as exc:
            cli_bail(str(exc))
    if harness is not None:
        try:
            updated["harness"] = resolve_provider_harness(
                str(updated.get("label", label)),
                harness=harness,
            )
        except ValueError as exc:
            cli_bail(str(exc))

    entries[match_index] = updated
    data["providers"] = entries
    _write_config_dict(config_path, data)
    console.print(f"updated provider [green]{updated.get('label', label)}[/green]")


@app.command("delete")
def delete_cmd(
    label: str = typer.Argument(..., help="Provider label to remove."),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root."),
) -> None:
    """Remove a provider label from config (env index gap is preserved)."""
    repo_root = cwd.resolve()
    config_path = _config_path(repo_root)
    data = _load_config_dict(config_path)
    entries = _provider_entries(data)

    remaining: list[dict[str, Any]] = []
    removed = False
    for entry in entries:
        if str(entry.get("label", "")).lower() == label.strip().lower():
            removed = True
            continue
        remaining.append(entry)

    if not removed:
        cli_bail(f"unknown provider label {label!r}")

    data["providers"] = remaining
    _write_config_dict(config_path, data)
    console.print(f"deleted provider [green]{label}[/green]")


__all__ = [
    "ProviderRegistry",
    "app",
    "list_supported_harnesses",
    "load_provider_registry",
    "resolve_provider_harness",
    "seed_builtin_providers",
]
