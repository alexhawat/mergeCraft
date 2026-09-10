"""Severity composition end to end: inference -> cap -> gate (RA1.2, D5/D14).

The audit's point is the composition, not any one unit. A ``Critical`` security
finding whose prose names a README must reach ``decide_approval`` as a blocker
and veto the run. Asserting the rubric in isolation would prove nothing.
"""

from __future__ import annotations

import pytest

from tests.findings.support import make_finding

_RA3_XFAIL = pytest.mark.xfail(
    reason="green after RA3: inference + cap leave a Critical security finding blocking",
    strict=False,
)

_MESSAGE = (
    "Authentication bypass lets an unauthenticated attacker reach the admin endpoint; see README"
)


@_RA3_XFAIL
def test_critical_security_finding_reaches_decide_approval_as_blocking() -> None:
    """Inference -> cap -> BLOCKING_SEVERITIES -> decide_approval is non-success."""
    from mergecraft.agents.gates import BLOCKING_SEVERITIES, decide_approval
    from mergecraft.findings.severity_rubric import (
        apply_severity_rubric,
        infer_category_from_message,
    )

    category = infer_category_from_message(_MESSAGE)
    finding = make_finding(
        category=category,
        severity="Critical",
        message=_MESSAGE,
        path="src/session.py",
        start_line=12,
        end_line=12,
        source="agent",
    )
    normalized = apply_severity_rubric(finding, model_assigned_severity="Critical")

    assert normalized.severity in BLOCKING_SEVERITIES, (
        f"inference produced category {category!r} and capped the finding to "
        f"{normalized.severity!r}"
    )
    conclusion = decide_approval([normalized], run_succeeded=True, tier="trusted")
    assert conclusion != "success", (
        f"a blocking Critical security finding produced approval {conclusion!r}"
    )
