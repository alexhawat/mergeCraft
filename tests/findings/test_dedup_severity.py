"""Semantic dedupe keeps the strongest survivor (RA1.3, D7/D8).

``findings/dedup.py`` runs before ``evidence/merge.merge_findings`` and used to
keep ``cluster[0]`` unconditionally, so a weaker paraphrase arriving first could
turn a blocker green. The survivor must be the strongest member, its evidence
must unite the discarded members, and ``kept_indices`` must point at the row
actually kept (lane B's RB6 realigns on those indices).
"""

from __future__ import annotations

import itertools
from typing import Any

import pytest

from tests.findings.support import make_finding

_RA4_XFAIL = pytest.mark.xfail(
    reason="green after RA4: semantic dedupe keeps the strongest survivor",
    strict=False,
)


def _finding(severity: str, message: str, *, evidence: list[str] | None = None) -> Any:
    return make_finding(
        tool="agent",
        rule_id="agent:retry-timeout",
        category="Functional Correctness",
        severity=severity,
        confidence="likely",
        message=message,
        path="src/app.py",
        start_line=42,
        end_line=42,
        source="agent",
        evidence=evidence or [],
    )


def _minor() -> Any:
    return _finding("Minor", "Missing timeout on the retry loop", evidence=["minor-evidence"])


def _major() -> Any:
    return _finding("Major", "The retry loop never sets a timeout", evidence=["major-evidence"])


@_RA4_XFAIL
def test_semantic_dedupe_keeps_the_strongest_survivor() -> None:
    """The paraphrased retry-loop-timeout pair collapses to the Major row."""
    from mergecraft.findings.dedup import dedupe_findings_with_indices

    result = dedupe_findings_with_indices([_minor(), _major()])

    assert len(result.findings) == 1
    assert result.findings[0].severity == "Major"


@_RA4_XFAIL
def test_dedupe_result_is_permutation_invariant() -> None:
    """Both orderings of the same pair produce the same survivor severity."""
    from mergecraft.findings.dedup import dedupe_findings_with_indices

    reference: tuple[str, ...] | None = None
    for ordering in itertools.permutations([_minor(), _major()]):
        result = dedupe_findings_with_indices(list(ordering))
        severities = tuple(sorted(finding.severity for finding in result.findings))
        if reference is None:
            reference = severities
        else:
            assert severities == reference, f"ordering produced {severities!r} != {reference!r}"


@_RA4_XFAIL
def test_evidence_from_discarded_members_is_retained() -> None:
    """A discarded paraphrase's evidence survives on the survivor."""
    from mergecraft.findings.dedup import dedupe_findings_with_indices

    result = dedupe_findings_with_indices([_minor(), _major()])

    assert len(result.findings) == 1
    evidence = " ".join(result.findings[0].evidence)
    assert "minor-evidence" in evidence
    assert "major-evidence" in evidence


@_RA4_XFAIL
def test_kept_indices_still_point_at_the_surviving_row() -> None:
    """The cross-lane contract RB6 depends on: indices name the row actually kept."""
    from mergecraft.findings.dedup import dedupe_findings_with_indices

    source = [_minor(), _major()]
    result = dedupe_findings_with_indices(source)

    assert len(result.kept_indices) == len(result.findings) == 1
    survivor = source[result.kept_indices[0]]
    assert survivor is result.findings[0]
    assert survivor.severity == "Major"
