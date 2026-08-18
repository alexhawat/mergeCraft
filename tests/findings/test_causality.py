"""DG1 causality — checkable field on blocking findings (G3, D2).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG1).
Implementation: **DG1.2** — causality promoted from prompt prose to a structured
field validated before the approval gate.
"""

from __future__ import annotations

import pytest

from mergecraft.agents.gates import BLOCKING_SEVERITIES
from tests.findings.support import make_finding


@pytest.mark.xfail(reason="green after DG1.2", strict=False)
def test_blocking_finding_requires_a_causality_field() -> None:
    """Blocking findings without causality fail validation (D2)."""
    from mergecraft.findings.causality import CausalityValidationError, validate_blocking_finding

    finding = make_finding(
        severity="Critical",
        message="Race in cache invalidation",
        path="src/cache.py",
        start_line=88,
        end_line=90,
    )

    with pytest.raises(CausalityValidationError, match="causality"):
        validate_blocking_finding(finding)


@pytest.mark.xfail(reason="green after DG1.2", strict=False)
def test_finding_not_introduced_by_the_diff_is_downgraded() -> None:
    """Pre-existing defects are downgraded — they must not block merge."""
    from mergecraft.findings.causality import apply_causality_policy

    finding = make_finding(
        severity="Critical",
        introduced_by_pr="false",
        message="Legacy bare except on untouched line",
        path="src/legacy.py",
        start_line=15,
        end_line=15,
    )

    adjusted = apply_causality_policy(finding)

    assert adjusted.severity not in BLOCKING_SEVERITIES
