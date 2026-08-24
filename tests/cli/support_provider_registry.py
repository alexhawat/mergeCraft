"""Shared helpers for BA #477 provider-registry CLI tests."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest
import yaml

PROVIDER_CMD_MODULE = "mergecraft.cli.provider_cmd"
MODEL_CMD_MODULE = "mergecraft.cli.model_cmd"
PROVIDER_REGISTRY_MODULE = "mergecraft.config.provider_registry"
MODEL_REGISTRY_MODULE = "mergecraft.config.model_registry"

BUILTIN_HARNESS_DEFAULTS: dict[str, str] = {
    "openai": "codex",
    "anthropic": "claude",
    "google": "gemini",
    "cursor": "cursor",
}

NOUS_BASE_URL = "https://inference-api.nousresearch.com/v1"
CUSTOM_BASE_URL = "https://gateway.example.invalid/v1"
EXPECTED_BUILTIN_PROVIDER_COUNT = 14

# BB #478 — unified ``provider auth`` contracts (D6-D7, D10).

AUTH_KIND_API_KEY = "api_key"
AUTH_KIND_OAUTH = "oauth"
AUTH_KIND_DEVICE_CODE = "device_code"
AUTH_KIND_CLOUD_CHAIN = "cloud_chain"

LEGACY_AUTH_SUBCOMMANDS: tuple[str, ...] = (
    "codex",
    "claude",
    "gemini",
    "cursor",
    "nous",
    "tokenhub",
    "minimax",
)

AUTH_KIND_PRIMARY_SUFFIX: dict[str, str] = {
    AUTH_KIND_API_KEY: "API_KEY",
    AUTH_KIND_OAUTH: "CLAUDE_CODE_OAUTH_TOKEN",
    AUTH_KIND_DEVICE_CODE: "CODEX_AUTH_JSON",
}

BEDROCK_INDEXED_KEYS: tuple[str, ...] = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
)

VERTEX_INDEXED_KEYS: tuple[str, ...] = ("GOOGLE_APPLICATION_CREDENTIALS",)

EXPECTED_SEEDED_AUTH_KINDS: dict[str, str] = {
    "openai": AUTH_KIND_DEVICE_CODE,
    "anthropic": AUTH_KIND_OAUTH,
    "google": AUTH_KIND_API_KEY,
    "cursor": AUTH_KIND_API_KEY,
    "nous": AUTH_KIND_API_KEY,
    "tokenhub": AUTH_KIND_API_KEY,
    "minimax": AUTH_KIND_API_KEY,
    "bedrock": AUTH_KIND_CLOUD_CHAIN,
    "vertex": AUTH_KIND_CLOUD_CHAIN,
}


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


def import_model_cmd() -> Any:
    """Import ``mergecraft.cli.model_cmd`` or fail with a clear message."""
    try:
        return importlib.import_module(MODEL_CMD_MODULE)
    except ImportError as exc:
        pytest.fail(f"{MODEL_CMD_MODULE} is not implemented yet: {exc}")


def import_model_registry() -> Any:
    """Import ``mergecraft.config.model_registry`` or fail with a clear message."""
    try:
        return importlib.import_module(MODEL_REGISTRY_MODULE)
    except ImportError as exc:
        pytest.fail(f"{MODEL_REGISTRY_MODULE} is not implemented yet: {exc}")


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


def indexed_env_key(env_index: int, suffix: str) -> str:
    """Return ``LLM_PROVIDER_<N>_<SUFFIX>`` per #478."""
    return f"LLM_PROVIDER_{env_index}_{suffix}"


def write_provider_entry(
    tmp_path: Path,
    *,
    label: str,
    env_index: int,
    harness: str = "opencode",
    auth_kind: str = AUTH_KIND_API_KEY,
    url: str | None = None,
) -> None:
    """Append one provider row to ``.mergecraft/config.yaml`` (BB auth fixtures)."""
    config = read_config(tmp_path)
    entries = provider_entries(config)
    entry: dict[str, Any] = {
        "label": label,
        "harness": harness,
        "envIndex": env_index,
        "authKind": auth_kind,
    }
    if url is not None:
        entry["url"] = url
    entries.append(entry)
    config["providers"] = entries
    path = tmp_path / ".mergecraft" / "config.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


def require_provider_auth_symbols() -> Any:
    """Import ``provider_cmd`` and require BB auth helpers to exist."""
    module = import_provider_cmd()
    for name in (
        "indexed_credential_keys",
        "resolve_auth_strategy",
        "provider_auth_cmd",
    ):
        if not hasattr(module, name):
            pytest.fail(f"{PROVIDER_CMD_MODULE}.{name} is not implemented")
    return module


def provider_entry(config: dict[str, Any], label: str) -> dict[str, Any] | None:
    """Return the provider registry row for *label*, if present."""
    lowered = label.strip().lower()
    for entry in provider_entries(config):
        if str(entry.get("label", "")).lower() == lowered:
            return entry
    return None


def provider_model_entries(config: dict[str, Any], label: str) -> list[dict[str, Any]]:
    """Return model rows under the provider *label* in config."""
    entry = provider_entry(config, label)
    if entry is None:
        return []
    models = entry.get("models")
    if models is None:
        return []
    assert isinstance(models, list)
    return [row for row in models if isinstance(row, dict)]


def model_id_value(row: dict[str, Any]) -> str:
    """Extract the stored model id from a config model row."""
    for key in ("id", "modelId", "model"):
        value = row.get(key)
        if value is not None:
            return str(value)
    return ""


def model_index_value(row: dict[str, Any]) -> int | None:
    """Extract ``modelIndex`` from a config model row."""
    raw = row.get("modelIndex")
    if raw is None:
        return None
    return int(raw)
