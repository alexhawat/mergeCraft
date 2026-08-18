"""DG1 agent adapter category inference."""

from __future__ import annotations

from mergecraft.agents.verifier import AgentFinding


def test_category_hints_match_whole_tokens_not_substrings() -> None:
    """Substring false positives must not bypass the severity rubric category."""
    from mergecraft.findings.severity_rubric import infer_category_from_message

    assert infer_category_from_message("Update the author bio copy") == ("Functional Correctness")
    assert infer_category_from_message("Switch from mysql to postgres") == (
        "Functional Correctness"
    )
    assert infer_category_from_message("Missing auth check on admin route") == (
        "Security & Privacy"
    )
    assert infer_category_from_message("SQL injection via unsanitized input") == (
        "Security & Privacy"
    )


def test_normalize_agent_findings_dedupes_at_publication_seam() -> None:
    """List-level dedupe must collapse duplicates without strict zip coupling."""
    from mergecraft.findings.agent_adapter import normalize_agent_findings_via_pipeline

    findings = [
        AgentFinding(
            path="src/a.py",
            body="SQL injection via unsanitized user input",
            severity="Critical",
            line=10,
        ),
        AgentFinding(
            path="src/a.py",
            body="SQL injection from unsanitized user input",
            severity="Critical",
            line=10,
        ),
    ]

    normalized = normalize_agent_findings_via_pipeline(
        findings,
        rule_id="agent:terminal",
        dedupe=True,
    )

    assert len(normalized) == 1
    assert normalized[0].path == "src/a.py"
    assert normalized[0].line == 10
