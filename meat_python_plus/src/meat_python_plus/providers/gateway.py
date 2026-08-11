"""exe.dev managed LLM gateway discovery (Go gateway.go)."""

from __future__ import annotations

import os

import httpx

# Present on exe.dev VMs; tests override via monkeypatch.
EXE_DEV_MARKER_PATH = "/exe.dev"

# Reflection endpoint listing integrations attached to this VM.
REFLECTION_INTEGRATIONS_URL = "https://reflection.int.exe.xyz/integrations"

# Placeholder key for edge-managed credentials on exe.dev gateways.
IMPLICIT_GATEWAY_KEY = "implicit"

_DISCOVERY_TIMEOUT = 5.0


def discover_exe_gateway_base(*, http_client: httpx.Client | None = None) -> str:
    """Return the bare origin of the exe.dev managed LLM gateway, or "" if unavailable."""
    try:
        os.stat(EXE_DEV_MARKER_PATH)
    except OSError:
        return ""

    client = http_client
    owns_client = False
    if client is None:
        client = httpx.Client(timeout=_DISCOVERY_TIMEOUT)
        owns_client = True

    try:
        resp = client.get(REFLECTION_INTEGRATIONS_URL, timeout=_DISCOVERY_TIMEOUT)
        if resp.status_code != 200:
            return ""

        body = resp.json()
        integrations = body.get("integrations") or []
        if not isinstance(integrations, list):
            return ""

        for item in integrations:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "")
            integration_type = str(item.get("type") or "")
            if integration_type != "llm" or not name:
                continue
            host = f"{name}.team.exe.xyz" if item.get("team") else f"{name}.int.exe.xyz"
            return f"https://{host}"
        return ""
    except (httpx.HTTPError, ValueError, TypeError):
        return ""
    finally:
        if owns_client:
            client.close()
