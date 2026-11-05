"""Cosmetic vocabulary is not evidence that a functional defect is a nit."""

from __future__ import annotations

import pytest

from mergecraft.agents.gates import decide_approval
from mergecraft.agents.verifier import AgentFinding
from mergecraft.analyzers.finding import render_finding_pr_comment
from mergecraft.findings.agent_adapter import (
    finding_for_publication_validation,
    normalize_agent_findings_via_pipeline,
)
from mergecraft.findings.causality import validate_blocking_finding


@pytest.mark.parametrize(
    "body",
    [
        "Posting a review now raises TypeError for every PR.",
        "Posting a review comment now raises TypeError for every PR.",
        "A typo in the handler name raises AttributeError for every request.",
        "The comment endpoint returns an incorrect status code for every request.",
        "The naming change drops every request from the retry queue.",
        "The README command deletes existing user data.",
    ],
)
@pytest.mark.parametrize("severity", ["Major", "Critical"])
def test_functional_impact_reaches_gate_and_publication(body: str, severity: str) -> None:
    normalized = normalize_agent_findings_via_pipeline(
        [AgentFinding(path="src/app.py", line=10, body=body, severity=severity)],
        rule_id="test:impact",
    )
    assert normalized[0].severity == severity
    published = finding_for_publication_validation(
        normalized[0].model_dump(), fingerprint="audit", causality="The PR changes this path."
    )
    validate_blocking_finding(published)
    assert decide_approval([published], run_succeeded=True, tier="trusted") == "failure"
    assert published.severity == severity
    assert body in render_finding_pr_comment(published, short_id="MC-audit")


@pytest.mark.parametrize("separator", ["; ", ". ", ", ", " — ", "\n"])
@pytest.mark.parametrize(
    "impact",
    [
        "the handler raises AttributeError for every request",
        "the example deletes existing user data",
        "the change allows unauthenticated access to the admin endpoint",
    ],
)
def test_cosmetic_lead_cannot_hide_impact_later_in_message(separator: str, impact: str) -> None:
    for lead in ["Fix the typo in the comment", "Update the README", "README spelling typo"]:
        normalized = normalize_agent_findings_via_pipeline(
            [
                AgentFinding(
                    path="src/app.py", line=10, body=lead + separator + impact, severity="Major"
                )
            ],
            rule_id="test:impact",
        )
        assert normalized[0].severity == "Major"


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("Prefer f-string over percent formatting", "Minor"),
        ("The authorship rules say prefer f-string over percent formatting", "Minor"),
        ("Update the comment in this module", "Trivial"),
        ("Fix spelling in the README", "Trivial"),
        ("README spelling typo", "Trivial"),
        ("Documentation spelling error.", "Trivial"),
        ("Prefer f-string over percent formatting in the token handler", "Minor"),
        ("Update the comment in the authentication module", "Trivial"),
    ],
)
def test_clear_cosmetic_intent_still_caps_even_with_security_vocabulary(
    body: str,
    expected: str,
) -> None:
    normalized = normalize_agent_findings_via_pipeline(
        [AgentFinding(path="src/app.py", line=10, body=body, severity="Critical")],
        rule_id="test:cosmetic",
    )
    assert normalized[0].severity == expected
