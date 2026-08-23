"""Finding lens attribution (RC8, D9) — W5.1 RED suite."""

from __future__ import annotations

from mergecraft.review_taxonomy import FINDING_CATEGORIES
from tests.analyzers.support import import_module


def _base_kwargs() -> dict[str, object]:
    return {
        "tool": "agent",
        "rule_id": "agent:security-1",
        "category": FINDING_CATEGORIES[0],
        "severity": "Major",
        "confidence": "likely",
        "message": "Missing auth check on refund endpoint",
        "path": "src/billing/refunds.py",
        "start_line": 42,
        "end_line": 42,
        "source": "agent",
    }


def test_finding_carries_optional_lens_attribution() -> None:
    """D9 — findings may carry the lens id that produced them."""
    finding_mod = import_module("mergecraft.analyzers.finding")
    finding = finding_mod.make_finding(**_base_kwargs(), lens="security")

    assert finding.lens == "security"


def test_existing_finding_construction_sites_still_work_without_lens() -> None:
    """D9 compatibility — ``make_finding`` and ``Finding()`` default lens to None."""
    finding_mod = import_module("mergecraft.analyzers.finding")
    kwargs = _base_kwargs()

    via_helper = finding_mod.make_finding(**kwargs)
    assert getattr(via_helper, "lens", None) is None

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
    assert getattr(via_direct, "lens", None) is None
