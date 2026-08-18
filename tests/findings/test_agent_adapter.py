"""DG1 agent adapter category inference."""

from __future__ import annotations


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
