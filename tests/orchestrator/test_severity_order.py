"""RED — pipeline severity ordering (AG6 / MCB-34)."""

from __future__ import annotations

from mergecraft.review_taxonomy import FINDING_SEVERITIES


def _severity_rank(severity: str) -> int:
    from mergecraft.orchestrator.pipeline import _SEVERITY_ORDER

    return _SEVERITY_ORDER.get(severity, -1)


def test_trivial_ranks_below_minor() -> None:
    from mergecraft.orchestrator.pipeline import _SEVERITY_ORDER

    assert "Trivial" in _SEVERITY_ORDER
    assert _SEVERITY_ORDER["Trivial"] < _SEVERITY_ORDER["Minor"]


def test_unknown_severity_ranks_below_everything() -> None:
    unknown = _severity_rank("NotASeverity")
    for severity in FINDING_SEVERITIES:
        assert unknown < _severity_rank(severity)


def test_severity_order_matches_finding_severities() -> None:
    from mergecraft.orchestrator.pipeline import _SEVERITY_ORDER

    assert set(_SEVERITY_ORDER) == set(FINDING_SEVERITIES)
