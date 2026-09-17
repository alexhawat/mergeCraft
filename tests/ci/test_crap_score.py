"""C2 — CRAP arithmetic, C0 band boundaries, and display severity (C-D9)."""

from __future__ import annotations

import math
from typing import Any

import pytest

from tests.ci.support_crap import (
    BANDS,
    DEFAULT_BANDS,
    DISPLAY_SEVERITY,
    FINDING_SEVERITY,
    WORKED_EXAMPLES,
    import_ci,
    load_meta,
)


def _crap() -> Any:
    return import_ci("crap")


@pytest.mark.parametrize(
    ("band", "complexity", "coverage", "expected"),
    WORKED_EXAMPLES,
    ids=[row[0] for row in WORKED_EXAMPLES],
)
def test_worked_example_crap_score(
    band: str, complexity: int, coverage: float, expected: float
) -> None:
    score = _crap().crap_score(complexity, coverage)
    assert score == pytest.approx(expected)
    assert _crap().crap_band(score) == band
    assert load_meta(band)["crap"] == pytest.approx(expected)


@pytest.mark.parametrize(
    ("score", "band"),
    [
        (0.0, "clean"),
        (math.nextafter(5.0, 0.0), "clean"),
        (5.0, "watch"),
        (math.nextafter(15.0, 0.0), "watch"),
        (15.0, "elevated"),
        (math.nextafter(30.0, 0.0), "elevated"),
        (30.0, "crap"),
        (math.nextafter(50.0, 0.0), "crap"),
        (50.0, "severe"),
        (110.0, "severe"),
    ],
    ids=[
        "0-clean",
        "just-below-5-clean",
        "5-watch",
        "just-below-15-watch",
        "15-elevated",
        "just-below-30-elevated",
        "30-crap",
        "just-below-50-crap",
        "50-severe",
        "110-severe",
    ],
)
def test_crap_band_inclusive_lower_exclusive_upper_except_severe(score: float, band: str) -> None:
    assert _crap().crap_band(score) == band


@pytest.mark.parametrize("band", BANDS)
def test_display_and_finding_severity_for_each_band(band: str) -> None:
    crap = _crap()
    assert crap.crap_display_severity(band) == DISPLAY_SEVERITY[band]
    assert crap.crap_finding_severity(band) == FINDING_SEVERITY[band]


def test_default_bands_match_c0_table() -> None:
    bands = _crap().DEFAULT_CRAP_BANDS
    assert bands.watch == DEFAULT_BANDS["watch"]
    assert bands.elevated == DEFAULT_BANDS["elevated"]
    assert bands.crap == DEFAULT_BANDS["crap"]
    assert bands.severe == DEFAULT_BANDS["severe"]


def test_consumer_bands_move_a_score_across_the_watch_line() -> None:
    """C=2, cov=0.2 → CRAP≈4.048: clean under defaults, watch when watch=3."""
    crap = _crap()
    score = crap.crap_score(2, 0.2)
    assert score == pytest.approx(4.048)
    assert crap.crap_band(score) == "clean"
    consumer = {"watch": 3, "elevated": 15, "crap": 30, "severe": 50}
    assert crap.crap_band(score, bands=consumer) == "watch"


def test_crap_score_rejects_complexity_below_one() -> None:
    crap = _crap()
    with pytest.raises(crap.CrapError) as exc_info:
        crap.crap_score(0, 1.0)
    assert exc_info.value.code == "invalid_complexity"


def test_crap_score_rejects_coverage_outside_unit_interval() -> None:
    crap = _crap()
    with pytest.raises(crap.CrapError) as exc_info:
        crap.crap_score(1, 1.01)
    assert exc_info.value.code == "invalid_coverage"
    with pytest.raises(crap.CrapError) as exc_info:
        crap.crap_score(1, -0.01)
    assert exc_info.value.code == "invalid_coverage"


def test_crap_score_rejects_none_inputs() -> None:
    crap = _crap()
    with pytest.raises(crap.CrapError) as exc_info:
        crap.crap_score(None, 1.0)
    assert exc_info.value.code == "invalid_complexity"
    with pytest.raises(crap.CrapError) as exc_info:
        crap.crap_score(1, None)
    assert exc_info.value.code == "invalid_coverage"
