"""Review publication gate pins (D11/C3.4) — W2.1 invariant suite."""

from __future__ import annotations

from mergecraft.analyzers.review_gate import filter_for_review
from tests.analyzers.support import import_module


def _critical_finding() -> object:
    finding_mod = import_module("mergecraft.analyzers.finding")
    return finding_mod.make_finding(
        tool="semgrep",
        rule_id="taint-flow",
        category="Security & Privacy",
        severity="Critical",
        confidence="likely",
        message="user input reaches sink without sanitization",
        path="src/fixture_app/eval_sink.py",
        start_line=10,
        end_line=10,
        source="analyzer",
    )


def test_unverified_critical_is_still_gated() -> None:
    """``review_gate.py:11-27`` — Critical/Major stay gated until verified (unchanged)."""
    critical = _critical_finding()
    blocked = filter_for_review(
        [critical],
        verified_ids=set(),
        require_verification=True,
    )
    assert blocked == []

    published = filter_for_review(
        [critical],
        verified_ids={critical.fingerprint},
        require_verification=True,
    )
    assert len(published) == 1
    assert published[0].fingerprint == critical.fingerprint
