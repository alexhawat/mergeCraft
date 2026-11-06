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


@pytest.mark.parametrize(
    "body",
    [
        "Update the docstring to document the return value",
        "Fix typo in the docstring for the raised error",
        "Clarify the documentation for allowed values",
        "Update the docstring describing failure modes",
    ],
)
def test_documented_behavior_is_not_itself_an_impact_claim(body: str) -> None:
    """Mentioning return values and exceptions does not claim broken execution."""
    normalized = normalize_agent_findings_via_pipeline(
        [AgentFinding(path="src/app.py", line=10, body=body, severity="Major")],
        rule_id="test:docs-vocabulary",
    )
    assert normalized[0].severity == "Trivial"


@pytest.mark.parametrize("noun", ["token", "tokens", "lexer tokens", "parser token", "LLM tokens"])
def test_tokenizer_naming_nits_are_not_credentials(noun: str) -> None:
    """Unqualified token collections are ordinary identifiers."""
    normalized = normalize_agent_findings_via_pipeline(
        [
            AgentFinding(
                path="src/parser.py",
                line=10,
                body=f"Use snake_case for the {noun} list",
                severity="Major",
            )
        ],
        rule_id="test:token-naming",
    )
    from mergecraft.findings.severity_rubric import infer_category_from_message

    assert infer_category_from_message(normalized[0].body) == "Maintainability & Code Quality"
    assert normalized[0].severity == "Minor"


@pytest.mark.parametrize(
    "impact",
    [
        "the handler raised TypeError for every request",
        "the process failed to persist the user's data",
        "the handler returned an incorrect status code",
        "the endpoint logs tokens in plaintext",
    ],
)
def test_docs_request_does_not_hide_past_tense_or_exposure(impact: str) -> None:
    """Cosmetic wording cannot erase a concrete defect after the request."""
    normalized = normalize_agent_findings_via_pipeline(
        [
            AgentFinding(
                path="src/app.py", line=10, body=f"Update the docstring; {impact}", severity="Major"
            )
        ],
        rule_id="test:impact-tense",
    )
    assert normalized[0].severity == "Major"
