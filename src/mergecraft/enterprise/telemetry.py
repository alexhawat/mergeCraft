"""Configurable telemetry with opt-out and off modes (#381).

Distinct from D11 local telemetry defaults on ``evidence.run_manifest``.

Exports:
    TelemetryMode: Enum of supported telemetry modes.
    resolve_telemetry_mode: Parse a string into a TelemetryMode.
    is_telemetry_export_enabled: Return whether remote export is active.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "TelemetryMode",
    "is_telemetry_export_enabled",
    "resolve_telemetry_mode",
]

_ALIASES: dict[str, str] = {
    "on": "ON",
    "enabled": "ON",
    "opt-out": "OPT_OUT",
    "opt_out": "OPT_OUT",
    "off": "OFF",
    "disabled": "OFF",
}


class TelemetryMode(StrEnum):
    """Supported telemetry modes.

    Attributes:
        ON: Remote export is enabled.
        OPT_OUT: The installation opts out of remote export.
        OFF: Remote export is hard-disabled.
    """

    ON = "on"
    OPT_OUT = "opt_out"
    OFF = "off"


def resolve_telemetry_mode(*, explicit: str) -> TelemetryMode:
    """Parse *explicit* into a :class:`TelemetryMode`.

    Args:
        explicit: One of ``"on"``, ``"enabled"``, ``"opt-out"``, ``"opt_out"``,
            ``"off"``, or ``"disabled"`` (case-insensitive).

    Returns:
        The resolved :class:`TelemetryMode`.

    Raises:
        ValueError: When *explicit* is not a recognised telemetry mode name.
    """
    key = explicit.strip().casefold()
    canonical = _ALIASES.get(key)
    if canonical is None:
        recognised = ", ".join(sorted(_ALIASES))
        msg = f"unknown telemetry mode {explicit!r}; recognised: {recognised}"
        raise ValueError(msg)
    return TelemetryMode[canonical]


def is_telemetry_export_enabled(mode: TelemetryMode) -> bool:
    """Return ``True`` only when *mode* is :attr:`TelemetryMode.ON`.

    Args:
        mode: The resolved telemetry mode.

    Returns:
        ``True`` for ``ON``; ``False`` for ``OPT_OUT`` or ``OFF``.
    """
    return mode is TelemetryMode.ON
