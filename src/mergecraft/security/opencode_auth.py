"""OpenCode Zen / Go credential helpers (billing-backed API keys in auth.json shape)."""

from __future__ import annotations

import json
from typing import Final

_ZEN_INTEGRATION_IDS: Final[tuple[str, ...]] = ("opencode", "opencode-go")


def opencode_auth_usable(raw: str) -> bool:
    """Return whether *raw* is usable OpenCode ``auth.json`` content."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return False
    if not isinstance(data, dict):
        return False
    for integration_id in _ZEN_INTEGRATION_IDS:
        entry = data.get(integration_id)
        if not isinstance(entry, dict):
            continue
        if entry.get("type") != "api":
            continue
        key = entry.get("key")
        if isinstance(key, str) and key.strip():
            return True
    return False


def opencode_api_key_from_auth_json(raw: str) -> str | None:
    """Extract the first Zen/Go API key from stored ``auth.json`` JSON."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    for integration_id in _ZEN_INTEGRATION_IDS:
        entry = data.get(integration_id)
        if not isinstance(entry, dict):
            continue
        key = entry.get("key")
        if isinstance(key, str) and key.strip():
            return key.strip()
    return None


def build_opencode_zen_auth_json(api_key: str) -> str:
    """Build minimal ``auth.json`` content for OpenCode Zen and Go."""
    stripped = api_key.strip()
    payload = {
        integration_id: {"type": "api", "key": stripped} for integration_id in _ZEN_INTEGRATION_IDS
    }
    return json.dumps(payload, separators=(",", ":"))


__all__ = [
    "build_opencode_zen_auth_json",
    "opencode_api_key_from_auth_json",
    "opencode_auth_usable",
]
