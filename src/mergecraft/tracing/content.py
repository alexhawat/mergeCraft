"""Content-capture policy for model payloads (OB2 — D6/D7/D8).

Module: mergecraft.tracing.content
Depends: mergecraft.analyzers.redact, mergecraft.tracing.cap, loguru

Bodies (prompts, completions, reasoning) are a **policy decision with a safe
default** (D6): four levels — ``off`` / ``metadata`` (counts + hash) /
``redacted`` (body through the secret matcher, capped) / ``full`` (capped
only, local debugging) — defaulting to ``redacted``.

D7 is the security assertion: an **untrusted** trust tier is capped at
``metadata`` by default — not by YAML ``content: full`` and not by
``MERGECRAFT_TRACING_CONTENT``. The cap applies *after* precedence
resolution, only ever lowers a level, and never lowers to ``off``. The
rationale is ``docs/TRACING.md`` D15: remote sinks export reviewed-repo
content, and shipping a fork PR's prompt bodies to a remote sink is the
exfiltration path trust tiers exist to close.

Operators who own the sink can lift the cap with an **explicit second
knob**: env ``MERGECRAFT_TRACING_EXPORT_UNTRUSTED_CONTENT``, CLI
``--tracing-export-untrusted-content``, the matching Action input, or
``tracing.exportUntrustedContent`` from a **trusted** source (same-repo
YAML, or the run-start snapshot on ``pull_request_target`` — the base
checkout). Fork-controlled HEAD YAML cannot lift D7.
``content: full`` alone still does not ship bodies on an untrusted run.

D8: the ``.sha256`` of the ORIGINAL payload is emitted at every level above
``off`` — it detects prompt drift between two runs even when neither
shipped a body.

Convention 3 — total and non-throwing: a malformed payload or an invalid
level degrades to a missing row / the safe default, never an exception and
never ``full``. Convention 4 — no second redaction or capping mechanism:
bodies go through ``analyzers.redact.redact_secrets`` and the cap is the
shared ``cap.TRACE_ATTRS_JSON_MAX_BYTES``.

|Exports:
    Classes:
        ContentCapture — The four capture levels (StrEnum).
    Functions:
        resolve_content_capture — Env → configured → default, then the D7 cap.
        capture_text — Build the ``<prefix>[.chars|.bytes|.sha256|.truncated]`` attrs.
"""

from __future__ import annotations

import hashlib
import os
from enum import StrEnum
from typing import Any, Final

from loguru import logger

from mergecraft.analyzers.redact import redact_secrets
from mergecraft.tracing.cap import TRACE_ATTRS_JSON_MAX_BYTES

CONTENT_ENV_VAR: Final[str] = "MERGECRAFT_TRACING_CONTENT"
EXPORT_UNTRUSTED_ENV_VAR: Final[str] = "MERGECRAFT_TRACING_EXPORT_UNTRUSTED_CONTENT"
_TRUE_VALUES: Final[frozenset[str]] = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES: Final[frozenset[str]] = frozenset({"0", "false", "no", "off"})


class ContentCapture(StrEnum):
    """The four payload-capture levels (D6)."""

    OFF = "off"
    METADATA = "metadata"
    REDACTED = "redacted"
    FULL = "full"

    @property
    def emits_body(self) -> bool:
        """Whether this level ships the payload body at all."""
        return self in (ContentCapture.REDACTED, ContentCapture.FULL)

    @property
    def emits_metadata(self) -> bool:
        """Whether this level ships counts + hash (everything above ``off``)."""
        return self is not ContentCapture.OFF


_DEFAULT: Final[ContentCapture] = ContentCapture.REDACTED


def _parse_level(raw: str | None) -> ContentCapture | None:
    """Parse a configured/env level, returning ``None`` for absent or invalid values."""
    if raw is None:
        return None
    try:
        return ContentCapture(raw.strip().lower())
    except ValueError:
        logger.warning("unknown tracing content level {!r} — falling back to default", raw)
        return None


def _env_export_untrusted() -> bool | None:
    """Parse ``MERGECRAFT_TRACING_EXPORT_UNTRUSTED_CONTENT`` when set."""
    raw = os.environ.get(EXPORT_UNTRUSTED_ENV_VAR)
    if raw is None or not raw.strip():
        return None
    lowered = raw.strip().lower()
    if lowered in _TRUE_VALUES:
        return True
    if lowered in _FALSE_VALUES:
        return False
    logger.warning(
        "unknown {} value {!r} — ignoring (untrusted bodies stay capped)",
        EXPORT_UNTRUSTED_ENV_VAR,
        raw,
    )
    return None


def resolve_content_capture(
    configured: str | None,
    trust_tier: str,
    *,
    export_untrusted: bool | None = None,
) -> ContentCapture:
    """Resolve the effective capture level: env → configured → default, then D7.

    Precedence is ``MERGECRAFT_TRACING_CONTENT`` over the YAML ``content``
    field over the D6 default (``redacted``); an unrecognised value at any
    step falls through to the next, ending at the default — fail safe,
    never open. The D7 untrusted cap applies **after** precedence: at any
    tier other than ``trusted`` a body-emitting level is lowered to
    ``metadata`` unless the operator set the explicit export-untrusted
    knob (env beats the ``export_untrusted`` argument). ``off`` and
    ``metadata`` pass through unchanged (the cap lowers, it never raises —
    and never to ``off``).

    Args:
        configured (str | None): The YAML ``tracing.content`` value, if any.
        trust_tier (str): The run's trust tier (``trusted`` / ``untrusted``).
        export_untrusted (bool | None): Operator ``exportUntrustedContent``
            when env does not set the flag. Callers must not pass a value
            loaded from untrusted (fork HEAD) YAML.

    Returns:
        ContentCapture: The effective, cap-applied capture level.
    """
    level = _parse_level(os.environ.get(CONTENT_ENV_VAR))
    if level is None:
        level = _parse_level(configured)
    if level is None:
        level = _DEFAULT
    env_flag = _env_export_untrusted()
    allow_untrusted_bodies = env_flag if env_flag is not None else bool(export_untrusted)
    if trust_tier != "trusted" and level.emits_body and not allow_untrusted_bodies:
        return ContentCapture.METADATA
    return level


def capture_text(
    payload: str,
    prefix: str,
    policy: ContentCapture,
    max_bytes: int = TRACE_ATTRS_JSON_MAX_BYTES,
) -> dict[str, Any]:
    """Capture ``payload`` under ``policy`` as ``<prefix>.*`` span attributes.

    Emits ``<prefix>.chars`` / ``<prefix>.bytes`` / ``<prefix>.sha256`` —
    all describing the ORIGINAL payload (D8) — at every level above
    ``off``. Body-emitting levels additionally emit ``<prefix>`` (the body,
    secret-redacted at ``redacted``, verbatim at ``full``) and
    ``<prefix>.truncated``; bodies are byte-capped at ``max_bytes``
    (default: the shared ``TRACE_ATTRS_JSON_MAX_BYTES`` budget). ``off``
    emits nothing, hash included.

    Total and non-throwing (convention 3): any failure degrades to ``{}``
    (a missing row), never an exception onto the review path.

    Args:
        payload (str): The original payload text.
        prefix (str): Attribute prefix (e.g. ``gen_ai.input``).
        policy (ContentCapture): The resolved capture level.
        max_bytes (int): Body byte cap. Defaults to TRACE_ATTRS_JSON_MAX_BYTES.

    Returns:
        dict[str, Any]: The attribute mapping (empty at ``off`` or on error).
    """
    try:
        return _capture_text(payload, prefix, policy, max_bytes)
    except Exception as exc:
        logger.warning("trace content capture failed for {}: {}", prefix, exc)
        return {}


def _capture_text(
    payload: str,
    prefix: str,
    policy: ContentCapture,
    max_bytes: int,
) -> dict[str, Any]:
    if not policy.emits_metadata:
        return {}
    text = payload if isinstance(payload, str) else str(payload)
    encoded = text.encode("utf-8", errors="replace")
    attrs: dict[str, Any] = {
        f"{prefix}.chars": len(text),
        f"{prefix}.bytes": len(encoded),
        # D8 — the hash covers the ORIGINAL payload so drift detection works
        # even when no body ships (and never depends on redactor output).
        f"{prefix}.sha256": hashlib.sha256(encoded).hexdigest(),
    }
    if not policy.emits_body:
        return attrs
    body = redact_secrets(text) if policy is ContentCapture.REDACTED else text
    body_bytes = body.encode("utf-8", errors="replace")
    truncated = len(body_bytes) > max_bytes
    if truncated:
        # Decode with errors="ignore" so a split multi-byte sequence at the
        # cap boundary is dropped rather than producing replacement chars.
        body = body_bytes[:max_bytes].decode("utf-8", errors="ignore")
    attrs[prefix] = body
    attrs[f"{prefix}.truncated"] = truncated
    return attrs


__all__ = [
    "CONTENT_ENV_VAR",
    "EXPORT_UNTRUSTED_ENV_VAR",
    "ContentCapture",
    "capture_text",
    "resolve_content_capture",
]
