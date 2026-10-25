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
so a reviewed fork cannot load code into the harness. Only a plugin copy whose
runtime entry provably reads ``captureContent`` is loaded, at every content level:
an older or unknown copy would ignore it and export bodies unredacted. Header values
are decoded as the Python OTLP exporter decodes them and never reach the config file
on disk: each one rides an env var the config references as ``{env:NAME}``, and the
same references feed the plugin's ``redactValues`` so a credential echoed into a
prompt or tool body is masked.

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
# Suffix of the env var holding a ``Scheme credential`` header's bare credential.
_CREDENTIAL_ENV_SUFFIX: Final[str] = "_CREDENTIAL"
_TRACES_SUFFIX: Final[str] = "/v1/traces"
_CAPTURE_OPTION: Final[str] = "captureContent"
# Package-entry conditions in the order Bun (OpenCode's runtime) resolves them.
_ENTRY_CONDITIONS: Final[tuple[str, ...]] = ("bun", "import", "default", "node", "require")
# Beside the runtime entry, the module that declares the plugin's options.
_CONFIG_MODULES: Final[tuple[str, ...]] = ("config.ts", "config.js", "config.mjs")
# The plugin's ``redactValues`` ignores anything shorter.
_MIN_REDACT_LENGTH: Final[int] = 6
# Characters a forwarded header value cannot carry: the plugin splits
# ``otlpHeaders`` on ``,`` and the value is substituted into a JSON config.
_UNFORWARDABLE_HEADER_CHARS: Final[frozenset[str]] = frozenset(',"\\\r\n')

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
    """Parse an ``OTEL_EXPORTER_OTLP_*HEADERS`` value as the Python exporter does.

    The exporter URL-decodes names and values (``Bearer%20tok`` is sent as
    ``Bearer tok``) and lowercases names; the plugin forwards what it is given
    verbatim, so the decoding happens here or the plugin authenticates with a
    different credential than mergeCraft's own spans.
    """
    from opentelemetry.util.re import parse_env_headers

    return dict(parse_env_headers(raw or "", liberal=True))


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


def _export_target(value: Any) -> str | None:
    """The file an ``exports`` value names under Bun's condition order."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for condition in _ENTRY_CONDITIONS:
            if condition in value:
                return _export_target(value[condition])
    return None


def _runtime_entry(root: Path) -> Path | None:
    """The file OpenCode imports for the plugin package at ``root``, if it can be named.

    Read from ``package.json`` (``exports["."]``, then ``module``, then ``main``),
    the same fields the runtime resolves. ``None`` when there is no manifest or
    the named file does not exist.
    """
    try:
        manifest = json.loads((root / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(manifest, dict):
        return None
    exports = manifest.get("exports")
    if isinstance(exports, dict) and "." in exports:
        exports = exports["."]
    target = _export_target(exports) or manifest.get("module") or manifest.get("main")
    if not isinstance(target, str):
        return None
    entry = (root / target).resolve()
    if not entry.is_file() or not entry.is_relative_to(root.resolve()):
        return None
    return entry


def _supports_capture_content(package: str) -> bool:
    """Whether the plugin code OpenCode will load at ``package`` honours ``captureContent``.

    An older or unknown plugin ignores the option (and may not redact), so only a
    copy that provably reads it is loaded, whatever this run's content level. The
    proof comes from the runtime entry ``package.json`` names and the config module
    beside it, never from source the runtime does not import: a checkout pulled
    but not rebuilt has new ``src/`` and a stale ``dist/`` that exports bodies.
    Only a directory can be checked; a bare package spec cannot, and reads as
    unsupported.
    """
    entry = _runtime_entry(Path(package).expanduser())
    if entry is None:
        return False
    for path in (entry, *(entry.parent / name for name in _CONFIG_MODULES)):
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
    redact_refs: list[str] = []
    env: dict[str, str] = {}
    for index, (name, value) in enumerate(_effective_headers(target.headers).items()):
        if _UNFORWARDABLE_HEADER_CHARS.intersection(name + value) or "=" in name:
            # Forwarding it mangled would leave the plugin's exports failing auth
            # while mergeCraft's own spans keep arriving.
            logger.warning(
                "opencode otel plugin: OTLP header {!r} cannot be forwarded intact; not enabling",
                name,
            )
            return None
        env_name = f"{_HEADER_ENV_PREFIX}{index}"
        env[env_name] = value
        header_refs.append(f"{name}={{env:{env_name}}}")
        # Every forwarded value is a literal for the plugin's redactor: under
        # ``redacted`` the plugin exports bodies, and the renamed env var hides the
        # credential from its secret-name scan (an opaque API key has no telltale
        # prefix either). ``Scheme credential`` values register the bare credential
        # too, since that is what gets echoed. Env refs keep both off disk.
        if len(value) >= _MIN_REDACT_LENGTH:
            redact_refs.append(f"{{env:{env_name}}}")
        scheme, _, credential = value.partition(" ")
        if scheme and len(credential.strip()) >= _MIN_REDACT_LENGTH:
            credential_env = f"{env_name}{_CREDENTIAL_ENV_SUFFIX}"
            env[credential_env] = credential.strip()
            redact_refs.append(f"{{env:{credential_env}}}")

    capture = resolve_capture_policy(trust_tier)
    if not _supports_capture_content(package):
        # Required at every level, not only when bodies are withheld: under the default
        # ``redacted`` the plugin must also redact, and a copy that cannot be shown to
        # honour these options may export every prompt and tool body verbatim.
        logger.warning(
            "opencode otel plugin: {} does not support captureContent; not enabling "
            "(this run's content policy is {})",
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
    if redact_refs:
        options["redactValues"] = redact_refs
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
