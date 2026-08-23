"""Finding collateral paths (RC11) — W8.1 RED suite.

Wave plan: ``.ignorelocal/waves/review-convergence-wave-plan.md`` (W8).
Pins optional ``Finding.collateral`` — call sites, tests, docs the fix must
also touch. Implementation lands in W8.2.
"""

from __future__ import annotations

from mergecraft.review_taxonomy import FINDING_CATEGORIES
from tests.analyzers.support import import_module


def _base_kwargs() -> dict[str, object]:
    return {
        "tool": "agent",
        "rule_id": "agent:correctness-1",
        "category": FINDING_CATEGORIES[0],
        "severity": "Major",
        "confidence": "likely",
        "message": "Refund handler skips auth guard",
        "path": "src/billing/refunds.py",
        "start_line": 42,
        "end_line": 42,
        "source": "agent",
    }


_COLLATERAL_PATHS: tuple[str, ...] = (
    "tests/billing/test_refunds.py",
    "src/billing/caller.py",
)


def test_finding_carries_optional_collateral_list() -> None:
    """RC11 — findings may list collateral paths the fix must also touch."""
    finding_mod = import_module("mergecraft.analyzers.finding")
    finding = finding_mod.make_finding(**_base_kwargs(), collateral=list(_COLLATERAL_PATHS))

    assert finding.collateral == list(_COLLATERAL_PATHS)


def test_existing_construction_sites_still_work_without_collateral() -> None:
    """RC11 compatibility — ``make_finding`` and ``Finding()`` work without collateral."""
    finding_mod = import_module("mergecraft.analyzers.finding")
    kwargs = _base_kwargs()

    via_helper = finding_mod.make_finding(**kwargs)
    assert getattr(via_helper, "collateral", None) in (None, [])

    via_direct = finding_mod.Finding(
        tool=str(kwargs["tool"]),
        rule_id=str(kwargs["rule_id"]),
        category=str(kwargs["category"]),
        severity=str(kwargs["severity"]),
        confidence=str(kwargs["confidence"]),
        message=str(kwargs["message"]),
        path=str(kwargs["path"]),
        start_line=int(kwargs["start_line"]),  # type: ignore[arg-type]
        end_line=int(kwargs["end_line"]),  # type: ignore[arg-type]
        fingerprint="abc123",
        evidence=[],
        remediation=None,
        autofix=None,
        introduced_by_pr="unknown",
        source="agent",  # type: ignore[arg-type]
        cluster_id=None,
    )
    assert getattr(via_direct, "collateral", None) in (None, [])
