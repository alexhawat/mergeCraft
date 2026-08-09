"""Resolve GitHub Action ``INPUT_*`` tracing inputs to ``TracingSettings`` (W8.5 / W7.7).

The four new action inputs — ``tracing``, ``tracing-to``, ``logfire-token``,
``otel-endpoint`` — flow through ``INPUT_TRACING*`` env vars that the Docker
runtime injects. The contract is that each input maps to a deterministic
field on :class:`mergecraft.config.settings.TracingSettings` and that the
existing GitHub auth input (``INPUT_TOKEN``) is never confused with
``INPUT_LOGFIRE_TOKEN``.

``GITHUB_WORKSPACE`` is honoured for the local ``jsonl_file`` sink's path so
the trace files land under the consumer repo, not the Docker CWD.
"""

from __future__ import annotations

import os
from typing import Any, Literal

from mergecraft.config.settings import TraceSinkEntry, TracingSettings

Shorthand = Literal["local_files", "logfire", "otel"]


def _read_input(name: str) -> str | None:
    """Read an ``INPUT_*`` env var injected by the GitHub Actions runtime."""
    value = os.environ.get(name)
    if value is None or value == "":
        return None
    return value


def _parse_bool(value: str | None) -> bool:
    """Parse a ``true`` / ``false`` action input string."""
    if value is None:
        return False
    return value.strip().lower() in {"true", "1", "yes", "on"}


def _resolve_local_path(raw_path: str | None) -> str:
    """Resolve ``local_files`` ``path`` against ``GITHUB_WORKSPACE``."""
    workspace = os.environ.get("GITHUB_WORKSPACE")
    if workspace and raw_path and not raw_path.startswith("/"):
        return f"{workspace.rstrip('/')}/{raw_path.lstrip('./')}".rstrip("/") + "/"
    return raw_path or ".mergecraft/traces/"


def resolve_tracing_from_action_inputs() -> dict[str, Any]:
    """Resolve the four action inputs to a tracing settings dict.

    Returns a dict shaped as::

        {
            "enabled": bool,
            "sinks": [{"type": "jsonl_file", "path": "..."}] | [{"type": "logfire"}] | ...,
            "logfire_token": str | None,
            "otel_endpoint": str | None,
            "settings": TracingSettings,
        }

    The dict is consumed by ``mergecraft config tracing`` (W7.4 redaction)
    and by the CLI precedence layer (W7.6). The ``logfire_token`` field is
    the resolved value when the action input was provided — the
    ``TracingSettings`` does **not** carry it (D5).
    """
    tracing_input = _read_input("INPUT_TRACING")
    tracing_to = _read_input("INPUT_TRACING_TO")
    logfire_token = _read_input("INPUT_LOGFIRE_TOKEN")
    otel_endpoint = _read_input("INPUT_OTEL_ENDPOINT")

    enabled = _parse_bool(tracing_input)
    sinks: list[dict[str, Any]] = []

    if enabled and tracing_to:
        if tracing_to == "local_files":
            sinks.append({"type": "jsonl_file", "path": _resolve_local_path(None)})
        elif tracing_to == "logfire":
            sinks.append({"type": "logfire"})
        elif tracing_to == "otel":
            entry: dict[str, Any] = {"type": "otel"}
            if otel_endpoint:
                entry["endpoint"] = otel_endpoint
            sinks.append(entry)
        else:
            msg = f"unknown tracing-to value: {tracing_to!r}"
            raise ValueError(msg)

    settings = TracingSettings.model_validate(
        {"enabled": enabled, "sinks": [TraceSinkEntry.model_validate(item) for item in sinks]}
    )
    return {
        "enabled": enabled,
        "sinks": sinks,
        "logfire_token": logfire_token,
        "otel_endpoint": otel_endpoint,
        "settings": settings,
    }


__all__ = ["resolve_tracing_from_action_inputs"]
