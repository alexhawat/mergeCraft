"""Deterministic CRAP arithmetic and C0 band mapping (C-D9).

CRAP is Python arithmetic only — never routed through Jev.

Module: mergecraft.ci.crap
Depends: (stdlib only)

Exports:
    Classes:
        CrapBands — Inclusive-lower band table (watch / elevated / crap / severe).
        CrapError — Invalid complexity or coverage input.
    Functions:
        crap_score — ``C^2 * (1 - cov)^3 + C`` with ``C >= 1`` and ``cov`` in ``[0, 1]``.
        crap_band — Inclusive lower / exclusive upper except ``severe``.
        crap_display_severity — C0 display severity for a band.
        crap_finding_severity — Finding.severity for a band (watch+ only emit).
    Private:
        _resolve_bands — Coerce a mapping or ``CrapBands`` onto the default table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

DEFAULT_WATCH = 5.0
DEFAULT_ELEVATED = 15.0
DEFAULT_CRAP = 30.0
DEFAULT_SEVERE = 50.0

DISPLAY_SEVERITY: dict[str, str] = {
    "clean": "note",
    "watch": "minor",
    "elevated": "major",
    "crap": "major",
    "severe": "critical",
}
FINDING_SEVERITY: dict[str, str] = {
    "clean": "Trivial",
    "watch": "Minor",
    "elevated": "Major",
    "crap": "Major",
    "severe": "Critical",
}


class CrapError(ValueError):
    """Raised when CRAP inputs are outside the C0 domain."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class CrapBands:
    """Inclusive-lower CRAP thresholds. ``severe`` has no exclusive upper bound."""

    watch: float = DEFAULT_WATCH
    elevated: float = DEFAULT_ELEVATED
    crap: float = DEFAULT_CRAP
    severe: float = DEFAULT_SEVERE


DEFAULT_CRAP_BANDS = CrapBands()


def _as_number(value: object, *, code: str, label: str) -> float:
    if value is None:
        msg = f"{label} is required"
        raise CrapError(msg, code=code)
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        msg = f"{label} must be a number"
        raise CrapError(msg, code=code)
    try:
        number = float(value)
    except ValueError as exc:
        msg = f"{label} must be a number"
        raise CrapError(msg, code=code) from exc
    if number != number:  # NaN
        msg = f"{label} must be a finite number"
        raise CrapError(msg, code=code)
    return number


def crap_score(complexity: object, coverage: object) -> float:
    """Return ``C^2 * (1 - cov)^3 + C``.

    Args:
        complexity: Cyclomatic complexity. Must be ``>= 1``.
        coverage: Line coverage in ``[0, 1]``.

    Returns:
        The CRAP score as a float.

    Raises:
        CrapError: ``invalid_complexity`` or ``invalid_coverage``.
    """
    complexity_value = _as_number(complexity, code="invalid_complexity", label="complexity")
    if complexity_value < 1:
        msg = "complexity must be >= 1"
        raise CrapError(msg, code="invalid_complexity")
    coverage_value = _as_number(coverage, code="invalid_coverage", label="coverage")
    if coverage_value < 0 or coverage_value > 1:
        msg = "coverage must be in [0, 1]"
        raise CrapError(msg, code="invalid_coverage")
    uncovered = 1.0 - coverage_value
    return complexity_value**2 * uncovered**3 + complexity_value


def _resolve_bands(bands: CrapBands | Mapping[str, float] | None) -> CrapBands:
    if bands is None:
        return DEFAULT_CRAP_BANDS
    if isinstance(bands, CrapBands):
        return bands
    watch = bands.get("watch", DEFAULT_CRAP_BANDS.watch)
    elevated = bands.get("elevated", DEFAULT_CRAP_BANDS.elevated)
    crap = bands.get("crap", DEFAULT_CRAP_BANDS.crap)
    severe = bands.get("severe", DEFAULT_CRAP_BANDS.severe)
    return CrapBands(
        watch=float(watch),
        elevated=float(elevated),
        crap=float(crap),
        severe=float(severe),
    )


def crap_band(
    score: float,
    bands: CrapBands | Mapping[str, float] | None = None,
) -> str:
    """Map a CRAP score onto a C0 band.

    Inclusive lower bound, exclusive upper bound, except ``severe`` which is
    ``>= severe``.
    """
    table = _resolve_bands(bands)
    if score < table.watch:
        return "clean"
    if score < table.elevated:
        return "watch"
    if score < table.crap:
        return "elevated"
    if score < table.severe:
        return "crap"
    return "severe"


def crap_display_severity(band: str) -> str:
    """Return the C0 display severity for ``band``."""
    try:
        return DISPLAY_SEVERITY[band]
    except KeyError as exc:
        msg = f"unknown CRAP band: {band!r}"
        raise CrapError(msg, code="invalid_band") from exc


def crap_finding_severity(band: str) -> str:
    """Return the Finding.severity token for ``band``."""
    try:
        return FINDING_SEVERITY[band]
    except KeyError as exc:
        msg = f"unknown CRAP band: {band!r}"
        raise CrapError(msg, code="invalid_band") from exc


__all__ = [
    "DEFAULT_CRAP_BANDS",
    "DISPLAY_SEVERITY",
    "FINDING_SEVERITY",
    "CrapBands",
    "CrapError",
    "crap_band",
    "crap_display_severity",
    "crap_finding_severity",
    "crap_score",
]
