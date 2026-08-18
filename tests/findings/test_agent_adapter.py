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
    assert infer_category_from_message("Rename secretariat office contact field") == (
        "Functional Correctness"
    )
    assert infer_category_from_message("Increment token_count before rate limit") == (
        "Functional Correctness"
    )
    assert infer_category_from_message("Token bucket refill rate is too high") == (
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


def test_normalize_agent_findings_memory_suppression_aligns_drafts(tmp_path) -> None:
    """Memory suppression must not remap deduped rows to pre-suppression drafts."""
    from mergecraft.findings.agent_adapter import normalize_agent_findings_via_pipeline
    from mergecraft.utils.memory import FeedbackOutcome, record_finding_feedback
    from tests.memory.support import feedback_store_path, make_finding

    repo = tmp_path / "repo"
    repo.mkdir()
    dismissed = make_finding(
        message="Stale warning",
        path="src/app.py",
        start_line=1,
        end_line=1,
    )
    record_finding_feedback(
        store_path=feedback_store_path(repo),
        fingerprint=dismissed.fingerprint,
        outcome=FeedbackOutcome.DISMISSED,
        reason="Already fixed upstream",
        pr_number=7,
    )

    findings = [
        AgentFinding(
            path="src/app.py",
            body="Stale warning",
            severity="Major",
            line=1,
            fingerprint=dismissed.fingerprint,
        ),
        AgentFinding(
            path="src/app.py",
            body="Real regression in retry loop",
            severity="Major",
            line=10,
        ),
    ]

    normalized = normalize_agent_findings_via_pipeline(
        findings,
        rule_id="agent:terminal",
        dedupe=True,
        repo_root=repo,
    )

    assert len(normalized) == 1
    assert normalized[0].body == "Real regression in retry loop"
    assert normalized[0].line == 10
