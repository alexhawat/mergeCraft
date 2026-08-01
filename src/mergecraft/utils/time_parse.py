"""Timeout / duration string parsing (``10m``, ``1h30m``, ``--notimeout``)."""

from __future__ import annotations

import re

# Special value indicating timeout is explicitly disabled via --notimeout flag.
TIMEOUT_DISABLED = "none"

# At least one component (hours, minutes, or seconds) is required.
_TIME_STRING_RE = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$")

# Node / setTimeout ceiling (~24.8 days).
TIMEOUT_MAX_MS = 2_147_483_647


def parse_time_string(input_value: str) -> int | None:
    """Parse ``10m`` / ``1h30m`` / ``10m12s`` into milliseconds, or ``None`` if invalid."""
    match = _TIME_STRING_RE.match(input_value)
    if not match or (not match.group(1) and not match.group(2) and not match.group(3)):
        return None

    hours = int(match.group(1) or "0")
    minutes = int(match.group(2) or "0")
    seconds = int(match.group(3) or "0")
    return (hours * 3600 + minutes * 60 + seconds) * 1000


def is_valid_time_string(input_value: str) -> bool:
    """Return whether ``input_value`` is a valid time format."""
    return parse_time_string(input_value) is not None


def resolve_timeout_ms(input_value: str | None) -> int | None:
    """Resolve a timeout string to setTimeout-safe milliseconds, or ``None`` if unusable.

    Unusable covers: missing, unparseable, zero, and overflow past ``TIMEOUT_MAX_MS``.
    """
    if not input_value:
        return None
    parsed = parse_time_string(input_value)
    if parsed is None or parsed <= 0 or parsed > TIMEOUT_MAX_MS:
        return None
    return parsed


def normalize_timeout_input(raw: str | None) -> str | None:
    """Normalize CLI/action timeout input; map ``--notimeout`` to ``TIMEOUT_DISABLED``."""
    if raw is None:
        return None
    stripped = raw.strip()
    if not stripped:
        return None
    if stripped in {"--notimeout", "notimeout", TIMEOUT_DISABLED}:
        return TIMEOUT_DISABLED
    return stripped


def parse_timeout(raw: str | None) -> int | None:
    """Parse a timeout input into milliseconds.

    Returns ``None`` when timeout is disabled (``--notimeout`` / ``none``) or when the
    value cannot be honored (invalid / zero / overflow). Callers that need to
    distinguish disabled vs invalid should inspect ``normalize_timeout_input`` first.
    """
    normalized = normalize_timeout_input(raw)
    if normalized is None or normalized == TIMEOUT_DISABLED:
        return None
    return resolve_timeout_ms(normalized)
