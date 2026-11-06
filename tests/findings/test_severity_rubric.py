"""DG1 severity rubric — code-defined, not model-assigned (G2).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG1).
Implementation: **DG1.2** — rubric applied at the ``JudgeVerdict`` seam in
``agents/verifier.py``.
"""

from __future__ import annotations

import pytest

from mergecraft.agents.gates import BLOCKING_SEVERITIES
from tests.findings.support import make_finding


def test_blocking_severities_unchanged() -> None:
    """Regression pin — ``BLOCKING_SEVERITIES`` stays ``Critical`` + ``Major`` only."""
    assert frozenset({"Critical", "Major"}) == BLOCKING_SEVERITIES


def test_rubric_normalizes_model_assigned_severity() -> None:
    """Inflated model severity is normalized by the code-defined rubric."""
    from mergecraft.findings.severity_rubric import apply_severity_rubric

    finding = make_finding(
        category="Maintainability & Code Quality",
        severity="Critical",
        message="Prefer f-string over percent formatting",
        path="src/util.py",
        start_line=3,
        end_line=3,
    )

    normalized = apply_severity_rubric(finding, model_assigned_severity="Critical")

    assert normalized.severity not in BLOCKING_SEVERITIES
    assert normalized.severity in {"Minor", "Trivial"}


def test_rubric_is_code_defined_not_model_defined() -> None:
    """The rubric is a code artifact — not delegated to the reviewing model."""
    from mergecraft.findings import severity_rubric

    assert hasattr(severity_rubric, "SEVERITY_RUBRIC")
    rubric = severity_rubric.SEVERITY_RUBRIC
    assert isinstance(rubric, (tuple, list, dict))
    assert len(rubric) > 0
    # Rubric rules must be inspectable Python data, not prompt prose.
    assert not isinstance(rubric, str)


@pytest.mark.parametrize(
    "body",
    [
        "Update the docstring example: it contains a real AWS secret access key",
        "Fix the README: it embeds a live GitHub token in the curl example",
        "Update the comment to remove the hardcoded password",
        "Fix the documentation: the API key is stored in plaintext",
        "Clarify the README: it contains credentials",
    ],
)
def test_documentation_credentials_remain_security_blockers(body: str) -> None:
    from mergecraft.agents.verifier import AgentFinding
    from mergecraft.findings.agent_adapter import (
        agent_finding_to_finding,
        blocking_agent_findings,
        normalize_agent_findings_via_pipeline,
    )

    draft = AgentFinding(path="README.md", line=1, body=body, severity="Critical")
    normalized = normalize_agent_findings_via_pipeline([draft], rule_id="review")

    assert normalized[0].severity == "Critical"
    finding = agent_finding_to_finding(normalized[0], rule_id="review")
    assert finding.category == "Security & Privacy"
    assert blocking_agent_findings(normalized, rule_id="review")


@pytest.mark.parametrize(
    ("body", "severity"),
    [
        ("Update the comment in the authentication module", "Trivial"),
        ("Fix the README typo in the token handler example", "Trivial"),
        ("Prefer f-string over percent formatting in the token handler", "Minor"),
    ],
)
def test_security_domain_alone_does_not_block_cosmetic_caps(body: str, severity: str) -> None:
    from mergecraft.agents.verifier import AgentFinding
    from mergecraft.findings.agent_adapter import normalize_agent_findings_via_pipeline

    draft = AgentFinding(path="README.md", line=1, body=body, severity="Critical")
    normalized = normalize_agent_findings_via_pipeline([draft], rule_id="review")
    assert normalized[0].severity == severity
