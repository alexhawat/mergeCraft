"""DG1 agent adapter category inference."""

from __future__ import annotations


def test_category_hints_match_whole_tokens_not_substrings() -> None:
    """Substring false positives must not bypass the severity rubric category."""
    from mergecraft.findings.agent_adapter import infer_agent_finding_category

    assert infer_agent_finding_category("Update the author bio copy") == ("Functional Correctness")
    assert infer_agent_finding_category("Switch from mysql to postgres") == (
        "Functional Correctness"
    )
    assert infer_agent_finding_category("Missing auth check on admin route") == (
        "Security & Privacy"
    )
    assert infer_agent_finding_category("SQL injection via unsanitized input") == (
        "Security & Privacy"
    )
