"""Unified tracing resolution — bridge env/CLI/YAML precedence to the live sink.

The precedence arithmetic (CLI > env > ``.mergecraft/config.yaml`` > default)
lives in :func:`mergecraft.cli.tracing_precedence.resolve_tracing_settings`,
which returns a plain dict. That dict fed ``mergecraft config tracing`` and
tests but never reached the actual trace sink — the sink was built only from
``RepoSettings().tracing`` (the YAML block). This module is the single
unification point: it converts the resolved dict into a
:class:`mergecraft.config.settings.TracingSettings` that the existing
``sink_factory`` / ``build_remote_sink`` consume unchanged.

Exports:
    resolve_active_tracing — merged dict → ``TracingSettings`` for the live sink.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from mergecraft.cli.tracing_precedence import resolve_tracing_settings
from mergecraft.config.settings import (
    TraceSinkEntry,
    TracingSettings,
)

if TYPE_CHECKING:
    from pathlib import Path


def _build_sinks(merged: dict[str, Any]) -> list[TraceSinkEntry]:
    """Translate the resolved precedence dict into ``TraceSinkEntry`` objects.

    The dict has at most one "active" destination encoded in ``tracing_to``
    plus optional ``logfire_token`` / ``tracing_project`` / ``otel_endpoint`` /
    ``trace_dir``. We map that single destination onto exactly one sink entry,
    keeping parity with how the YAML ``sinks`` list is consumed downstream
    (one entry → one child sink in ``sink_factory``).
    """
    tracing_to: str | None = merged.get("tracing_to")
    logfire_token: str | None = merged.get("logfire_token")
    tracing_project: str | None = merged.get("tracing_project")
    otel_endpoint: str | None = merged.get("otel_endpoint")
    trace_dir: str | None = merged.get("trace_dir")
    raw_region = merged.get("region")
    region: Literal["us", "eu"] = raw_region if raw_region in ("us", "eu") else "us"

    # A logfire destination is selected when the operator explicitly asked for
    # it, or when a token is present and nothing else overrides the
    # destination. Either way the project + token are forwarded.
    wants_logfire = tracing_to == "logfire" or (
        logfire_token is not None and tracing_to in {None, "logfire"}
    )
    if wants_logfire:
        return [
            TraceSinkEntry(
                type="logfire",
                project=tracing_project,
                region=region,
            )
            # The resolved ``logfire_token`` is forwarded separately via the
            # env-var seam that ``build_remote_sink`` consults
            # (``MERGECRAFT_LOGFIRE_TOKEN``), so it never lands in the model
            # dump / config on disk.
        ]

    if tracing_to == "otel" or (tracing_to is None and otel_endpoint):
        # Explicit ``--tracing-to otel`` *or* an OTel endpoint env var without an
        # explicit destination (``MERGECRAFT_OTEL_ENDPOINT`` implies OTLP).
        return [TraceSinkEntry(type="otel", endpoint=otel_endpoint)]

    # Default destinations:
    # - ``local_files`` (or ``enabled`` with no remote token) → JSONL file sink.
    # - ``None`` + no token (``MERGECRAFT_TRACING=true`` only) → JSONL file sink.
    path = trace_dir or ".mergecraft/traces/"
    return [TraceSinkEntry(type="jsonl_file", path=path)]


def _overlay_logfire_region(
    sinks: list[TraceSinkEntry], merged: dict[str, Any]
) -> list[TraceSinkEntry]:
    """Apply env/CLI ``region`` onto adopted logfire sinks, if present."""
    raw_region = merged.get("region")
    if raw_region not in ("us", "eu"):
        return sinks
    region: Literal["us", "eu"] = raw_region
    return [
        sink.model_copy(update={"region": region}) if sink.type == "logfire" else sink
        for sink in sinks
    ]


def resolve_active_tracing(
    *,
    cli_args: list[str] | None = None,
    env: dict[str, str] | None = None,
    config_path: str | None = None,
    cwd: Path | None = None,
    config: TracingSettings | None = None,
) -> TracingSettings:
    """Resolve the env/CLI/YAML/default precedence into a live ``TracingSettings``.

    The returned object is what ``sink_factory`` / ``claim_sink`` consume, so
    every entry point (the CLI ``diff-review`` command, the agent stream
    tracers, and ``get_tracer_from_settings``) honors ``.env`` tokens and
    ``--tracing-to`` flags instead of reading YAML alone. ``enabled`` is taken
    from the resolved dict (so ``MERGECRAFT_TRACING`` and ``--tracing`` drive
    it), and the sinks are built from the same dict.

    Args:
        cli_args (list[str] | None): ``diff-review`` CLI tokens, highest
            precedence. ``None`` disables the CLI layer.
        env (dict[str, str] | None): Environment to resolve against; defaults
            to ``os.environ`` (so ``MERGECRAFT_*`` vars are picked up).
        config_path (str | None): Explicit path to ``.mergecraft/config.yaml``;
            ``None`` lets the resolver auto-discover via ``cwd``. Ignored when
            ``config`` is supplied (the already-resolved block wins).
        cwd (Path | None): Working directory for config auto-discovery and
            relative ``trace_dir`` resolution.
        config (TracingSettings | None): An already-resolved YAML ``tracing``
            block (e.g. ``RepoSettings().tracing``). When supplied it seeds the
            config layer directly instead of re-reading disk, so an in-memory
            ``RepoSettings`` with tracing enabled keeps emitting spans while
            env/CLI still override it. ``None`` falls back to disk discovery.

    Returns:
        TracingSettings: The fully resolved tracing configuration for the
        live sink.

    Examples:
        >>> from pathlib import Path
        >>> s = resolve_active_tracing(env={"MERGECRAFT_TRACING": "false"})
        >>> s.enabled
        False
    """
    if config is not None:
        # Seed the config layer from the already-resolved block rather than
        # re-reading ``.mergecraft/config.yaml``. The precedence arithmetic
        # still lets CLI/env override ``enabled`` and the destination.
        config_path = None
    merged: dict[str, Any] = resolve_tracing_settings(
        cli_args=cli_args,
        env=env,
        config_path=config_path,
        cwd=cwd,
    )
    if config is not None and not merged.get("enabled"):
        # No env/CLI layer enabled tracing (and no config file on disk was
        # consulted) — adopt the already-resolved YAML block's enablement and
        # sinks so a settings-driven run emits. Env/CLI override takes
        # precedence: when ``merged["enabled"]`` is already True/False from a
        # higher layer, that decision stands and ``_build_sinks`` applies.
        #
        # Region is special: Action enablement arrives via ``INPUT_TRACING``,
        # so ``MERGECRAFT_TRACING`` is often unset even when tracing is on.
        # Still overlay ``MERGECRAFT_TRACING_REGION`` onto logfire sinks so an
        # EU write token is not posted to the US OTLP host.
        return TracingSettings(
            enabled=bool(config.enabled),
            sinks=_overlay_logfire_region(list(config.sinks), merged),
        )
    return TracingSettings(
        enabled=bool(merged.get("enabled")),
        sinks=_build_sinks(merged),
    )


__all__ = ["resolve_active_tracing"]
