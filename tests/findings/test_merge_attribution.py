"""Duplicate evidence cannot erase or invent an introduced blocking occurrence."""

from __future__ import annotations

from itertools import permutations
from typing import TYPE_CHECKING

import pytest

from mergecraft.agents.gates import decide_approval
from mergecraft.analyzers.baseline_suppression import suppress_baseline_findings
from mergecraft.analyzers.cluster import cluster_findings
from mergecraft.analyzers.scope import introduced_by_base_diff
from mergecraft.evidence.merge import merge_finding_records, merge_findings
from mergecraft.findings.dedup import dedupe_findings
from tests.findings.support import make_finding

if TYPE_CHECKING:
    from collections.abc import Callable

    from mergecraft.analyzers.finding import Finding

_MERGES = [cluster_findings, dedupe_findings, merge_findings]


@pytest.mark.parametrize("merge", _MERGES, ids=["cluster", "semantic", "evidence"])
def test_baseline_duplicate_cannot_clear_an_introduced_blocker(
    merge: Callable[[list[Finding]], list[Finding]],
) -> None:
    major = make_finding(tool="z-scanner", rule_id="new", severity="Major", source="analyzer")
    minor = make_finding(tool="a-scanner", rule_id="existing", severity="Minor", source="analyzer")
    head = introduced_by_base_diff([major, minor], [minor])
    reported = suppress_baseline_findings(
        head_findings=head,
        base_findings=[minor],
        diff_text="diff --git a/src/app.py b/src/app.py\n--- a/src/app.py\n+++ b/src/app.py\n@@ -10 +10 @@\n-old()\n+new()\n",
        base_comparison="full",
    ).reported
    assert [row.introduced_by_pr for row in reported] == ["true", "false"]
    for ordering in permutations(reported):
        result = merge([row.model_copy(deep=True) for row in ordering])
        assert decide_approval(result, run_succeeded=True, tier="trusted") == "failure"
        assert {(row.severity, row.introduced_by_pr) for row in result} == {
            ("Major", "true"),
            ("Minor", "false"),
        }


@pytest.mark.parametrize("merge", _MERGES, ids=["cluster", "semantic", "evidence"])
def test_merge_cannot_borrow_causality_to_invent_a_blocker(
    merge: Callable[[list[Finding]], list[Finding]],
) -> None:
    old = make_finding(severity="Critical", introduced_by_pr="false")
    new = make_finding(severity="Minor", introduced_by_pr="true")
    for ordering in permutations([old, new]):
        result = merge([row.model_copy(deep=True) for row in ordering])
        assert decide_approval(result, run_succeeded=True, tier="trusted") == "success"
        assert len(result) == 2


@pytest.mark.parametrize("merge", _MERGES, ids=["cluster", "semantic", "evidence"])
@pytest.mark.parametrize("different", ["line", "scope", "causality"])
def test_same_fingerprint_does_not_erase_distinct_context(
    merge: Callable[[list[Finding]], list[Finding]],
    different: str,
) -> None:
    left = make_finding(fingerprint="same-body")
    update = {
        "line": {"start_line": 90, "end_line": 90},
        "scope": {"scope": "run"},
        "causality": {"introduced_by_pr": "unknown"},
    }[different]
    right = left.model_copy(update=update)
    for ordering in permutations([left, right]):
        result = merge(list(ordering))
        assert len(result) == 2


@pytest.mark.parametrize("shape", ["finding", "inline", "deferred"])
def test_serialized_union_retains_location_and_contradictory_attribution(shape: str) -> None:
    from mergecraft.analyzers.budget import finding_to_deferred_row

    finding = make_finding(fingerprint="same-body")
    occurrences = [
        finding,
        finding.model_copy(update={"start_line": 90, "end_line": 90}),
        finding.model_copy(update={"introduced_by_pr": "false"}),
        finding.model_copy(update={"scope": "run"}),
    ]
    records = []
    for row in occurrences:
        if shape == "deferred":
            records.append(finding_to_deferred_row(row))
        elif shape == "inline":
            records.append({"finding": row.model_dump(), "inlineBody": row.message})
        else:
            records.append(row.model_dump())
    for ordering in permutations(records):
        result = merge_finding_records(list(ordering), inline=shape == "inline")
        assert len(result) == 4
        assert result == merge_finding_records(result, inline=shape == "inline")
