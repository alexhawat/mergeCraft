"""Per-run wiring for the OpenCode V2 OpenTelemetry plugin (opencode-plugin-otel-v2).

mergeCraft runs OpenCode as a subprocess, so its own spans see one opaque
``llm.call`` per review. The plugin runs inside OpenCode and emits a span per
LLM step and per tool call. When the operator opts in, each OpenCode run gets a
plugin entry that:

- exports to the same OTLP endpoint as mergeCraft's active ``otel`` / ``logfire``
  sink, under the same ``service.name``;
- parents the plugin's root span on the active ``mergecraft.agent.run`` span
  (W3C ``traceparent``), so both halves land in one trace;
- sets ``captureContent`` from :func:`resolve_capture_policy`, so ``tracing.content``
  and the untrusted-tier cap govern the plugin's prompt and tool bodies exactly as
  they govern mergeCraft's own spans;
- tags every plugin span with the review's ``gen_ai.conversation.id``, so the whole
  review is one session in Datadog LLM Observability;
- disables the plugin's logs and metrics (traces only).

Opt-in is operator-only: ``MERGECRAFT_OPENCODE_OTEL_PLUGIN`` names the plugin
package (a directory path or package spec). Repository config never enables it,
so a reviewed fork cannot load code into the harness. When the policy withholds
bodies, only a plugin copy that provably reads ``captureContent`` is loaded: an
older copy would ignore it and export them. Header values never reach
the config file on disk: each one rides an env var the config references as
``{env:NAME}``.

Exports:
    Classes:
        OtelPluginWiring — the plugin config entry plus the env vars it references.
    Functions:
        opencode_otel_plugin_wiring — build the wiring for this run, or None.
        apply_otel_plugin — merge the plugin entry into an OpenCode config JSON.
    Constants:
        OTEL_PLUGIN_ENV — the opt-in env var.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from loguru import logger

from mergecraft.tracing import current_tracer
from mergecraft.tracing.content import ContentCapture
from mergecraft.tracing.exporters import review_conversation_id
from mergecraft.tracing.genai import resolve_capture_policy
from mergecraft.tracing.otel_context import (
    parse_mergecraft_otel_span_id,
    parse_mergecraft_otel_trace_id,
)
from mergecraft.tracing.tracer import active_span_for

__all__ = [
    "OTEL_PLUGIN_ENV",
    "OtelPluginWiring",
    "apply_otel_plugin",
    "opencode_otel_plugin_wiring",
]

OTEL_PLUGIN_ENV: Final[str] = "MERGECRAFT_OPENCODE_OTEL_PLUGIN"
_HEADER_ENV_PREFIX: Final[str] = "MERGECRAFT_OPENCODE_OTLP_HEADER_"
_TRACES_SUFFIX: Final[str] = "/v1/traces"
_CAPTURE_OPTION: Final[str] = "captureContent"
# Where a plugin checkout or install declares its options.
_CAPTURE_SOURCES: Final[tuple[str, ...]] = ("src/config.ts", "dist/config.js")

# mergeCraft's four levels onto the plugin's three. ``redacted`` maps to the
# plugin's ``full``, whose bodies pass through its own secret redaction.
_PLUGIN_CONTENT: Final[dict[ContentCapture, str]] = {
    ContentCapture.OFF: "off",
    ContentCapture.METADATA: "metadata",
    ContentCapture.REDACTED: "full",
    ContentCapture.FULL: "full",
}


@dataclass(frozen=True)
class OtelPluginWiring:
    """The plugin config entry for one OpenCode run, and the env vars it references."""

    entry: dict[str, Any]
    env: dict[str, str] = field(default_factory=dict)


def _sink_otlp_targets(sink: Any) -> list[Any]:
    """Return every ``OTLPSink`` under ``sink`` (through Redacting/Multi wrappers)."""
    from mergecraft.tracing.exporters import OTLPSink

    if isinstance(sink, OTLPSink):
        return [sink]
    inner = getattr(sink, "inner", None)
    if inner is not None:
        return _sink_otlp_targets(inner)
    children = getattr(sink, "sinks", None)
    if isinstance(children, list):
        return [target for child in children for target in _sink_otlp_targets(child)]
    return []


def _parse_header_env(raw: str | None) -> dict[str, str]:
    """Parse an ``OTEL_EXPORTER_OTLP_*HEADERS`` value (``k=v,k=v``)."""
    headers: dict[str, str] = {}
    for pair in (raw or "").split(","):
        key, sep, value = pair.partition("=")
        if sep and key.strip():
            headers[key.strip()] = value.strip()
    return headers


def _effective_headers(sink_headers: dict[str, str]) -> dict[str, str]:
    """The headers the OTLP exporter actually sends for this sink.

    An ``otel`` sink with no configured headers falls back to the standard OTLP
    env vars, exactly as the Python exporter does; the plugin runs in a
    subprocess whose environment mergeCraft filters, so it must be told.
    """
    if sink_headers:
        return dict(sink_headers)
    return _parse_header_env(
        os.environ.get("OTEL_EXPORTER_OTLP_TRACES_HEADERS")
        or os.environ.get("OTEL_EXPORTER_OTLP_HEADERS")
    )


def _traceparent(trace_id: str, span_id: str) -> str | None:
    """W3C ``traceparent`` for a mergeCraft span, in the ids the OTLP sink exports."""
    otel_trace = parse_mergecraft_otel_trace_id(trace_id)
    otel_span = parse_mergecraft_otel_span_id(span_id)
    if not otel_trace or not otel_span:
        return None
    return f"00-{otel_trace:032x}-{otel_span:016x}-01"


def _conversation_id(trace_id: str) -> str | None:
    """The review's ``gen_ai.conversation.id``, matching what the OTLP sink stamps."""
    otel_trace = parse_mergecraft_otel_trace_id(trace_id)
    return review_conversation_id(otel_trace) if otel_trace else None


def _supports_capture_content(package: str) -> bool:
    """Whether the plugin at ``package`` honours ``captureContent``.

    An older plugin ignores the option and exports every body, so a run whose
    policy withholds bodies must only load a copy that provably reads it. Only a
    directory can be checked; a bare package spec cannot, and reads as unsupported.
    """
    root = Path(package).expanduser()
    for rel in _CAPTURE_SOURCES:
        path = root / rel
        try:
            if _CAPTURE_OPTION in path.read_text(encoding="utf-8"):
                return True
        except OSError:
            continue
    return False


def opencode_otel_plugin_wiring(trust_tier: str | None) -> OtelPluginWiring | None:
    """Build the plugin wiring for the current OpenCode run, or ``None``.

    ``None`` — and no change to the run — unless the operator opted in, a
    mergeCraft span is active, and tracing exports to an OTLP sink.

    Args:
        trust_tier (str | None): The run's derived trust tier
            (``tool_state.trust_tier``); ``None`` fails closed to the capped level.

    Returns:
        OtelPluginWiring | None: The plugin entry and its header env vars.
    """
    package = os.environ.get(OTEL_PLUGIN_ENV, "").strip()
    if not package:
        return None
    tracer = current_tracer()
    span = active_span_for(tracer)
    if span is None:
        logger.debug("opencode otel plugin: no active mergeCraft span; not enabling")
        return None
    targets = _sink_otlp_targets(getattr(tracer, "sink", None))
    if not targets:
        logger.info(
            "opencode otel plugin: {} is set but tracing has no otel/logfire sink; not enabling",
            OTEL_PLUGIN_ENV,
        )
        return None
    target = targets[0]
    traceparent = _traceparent(span.trace_id, span.span_id)
    if traceparent is None:
        logger.debug("opencode otel plugin: span ids are not OTel-shaped; not enabling")
        return None

    endpoint = str(target.endpoint)
    if endpoint.endswith(_TRACES_SUFFIX):
        endpoint = endpoint[: -len(_TRACES_SUFFIX)]
    header_refs: list[str] = []
    env: dict[str, str] = {}
    for index, (name, value) in enumerate(_effective_headers(target.headers).items()):
        env_name = f"{_HEADER_ENV_PREFIX}{index}"
        env[env_name] = value
        header_refs.append(f"{name}={{env:{env_name}}}")

    capture = resolve_capture_policy(trust_tier)
    if _PLUGIN_CONTENT[capture] != "full" and not _supports_capture_content(package):
        logger.warning(
            "opencode otel plugin: {} does not support captureContent; not enabling, "
            "because this run's content policy ({}) withholds bodies",
            package,
            capture.value,
        )
        return None
    options: dict[str, Any] = {
        "enabled": True,
        "endpoint": endpoint,
        "protocol": "http/protobuf",
        "resourceAttributes": f"service.name={target.service_name}",
        "traceparent": traceparent,
        "captureContent": _PLUGIN_CONTENT[capture],
        "capturePromptInLogs": False,
        "logsEnabled": False,
        "disabledMetrics": ["all"],
        "redactSecrets": True,
    }
    conversation = _conversation_id(span.trace_id)
    if conversation:
        # The plugin keys its spans by OpenCode session, and a review runs several;
        # this puts them all in the review's single Datadog session.
        options["spanAttributes"] = f"gen_ai.conversation.id={conversation}"
    if header_refs:
        options["otlpHeaders"] = ",".join(header_refs)
    logger.info(
        "opencode otel plugin: exporting to {} (content={})",
        endpoint,
        options["captureContent"],
    )
    return OtelPluginWiring(entry={"package": package, "options": options}, env=env)


def apply_otel_plugin(config_json: str, wiring: OtelPluginWiring) -> str:
    """Return ``config_json`` with the plugin entry in its ``plugins`` list.

    An existing entry for the same package is replaced, so this run's options win
    over a copy of the plugin the operator also lists globally.
    """
    config = json.loads(config_json)
    package = wiring.entry["package"]
    plugins = [
        entry
        for entry in config.get("plugins", [])
        if not (isinstance(entry, dict) and entry.get("package") == package)
    ]
    plugins.append(wiring.entry)
    config["plugins"] = plugins
    return json.dumps(config)
