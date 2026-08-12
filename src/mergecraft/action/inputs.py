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


def _parse_bool(value: str | None) -> bool | None:
    """Parse a tri-state bool string (true / false / unset-or-garbage → None).

    Unset and unrecognized values return ``None`` so callers can distinguish
    "defer to the next precedence layer" from an explicit ``false`` (W6.4).
    """
    if value is None or value == "":
        return None
    lowered = value.strip().lower()
    if lowered in {"true", "1", "yes", "on"}:
        return True
    if lowered in {"false", "0", "no", "off"}:
        return False
    return None


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
            "enabled": bool | None,
            "sinks": [{"type": "jsonl_file", "path": "..."}] | [{"type": "logfire"}] | ...,
            "logfire_token": str | None,
            "otel_endpoint": str | None,
            "settings": TracingSettings,
        }

    ``enabled`` is ``None`` when ``INPUT_TRACING`` is unset — that preserves
    the next precedence layer (env → YAML → default). The dict is consumed by
    ``mergecraft config tracing`` and by :func:`apply_tracing_overrides` on
    the live Action path (W6.4). The ``logfire_token`` field is the resolved
    value when the action input was provided — ``TracingSettings`` does
    **not** carry it (D5).
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


def apply_tracing_overrides(settings: Any) -> Any:
    """Apply Action-input / env tracing onto ``RepoSettings`` (W6.4).

    Precedence: action input (``INPUT_TRACING*``) > ``MERGECRAFT_TRACING`` env
    > YAML ``tracing:`` block > default (``enabled=None`` → tracer treats as off).
    Unset layers do not force ``False``.
    """
    from mergecraft.config.settings import RepoSettings

    if not isinstance(settings, RepoSettings):
        return settings

    resolved = resolve_tracing_from_action_inputs()
    enabled: bool | None = resolved["enabled"]
    if enabled is None:
        enabled = _parse_bool(os.environ.get("MERGECRAFT_TRACING"))
    if enabled is None:
        return settings

    update: dict[str, Any] = {"enabled": enabled}
    action_settings = resolved["settings"]
    if isinstance(action_settings, TracingSettings) and action_settings.sinks:
        update["sinks"] = action_settings.sinks
    new_tracing = settings.tracing.model_copy(update=update)
    return settings.model_copy(update={"tracing": new_tracing})


__all__ = ["apply_tracing_overrides", "resolve_tracing_from_action_inputs"]
