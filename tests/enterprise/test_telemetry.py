"""W7.1 — configurable telemetry with opt-out and off (#381).

Intended public API (W7.2): ``mergecraft.enterprise.telemetry``.
Distinct from D11 local telemetry defaults on ``evidence.run_manifest``.
"""

from __future__ import annotations

import pytest


def test_telemetry_modes_include_on_opt_out_and_off() -> None:
    """Happy: the contract exposes on, opt_out, and off modes."""
    from mergecraft.enterprise.telemetry import TelemetryMode

    names = {
        mode.name.casefold() if hasattr(mode, "name") else str(mode).casefold()
        for mode in TelemetryMode
    }
    values = {
        str(mode.value).casefold() if hasattr(mode, "value") else str(mode).casefold()
        for mode in TelemetryMode
    }
    combined = names | values
    assert "on" in combined or "enabled" in combined
    assert "opt_out" in combined or "opt-out" in combined
    assert "off" in combined


def test_telemetry_off_disables_export() -> None:
    """Happy: off mode is a hard disable of remote export."""
    from mergecraft.enterprise.telemetry import (
        TelemetryMode,
        is_telemetry_export_enabled,
        resolve_telemetry_mode,
    )

    mode = resolve_telemetry_mode(explicit="off")
    assert mode == TelemetryMode.OFF or str(mode).casefold().endswith("off")
    assert is_telemetry_export_enabled(mode) is False


def test_telemetry_opt_out_is_not_on() -> None:
    """Edge: opt-out is a first-class mode, not silently treated as on."""
    from mergecraft.enterprise.telemetry import (
        TelemetryMode,
        is_telemetry_export_enabled,
        resolve_telemetry_mode,
    )

    mode = resolve_telemetry_mode(explicit="opt-out")
    assert mode != TelemetryMode.ON
    assert is_telemetry_export_enabled(mode) is False


def test_unknown_telemetry_mode_raises() -> None:
    """Error: an unknown mode name raises ValueError naming telemetry."""
    from mergecraft.enterprise.telemetry import resolve_telemetry_mode

    with pytest.raises(ValueError, match="telemetry"):
        resolve_telemetry_mode(explicit="maybe")
