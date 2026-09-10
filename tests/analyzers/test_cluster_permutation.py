"""Clustering is permutation-invariant (RA1.3, D15).

The audit reproduced order-dependence: the canonical member was picked by input
order, so the same input set clustered to different severities. A fixed
two-element case passes on the wrong fix; this property checks every ordering.
"""

from __future__ import annotations

import itertools
from typing import Any

import pytest

from tests.findings.support import make_finding

_RA4_XFAIL = pytest.mark.xfail(
    reason="green after RA4: cluster result is invariant under input ordering",
    strict=False,
)

_MESSAGE = "same defect, same location"


def _finding(tool: str, severity: str, *, source: str = "analyzer") -> Any:
    return make_finding(
        tool=tool,
        rule_id=f"{tool}-rule",
        category="Security & Privacy",
        severity=severity,
        confidence="likely",
        message=_MESSAGE,
        path="src/app.py",
        start_line=10,
        end_line=10,
        source=source,
    )


@_RA4_XFAIL
def test_cluster_result_is_permutation_invariant() -> None:
    """Every ordering of the same input set yields the same severities."""
    from mergecraft.analyzers.cluster import cluster_findings

    members = [
        _finding("agent-a", "Minor", source="agent"),
        _finding("agent-b", "Major", source="agent"),
        _finding("z-scanner", "Critical"),
    ]

    reference: tuple[str, ...] | None = None
    for ordering in itertools.permutations(members):
        result = cluster_findings(list(ordering))
        severities = tuple(sorted(finding.severity for finding in result))
        if reference is None:
            reference = severities
        else:
            assert severities == reference, (
                f"ordering {[f.tool for f in ordering]} produced {severities!r} != {reference!r}"
            )
