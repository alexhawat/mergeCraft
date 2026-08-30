"""``mergecraft model`` — per-provider model registry (#479 / BC)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.errors import cli_bail
from mergecraft.cli.provider_cmd import (
    _config_path,
    _env_path,
    _load_config_dict,
    _provider_entries,
    load_provider_registry,
)
from mergecraft.config.io import write_config_dict
from mergecraft.config.model_registry import (
    allocate_model_index,
    effective_model_id,
    normalize_model_id,
)

app = typer.Typer(
    help="Add, list, and delete models on registered LLM providers.",
    no_args_is_help=True,
)


def _model_rows(entry: dict[str, Any]) -> list[dict[str, Any]]:
    raw = entry.get("models")
    if raw is None:
        return []
    if not isinstance(raw, list):
        cli_bail("models must be a list on provider entry")
    return [row for row in raw if isinstance(row, dict)]


def _model_id_from_row(row: dict[str, Any]) -> str:
    for key in ("id", "modelId", "model"):
        value = row.get(key)
        if value is not None:
            return str(value)
    return ""


def _model_index_from_row(row: dict[str, Any]) -> int | None:
    raw = row.get("modelIndex")
    if raw is None:
        return None
    return int(raw)


def _find_provider_index(entries: list[dict[str, Any]], label: str) -> int | None:
    lowered = label.strip().lower()
    for idx, entry in enumerate(entries):
        if str(entry.get("label", "")).lower() == lowered:
            return idx
    return None


def _registered_labels(entries: list[dict[str, Any]]) -> list[str]:
    return [str(entry["label"]) for entry in entries if entry.get("label")]


def _unknown_provider_message(label: str, labels: list[str]) -> str:
    registered = ", ".join(labels) if labels else "none"
    return f"unknown provider {label!r} — not registered; registered providers: {registered}"


def _prompt_provider(labels: list[str]) -> str:
    choices = ", ".join(labels)
    return str(typer.prompt(f"provider ({choices})"))


@app.command("list")
def list_cmd(
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root."),
) -> None:
    """List models registered on each provider."""
    repo_root = cwd.resolve()
    config_path = _config_path(repo_root)
    registry = load_provider_registry(config_path)
    env_file = _env_path(repo_root)

    if not registry.labels():
        console.print("no models registered")
        return

    any_model = False
    for entry in registry.entries:
        label = str(entry.get("label", ""))
        env_index = entry.get("envIndex")
        models = _model_rows(entry)
        if not models:
            continue
        for row in models:
            model_index = _model_index_from_row(row)
            stored_id = _model_id_from_row(row)
            if model_index is None or env_index is None:
                display_id = stored_id
            else:
                display_id = effective_model_id(
                    stored_id,
                    env_path=env_file,
                    env_index=int(env_index),
                    model_index=model_index,
                )
            console.print(f"{label}  {display_id}")
            any_model = True

    if not any_model:
        console.print("no models registered")


@app.command("add")
def add_cmd(
    model_id: str = typer.Argument(..., help="Model id (provider prefix optional)."),
    provider: str | None = typer.Option(
        None,
        "--provider",
        help="Registered provider label.",
    ),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root."),
) -> None:
    """Register a model on a provider in config (env override optional)."""
    repo_root = cwd.resolve()
    config_path = _config_path(repo_root)
    data = _load_config_dict(config_path)
    entries = _provider_entries(data)
    labels = _registered_labels(entries)

    if not labels:
        cli_bail("no providers registered — run mergecraft provider add first")

    provider_label = provider
    if provider_label is None:
        provider_label = _prompt_provider(labels)

    provider_label = provider_label.strip()
    provider_idx = _find_provider_index(entries, provider_label)
    if provider_idx is None:
        cli_bail(_unknown_provider_message(provider_label, labels))

    entry = dict(entries[provider_idx])
    provider_name = str(entry.get("label", provider_label))
    models = _model_rows(entry)
    normalised_id = normalize_model_id(provider_name, model_id)

    if not normalised_id:
        cli_bail("model id must not be empty")

    for row in models:
        if _model_id_from_row(row) == normalised_id:
            cli_bail(
                f"duplicate model {normalised_id!r} already registered on provider {provider_name!r}"
            )

    model_index = allocate_model_index(models)
    models.append({"id": normalised_id, "modelIndex": model_index})
    entry["models"] = models
    entries[provider_idx] = entry
    data["providers"] = entries
    write_config_dict(config_path, data)
    console.print(
        f"registered model [green]{normalised_id}[/green] on provider "
        f"[green]{provider_name}[/green] (modelIndex={model_index})"
    )


@app.command("delete")
def delete_cmd(
    provider: str = typer.Argument(..., help="Registered provider label."),
    model_id: str = typer.Argument(..., help="Model id to remove."),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root."),
) -> None:
    """Remove a model from a provider (model index gap is preserved)."""
    repo_root = cwd.resolve()
    config_path = _config_path(repo_root)
    data = _load_config_dict(config_path)
    entries = _provider_entries(data)
    labels = _registered_labels(entries)

    provider_idx = _find_provider_index(entries, provider)
    if provider_idx is None:
        cli_bail(_unknown_provider_message(provider, labels))

    entry = dict(entries[provider_idx])
    provider_name = str(entry.get("label", provider))
    models = _model_rows(entry)
    target_id = normalize_model_id(provider_name, model_id)

    remaining: list[dict[str, Any]] = []
    removed = False
    for row in models:
        if _model_id_from_row(row) == target_id:
            removed = True
            continue
        remaining.append(row)

    if not removed:
        cli_bail(f"unknown model {target_id!r} on provider {provider_name!r}")

    entry["models"] = remaining
    entries[provider_idx] = entry
    data["providers"] = entries
    write_config_dict(config_path, data)
    console.print(
        f"deleted model [green]{target_id}[/green] from provider [green]{provider_name}[/green]"
    )


__all__ = ["app"]
