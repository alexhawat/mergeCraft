"""Generalized CLI / env / YAML / default precedence for config keys (CC2).

Tracing keeps its dedicated resolver in :mod:`mergecraft.cli.tracing_precedence`;
this module generalizes the same precedence story for operator-facing
``mergecraft config show`` and ``mergecraft config explain`` without
duplicating the tracing arithmetic.
"""

from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

from mergecraft.cli.tracing_precedence import resolve_tracing_settings
from mergecraft.config.io import committed_config_path
from mergecraft.config.layered import (
    load_layered_config_dict,
    local_config_path,
    merge_config_dicts,
    running_in_github_actions,
)
from mergecraft.config.settings import _DEFAULT_CONFIG_REL, default_settings, load_repo_settings
from mergecraft.utils.agent_resolve import configured_model_slugs, resolve_effective_model_slug

_TRUE_VALUES = {"true", "1", "yes", "on"}
_FALSE_VALUES = {"false", "0", "no", "off"}


class ConfigLayer(StrEnum):
    """Precedence layer — highest wins."""

    CLI = "cli"
    ENV = "environment"
    YAML = "yaml"
    DEFAULT = "default"


_LAYER_RANK = {
    ConfigLayer.CLI: 0,
    ConfigLayer.ENV: 1,
    ConfigLayer.YAML: 2,
    ConfigLayer.DEFAULT: 3,
}


def _config_path(cwd: Path) -> Path | None:
    env_path = os.environ.get("MERGECRAFT_CONFIG")
    if env_path:
        candidate = Path(env_path)
        if candidate.is_file():
            return candidate
    candidate = cwd / _DEFAULT_CONFIG_REL
    return candidate if candidate.is_file() else None


def _load_yaml_raw(config_path: Path | None) -> dict[str, Any]:
    if config_path is None or not config_path.is_file():
        return {}
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        msg = f"config must be a mapping: {config_path}"
        raise ValueError(msg)
    return loaded


def _parse_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in _TRUE_VALUES:
        return True
    if lowered in _FALSE_VALUES:
        return False
    return None


def _resolve_model_layers(*, cwd: Path, cli_model: str | None = None) -> dict[ConfigLayer, Any]:
    layers: dict[ConfigLayer, Any] = {}
    if cli_model:
        layers[ConfigLayer.CLI] = cli_model
    env_model = os.environ.get("MERGECRAFT_MODEL")
    if env_model:
        layers[ConfigLayer.ENV] = env_model.strip()
    settings = load_repo_settings(root=cwd, load_learnings_files=False)
    yaml_slugs = configured_model_slugs(settings)
    if yaml_slugs:
        layers[ConfigLayer.YAML] = yaml_slugs[0]
    layers[ConfigLayer.DEFAULT] = resolve_effective_model_slug(settings)
    return layers


def _resolve_tracing_enabled_layers(
    *,
    cwd: Path,
    cli_args: list[str] | None = None,
    config_path: Path | None = None,
) -> dict[ConfigLayer, Any]:
    resolved = resolve_tracing_settings(
        cli_args=cli_args or [],
        env={**os.environ},
        config_path=str(config_path) if config_path else None,
        cwd=cwd,
    )
    layers: dict[ConfigLayer, Any] = {}
    raw = _load_yaml_raw(config_path)
    tracing_block = raw.get("tracing")
    if isinstance(tracing_block, dict) and "enabled" in tracing_block:
        layers[ConfigLayer.YAML] = bool(tracing_block["enabled"])
    env_enabled = _parse_bool(os.environ.get("MERGECRAFT_TRACING"))
    if env_enabled is not None:
        layers[ConfigLayer.ENV] = env_enabled
    if cli_args:
        if "--tracing" in cli_args:
            layers[ConfigLayer.CLI] = True
        if "--no-tracing" in cli_args:
            layers[ConfigLayer.CLI] = False
    layers[ConfigLayer.DEFAULT] = False
    winner = ConfigLayer.DEFAULT
    for layer in (ConfigLayer.YAML, ConfigLayer.ENV, ConfigLayer.CLI):
        if layer in layers:
            winner = layer
    if ConfigLayer.CLI in layers and layers[ConfigLayer.CLI] is False:
        winner = ConfigLayer.CLI
    elif resolved.get("enabled"):
        for layer in (ConfigLayer.CLI, ConfigLayer.ENV, ConfigLayer.YAML):
            if layer in layers and layers[layer] is True:
                winner = layer
                break
    layers[winner] = resolved.get("enabled", False)
    return layers


def _winning_layer(layers: dict[ConfigLayer, Any]) -> ConfigLayer:
    present = [layer for layer in ConfigLayer if layer in layers]
    if not present:
        return ConfigLayer.DEFAULT
    return min(present, key=lambda layer: _LAYER_RANK[layer])


def resolve_setting(
    key: str,
    *,
    cwd: Path | None = None,
    cli_args: list[str] | None = None,
    cli_model: str | None = None,
) -> tuple[Any, ConfigLayer]:
    """Return the resolved value and its winning precedence layer."""
    root = (cwd or Path.cwd()).resolve()
    config_path = _config_path(root)
    normalized = key.strip().lower()
    if normalized in {"model", "models"}:
        layers = _resolve_model_layers(cwd=root, cli_model=cli_model)
        winner = _winning_layer(layers)
        return layers.get(winner, resolve_effective_model_slug(default_settings())), winner
    if normalized in {"tracing.enabled", "tracing"}:
        layers = _resolve_tracing_enabled_layers(
            cwd=root, cli_args=cli_args, config_path=config_path
        )
        winner = _winning_layer(layers)
        if normalized == "tracing":
            return resolve_tracing_settings(
                cli_args=cli_args or [],
                env={**os.environ},
                config_path=str(config_path) if config_path else None,
                cwd=root,
            ), winner
        return layers.get(winner, False), winner
    msg = f"unsupported config key for show/explain: {key!r}"
    raise KeyError(msg)


def explain_setting(
    key: str,
    *,
    cwd: Path | None = None,
    cli_args: list[str] | None = None,
    cli_model: str | None = None,
) -> dict[str, Any]:
    """Return resolved value, winning layer, and every layer that contributed."""
    root = (cwd or Path.cwd()).resolve()
    config_path = _config_path(root)
    normalized = key.strip().lower()
    if normalized in {"model", "models"}:
        layers = _resolve_model_layers(cwd=root, cli_model=cli_model)
    elif normalized in {"tracing.enabled", "tracing"}:
        layers = _resolve_tracing_enabled_layers(
            cwd=root, cli_args=cli_args, config_path=config_path
        )
    else:
        msg = f"unsupported config key for show/explain: {key!r}"
        raise KeyError(msg)
    winner = _winning_layer(layers)
    value, _ = resolve_setting(key, cwd=root, cli_args=cli_args, cli_model=cli_model)
    return {
        "key": key,
        "value": value,
        "winner": winner.value,
        "layers": {layer.value: layers[layer] for layer in ConfigLayer if layer in layers},
    }


__all__ = [
    "ConfigLayer",
    "committed_config_path",
    "explain_setting",
    "load_layered_config_dict",
    "local_config_path",
    "merge_config_dicts",
    "resolve_setting",
    "running_in_github_actions",
]
