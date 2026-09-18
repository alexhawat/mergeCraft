"""Cluster canonicalization must not let corroboration lower a severity (RA1.3, D8).

The audit's exact reproduction: a Major ``z-scanner`` finding alone gates the
run; adding an identical Minor ``a-scanner`` finding at the same location must
not weaken the canonical row. Canonical *wording* may keep the agent's prose;
canonical *severity* is the strongest member's.
"""

from __future__ import annotations

from typing import Any

from tests.findings.support import make_finding

_MESSAGE = "duplicate defect at the same location"


def _finding(
    tool: str,
    severity: str,
    *,
    source: str = "analyzer",
    message: str = _MESSAGE,
) -> Any:
    return make_finding(
        tool=tool,
        rule_id=f"{tool}-rule",
        category="Security & Privacy",
        severity=severity,
        confidence="likely",
        message=message,
        path="src/app.py",
        start_line=10,
        end_line=10,
        source=source,
    )


def test_major_alone_and_major_plus_minor_duplicate_gate_identically() -> None:
    """The audit's reproduction: [Major z] vs [Major z, Minor a]."""
    from mergecraft.agents.gates import decide_approval
    from mergecraft.analyzers.cluster import cluster_findings

    major = _finding("z-scanner", "Major")
    minor = _finding("a-scanner", "Minor")

    alone = cluster_findings([major])
    both = cluster_findings([major, minor])

    assert len(alone) == 1
    assert len(both) == 1
    assert alone[0].severity == both[0].severity == "Major"
    assert decide_approval(alone, run_succeeded=True, tier="trusted") == "failure"
    assert decide_approval(both, run_succeeded=True, tier="trusted") == "failure"


def test_canonical_keeps_agent_wording_but_not_a_weaker_severity() -> None:
    """D8 — split wording from severity: agent prose wins, the Major survives."""
    from mergecraft.analyzers.cluster import cluster_findings

    agent = _finding("agent", "Minor", source="agent", message="Canonical agent prose")
    analyzer = _finding("z-scanner", "Major", source="analyzer", message="Canonical agent prose")

    canonical = cluster_findings([analyzer, agent])

    assert len(canonical) == 1
    assert canonical[0].message == "Canonical agent prose"
    assert canonical[0].severity == "Major"


def test_corroboration_cannot_lower_should_verify() -> None:
    """A weaker duplicate must not clear the verification gate."""
    from mergecraft.agents.verifier import should_verify
    from mergecraft.analyzers.cluster import cluster_findings

    major = _finding("z-scanner", "Major")
    minor = _finding("a-scanner", "Minor")

    alone = cluster_findings([major])[0]
    corroborated = cluster_findings([major, minor])[0]

    assert should_verify(alone) is True
    assert should_verify(corroborated) == should_verify(alone)
