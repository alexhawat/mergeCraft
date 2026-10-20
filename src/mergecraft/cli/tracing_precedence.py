"""CLI / env / config tracing precedence (W8.4 / W7.6).

Issue #56 specifies the precedence order:

1. CLI flag
2. Environment variable
3. ``.mergecraft/config.yaml``
4. Default (off)

This module exposes a small helper :func:`resolve_tracing_settings` that the
CLI commands use to compute the resolved tracing state. ``diff-review``
flags (``--tracing``, ``--no-tracing``, ``--tracing-to``, ``--trace-dir``,
``--logfire-token``, ``--otel-endpoint``, ``--tracing-content``,
``--tracing-export-untrusted-content``) take precedence over the
``MERGECRAFT_TRACING*`` env vars, which take precedence over the YAML
``tracing`` block. The result is a plain dict the CLI can render and tests
can assert against without booting the full review.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mergecraft.config.env.tracing import TracingEnv
from mergecraft.config.layered import ConfigSources, resolve_config_sources
from mergecraft.config.settings import load_repo_settings
from mergecraft.config.tracing_sink import check_tracing_sink


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


def tracing_config_sources(*, config_path: str | None, root: Path) -> ConfigSources:
    """Return the config files the YAML tracing layer reads, lowest precedence first.

    An explicit ``config_path`` (the ``--config`` flag) wins before the shared
    resolver is consulted, exactly as for ``doctor`` and ``config explain``: it is
    the sole contributor when it exists, and nothing contributes when it does not.
    Without one, :func:`mergecraft.config.layered.resolve_config_sources` decides —
    ``MERGECRAFT_CONFIG`` when it names an existing file, else the committed
    ``.mergecraft/config.yaml`` plus ``config.local.yaml`` off CI — so this view
    can never disagree with the other read views about which files contribute.
    """
    if config_path:
        candidate = Path(config_path)
        return ConfigSources(files=(candidate.resolve(),) if candidate.is_file() else ())
    return resolve_config_sources(root)


def _load_yaml_tracing(config_path: str | None, *, root: Path | None = None) -> dict[str, Any]:
    """Load the ``tracing`` block from YAML. Empty dict when no config.

    An explicit ``config_path`` is read on its own. With no path and a ``root``,
    the layered loader reads the same files :func:`tracing_config_sources` reports.
    With neither, nothing is read: the live sink path is handed its YAML layer
    explicitly and must never start discovering one by itself.
    """
    if config_path:
        settings = load_repo_settings(
            path=Path(config_path),
            root=Path(config_path).parent,
            load_learnings_files=False,
        )
    elif root is not None:
        settings = load_repo_settings(root=root, load_learnings_files=False)
    else:
        return {}
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
    region = _flag_value(args, "--region")
    if region is not None:
        out["region"] = region.strip().lower()
    tracing_content = _flag_value(args, "--tracing-content")
    if tracing_content is not None:
        out["content"] = tracing_content
    if _flag_present(args, "--tracing-export-untrusted-content"):
        out["export_untrusted_content"] = True
    if _flag_present(args, "--no-tracing-export-untrusted-content"):
        out["export_untrusted_content"] = False
    return out


def _resolve_env_layer(env: dict[str, str]) -> dict[str, Any]:
    """Layer 2 — ``MERGECRAFT_TRACING*`` env vars, read through ``TracingEnv``.

    Key presence is preserved exactly as before: an absent variable is omitted,
    a present-but-empty pass-through variable (``MERGECRAFT_TRACING_TO``,
    ``MERGECRAFT_TRACE_DIR``, ``MERGECRAFT_LOGFIRE_TOKEN``,
    ``MERGECRAFT_OTEL_ENDPOINT``) keeps its empty value, and the
    control-carrying variables (enable flag, region, content level,
    untrusted-content export) omit an empty value. A non-empty unknown value on
    a control-carrying variable fails closed inside the model instead of being
    dropped. ``logfire_token`` leaves this boundary as a plain ``str``.
    """
    model = TracingEnv.from_env(env)
    out: dict[str, Any] = {}
    if model.tracing_enabled is not None:
        out["enabled"] = model.tracing_enabled
    if model.tracing_to is not None:
        out["tracing_to"] = model.tracing_to
    if model.trace_dir is not None:
        out["trace_dir"] = model.trace_dir
    if model.logfire_token is not None:
        out["logfire_token"] = model.logfire_token.get_secret_value()
    if model.otel_endpoint is not None:
        out["otel_endpoint"] = model.otel_endpoint
    # ``MERGECRAFT_TRACING_PROJECT`` carries the Logfire project label. This is
    # informational only — Logfire routes spans by the token itself, not a
    # header. The CLI ``auth logfire`` command writes this alongside
    # ``MERGECRAFT_LOGFIRE_TOKEN`` so the operator never has to edit ``.env``
    # by hand.
    if model.tracing_project is not None:
        out["tracing_project"] = model.tracing_project
    # ``MERGECRAFT_TRACING_REGION`` selects the Logfire OTLP data region
    # (``us`` / ``eu``). Logfire routes spans to region-specific ingest
    # endpoints; this overrides the YAML ``region`` default (``us``). The
    # CLI ``--region`` flag (``tracing logfire enable``) sits above this in
    # the precedence stack via the merged dict.
    if model.tracing_region is not None:
        out["region"] = model.tracing_region
    if model.tracing_content is not None:
        out["content"] = model.tracing_content
    if model.export_untrusted_content is not None:
        out["export_untrusted_content"] = model.export_untrusted_content
    return out


def _resolve_config_layer(config_path: str | None, *, root: Path | None = None) -> dict[str, Any]:
    """Layer 3 — YAML ``tracing`` block."""
    if not config_path and root is None:
        return {}
    block = _load_yaml_tracing(config_path, root=root)
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
    if "content" in block:
        out["content"] = block["content"]
    export_untrusted = block.get("exportUntrustedContent", block.get("export_untrusted_content"))
    if export_untrusted is not None:
        out["export_untrusted_content"] = bool(export_untrusted)
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
    config_root: Path | None = None,
    warn_unknown_sink: bool = False,
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

    ``config_root`` opts the YAML layer into shared config discovery for a read
    view (``mergecraft config tracing``): with no explicit ``config_path`` the
    layer reads the files :func:`tracing_config_sources` reports for that root.
    It never changes the ordering above, and leaving it ``None`` keeps the live
    sink path reading only the YAML it is handed.

    An unknown ``tracing_to`` shorthand from the flag or the environment raises
    :class:`~mergecraft.config.tracing_sink.TracingSinkError` (a configuration
    failure) when tracing resolves on; with tracing off it is ignored, and logs a
    warning only when ``warn_unknown_sink`` is set, so the many resolutions a live
    run makes do not repeat it.
    """
    env = env or {**os.environ}
    args = cli_args or []
    cli = _resolve_cli_layer(args)
    env_layer = _resolve_env_layer(env)
    cfg = _resolve_config_layer(config_path, root=config_root)
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

    # The sink selector is control-carrying: a typo must not silently fall through
    # to the default local sink. The YAML layer only emits known shorthands, so only
    # the flag and the environment can carry an unknown one.
    if "tracing_to" in cli:
        sink_variable = "--tracing-to"
    elif "tracing_to" in env_layer:
        sink_variable = "MERGECRAFT_TRACING_TO"
    else:
        sink_variable = ""
    if sink_variable:
        check_tracing_sink(
            sink_variable,
            merged.get("tracing_to"),
            enabled=enabled,
            warn=warn_unknown_sink,
        )

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


__all__ = ["resolve_tracing_settings", "tracing_config_sources"]
