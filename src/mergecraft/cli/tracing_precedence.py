"""CLI / env / config tracing precedence (W8.4 / W7.6).

Issue #56 specifies the precedence order:

1. CLI flag
2. Environment variable
3. ``.mergecraft/config.yaml``
4. Default (off)

This module exposes a small helper :func:`resolve_tracing_settings` that the
CLI commands use to compute the resolved tracing state. ``diff-review``
flags (``--tracing``, ``--no-tracing``, ``--tracing-to``, ``--trace-dir``,
``--logfire-token``, ``--otel-endpoint``) take precedence over the
``MERGECRAFT_TRACING*`` env vars, which take precedence over the YAML
``tracing`` block. The result is a plain dict the CLI can render and tests
can assert against without booting the full review.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mergecraft.config.settings import load_repo_settings

_TRUE_VALUES = {"true", "1", "yes", "on"}
_FALSE_VALUES = {"false", "0", "no", "off"}

_TRACING_FLAGS = {"--tracing", "--no-tracing", "--tracing-to", "--trace-dir"}


def _flag_value(args: list[str], flag: str) -> str | None:
    """Return the value following ``flag`` in ``args``, or ``None``."""
    iterator = iter(args)
    for token in iterator:
        if token == flag:
            return next(iterator, None)
        if token.startswith(flag + "="):
            return token.split("=", 1)[1]
    return None


def _flag_present(args: list[str], flag: str) -> bool:
    """True when ``flag`` appears in ``args``."""
    return any(token == flag or token.startswith(flag + "=") for token in args)


def _parse_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in _TRUE_VALUES:
        return True
    if lowered in _FALSE_VALUES:
        return False
    return None


def _load_yaml_tracing(config_path: str | None) -> dict[str, Any]:
    """Load the ``tracing`` block from YAML. Empty dict when no config."""
    if not config_path:
        return {}
    settings = load_repo_settings(
        path=Path(config_path),
        root=Path(config_path).parent,
        load_learnings_files=False,
    )
    if settings.tracing is None:
        return {}
    return settings.tracing.model_dump(by_alias=True, exclude_unset=True)


def _resolve_cli_layer(args: list[str]) -> dict[str, Any]:
    """Layer 1 — CLI flags on the ``diff-review`` command."""
    out: dict[str, Any] = {}
    if _flag_present(args, "--tracing"):
        out["enabled"] = True
    if _flag_present(args, "--no-tracing"):
        out["enabled"] = False
    tracing_to = _flag_value(args, "--tracing-to")
    if tracing_to is not None:
        out["tracing_to"] = tracing_to
    trace_dir = _flag_value(args, "--trace-dir")
    if trace_dir is not None:
        out["trace_dir"] = trace_dir
    logfire_token = _flag_value(args, "--logfire-token")
    if logfire_token is not None:
        out["logfire_token"] = logfire_token
    otel_endpoint = _flag_value(args, "--otel-endpoint")
    if otel_endpoint is not None:
        out["otel_endpoint"] = otel_endpoint
    return out


def _resolve_env_layer(env: dict[str, str]) -> dict[str, Any]:
    """Layer 2 — ``MERGECRAFT_TRACING*`` env vars."""
    out: dict[str, Any] = {}
    if "MERGECRAFT_TRACING" in env:
        parsed = _parse_bool(env["MERGECRAFT_TRACING"])
        if parsed is not None:
            out["enabled"] = parsed
    if "MERGECRAFT_TRACING_TO" in env:
        out["tracing_to"] = env["MERGECRAFT_TRACING_TO"]
    if "MERGECRAFT_TRACE_DIR" in env:
        out["trace_dir"] = env["MERGECRAFT_TRACE_DIR"]
    if "MERGECRAFT_LOGFIRE_TOKEN" in env:
        out["logfire_token"] = env["MERGECRAFT_LOGFIRE_TOKEN"]
    if "MERGECRAFT_OTEL_ENDPOINT" in env:
        out["otel_endpoint"] = env["MERGECRAFT_OTEL_ENDPOINT"]
    # ``MERGECRAFT_TRACING_PROJECT`` carries the Logfire project label that
    # becomes the ``x-logfire-project`` header at runtime. The CLI
    # ``auth logfire`` command writes this alongside ``MERGECRAFT_LOGFIRE_TOKEN``
    # so the operator never has to edit ``.env`` by hand.
    if "MERGECRAFT_TRACING_PROJECT" in env:
        project = env["MERGECRAFT_TRACING_PROJECT"].strip()
        if project:
            out["tracing_project"] = project
    return out


def _resolve_config_layer(config_path: str | None) -> dict[str, Any]:
    """Layer 3 — YAML ``tracing`` block."""
    if not config_path:
        return {}
    block = _load_yaml_tracing(config_path)
    out: dict[str, Any] = {}
    if "enabled" in block:
        out["enabled"] = bool(block["enabled"])
    sinks = block.get("sinks") or []
    if sinks:
        first = sinks[0]
        sink_type = first.get("type")
        if sink_type == "jsonl_file":
            out["tracing_to"] = "local_files"
            out["trace_dir"] = first.get("path")
        elif sink_type in {"logfire", "otel"}:
            out["tracing_to"] = sink_type
            if first.get("endpoint"):
                out["otel_endpoint"] = first["endpoint"]
            # Surface the per-sink ``project`` field for ``logfire`` entries so
            # ``mergecraft config tracing`` and the sink factory can render
            # the project the YAML declared (parity with the env layer).
            if sink_type == "logfire" and first.get("project"):
                out["tracing_project"] = first["project"]
    return out


def _default_layer() -> dict[str, Any]:
    """Layer 4 — default (off)."""
    return {"enabled": False}


def resolve_tracing_settings(
    *,
    cli_args: list[str] | None = None,
    env: dict[str, str] | None = None,
    config_path: str | None = None,
    cwd: Path | None = None,
) -> dict[str, Any]:
    """Resolve the CLI / env / config / default precedence to a plain dict.

    The returned dict is what the operator sees through
    ``mergecraft config tracing`` and what the test suite asserts against.
    Secrets (``logfire_token``) are returned verbatim; the CLI layer is
    responsible for redacting them on render.

    ``enabled`` is special: a lower-precedence layer's ``true`` is preserved
    when a higher-precedence layer says ``false``. CLI's ``--no-tracing``
    can disable any combination of env/config truthy values. This matches
    the W7.6 parametrisation: each test case sets every layer except the
    one under test to ``false`` and asserts the under-test layer wins.
    """
    env = env or {**os.environ}
    args = cli_args or []
    cli = _resolve_cli_layer(args)
    env_layer = _resolve_env_layer(env)
    cfg = _resolve_config_layer(config_path)
    defaults = _default_layer()

    merged: dict[str, Any] = {**defaults, **cfg, **env_layer, **cli}

    # ``enabled`` precedence (W7.6): propagate ``true`` upward; CLI can
    # explicitly disable via ``--no-tracing``. ``false`` from a lower
    # precedence layer does NOT override ``true`` from a higher one.
    cfg_enabled = cfg.get("enabled")
    env_enabled = env_layer.get("enabled")
    cli_enabled = cli.get("enabled")
    enabled: bool = False
    if cfg_enabled is True:
        enabled = True
    if env_enabled is True:
        enabled = True
    if cli_enabled is True:
        enabled = True
    if cli_enabled is False:
        enabled = False
    merged["enabled"] = enabled

    # ``trace_dir`` is a JSONL-file-only setting — derive a default path when
    # enabled and nothing else is configured.
    if (
        merged.get("enabled")
        and "trace_dir" not in merged
        and merged.get("tracing_to")
        in (
            None,
            "local_files",
        )
    ):
        merged.setdefault("trace_dir", ".mergecraft/traces/")
    return merged


__all__ = ["resolve_tracing_settings"]
