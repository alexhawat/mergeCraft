"""Shared helpers for BA #477 provider-registry CLI tests."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest
import yaml

PROVIDER_CMD_MODULE = "mergecraft.cli.provider_cmd"
PROVIDER_REGISTRY_MODULE = "mergecraft.config.provider_registry"

BUILTIN_HARNESS_DEFAULTS: dict[str, str] = {
    "openai": "codex",
    "anthropic": "claude",
    "google": "gemini",
    "cursor": "cursor",
}

NOUS_BASE_URL = "https://inference-api.nousresearch.com/v1"
CUSTOM_BASE_URL = "https://gateway.example.invalid/v1"
EXPECTED_BUILTIN_PROVIDER_COUNT = 14


def import_provider_cmd() -> Any:
    """Import ``mergecraft.cli.provider_cmd`` or fail with a clear message."""
    try:
        return importlib.import_module(PROVIDER_CMD_MODULE)
    except ImportError as exc:
        pytest.fail(f"{PROVIDER_CMD_MODULE} is not implemented yet: {exc}")


def import_provider_registry() -> Any:
    """Import ``mergecraft.config.provider_registry`` or fail with a clear message."""
    try:
        return importlib.import_module(PROVIDER_REGISTRY_MODULE)
    except ImportError as exc:
        pytest.fail(f"{PROVIDER_REGISTRY_MODULE} is not implemented yet: {exc}")


def scaffold_mergecraft_home(tmp_path: Path, *, config_body: str = "") -> Path:
    """Create ``.mergecraft/config.yaml`` under *tmp_path* and return the config path."""
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    path = cfg_dir / "config.yaml"
    body = config_body.strip()
    path.write_text((body + "\n") if body else "models: []\n", encoding="utf-8")
    return path


def read_config(tmp_path: Path) -> dict[str, Any]:
    """Load ``.mergecraft/config.yaml`` as a dict."""
    path = tmp_path / ".mergecraft" / "config.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def read_env_file(tmp_path: Path) -> dict[str, str]:
    """Parse ``.env`` key/value pairs (simple ``KEY=value`` lines only)."""
    path = tmp_path / ".env"
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def provider_entries(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the ``providers`` list from a config dict."""
    providers = config.get("providers")
    if providers is None:
        return []
    assert isinstance(providers, list)
    return [entry for entry in providers if isinstance(entry, dict)]
