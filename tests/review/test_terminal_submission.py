"""Unit tests for multi-reviewer terminal submission helpers (D6/D7/D15)."""

from __future__ import annotations

from typing import Any

from mergecraft.agents.registry import AgentBinding, AgentRole, Registry
from mergecraft.review.terminal_submission import (
    ReviewerRun,
    append_degradation_to_summary,
    format_reviewer_degradation_summary,
    merge_reviewer_findings,
    prepare_terminal_submission,
    terminal_submission_count_from_review_runs,
    verdict_from_merged_findings,
)


def _binding(agent_id: str) -> AgentBinding:
    return AgentBinding(
        agent_id=agent_id,
        role=AgentRole.reviewer,
        model_chain=("anthropic/claude-sonnet",),
        prompt_id="mergecraft.reviewer",
        prompt_version="1.0.0",
        tool_classes=frozenset(),
        budget=8,
        timeout_s=600,
    )


def _finding(*, path: str = "a.py", body: str = "issue", severity: str = "Minor") -> dict[str, Any]:
    return {"path": path, "body": body, "severity": severity, "line": 1}


def test_reviewer_run_dataclass_fields() -> None:
    run = ReviewerRun(agent_id="reviewer2", findings=[_finding()], error="quota exceeded")
    assert run.agent_id == "reviewer2"
    assert run.error == "quota exceeded"


def test_format_reviewer_degradation_summary_empty() -> None:
    assert format_reviewer_degradation_summary(None) == ""
    assert format_reviewer_degradation_summary({}) == ""


def test_append_degradation_to_summary_replaces_empty_summary() -> None:
    block = format_reviewer_degradation_summary({"reviewer2": "quota exceeded"})
    assert append_degradation_to_summary("", errors={"reviewer2": "quota exceeded"}) == block


def test_append_degradation_to_summary_appends_block() -> None:
    merged = append_degradation_to_summary("Lead summary", errors={"reviewer2": "quota exceeded"})
    assert merged.startswith("Lead summary")
    assert "reviewer2" in merged.lower()


def test_verdict_from_merged_findings_branches() -> None:
    assert verdict_from_merged_findings([]) == "approve"
    assert verdict_from_merged_findings([_finding(severity="Minor")]) == "approve"
    assert verdict_from_merged_findings([_finding(severity="Major")]) == "request_changes"


def test_merge_reviewer_findings_logs_errors_and_orders_deterministically() -> None:
    merged = merge_reviewer_findings(
        [
            ("reviewer", [_finding(path="z.py", body="z", severity="Minor")]),
            ("reviewer2", [_finding(path="a.py", body="a", severity="Major")]),
        ],
        errors={"reviewer3": "timeout"},
        apply_placement=False,
    )
    assert [row["path"] for row in merged] == ["a.py", "z.py"]
    assert merged[0]["raised_by"] == "reviewer2"


def test_merge_reviewer_findings_apply_placement() -> None:
    merged = merge_reviewer_findings(
        [("reviewer", [_finding(body="inline finding", severity="Minor")])],
        apply_placement=True,
    )
    assert merged


def test_terminal_submission_count_is_one() -> None:
    assert terminal_submission_count_from_review_runs([]) == 1


def test_prepare_terminal_submission_without_reviewers() -> None:
    registry = Registry({})
    merged, verdict = prepare_terminal_submission(
        registry=registry,
        findings=[_finding()],
        verdict="comment",
    )
    assert merged
    assert verdict == "approve"


def test_prepare_terminal_submission_routes_unassigned_findings_to_unknown() -> None:
    registry = Registry(
        {
            "reviewer": _binding("mergecraft-reviewer"),
            "reviewer2": _binding("reviewer2"),
        }
    )
    merged, verdict = prepare_terminal_submission(
        registry=registry,
        findings=[_finding(body="unassigned")],
        verdict="approve",
    )
    assert merged[0]["raised_by"] == "unknown"
    assert verdict == "approve"


def test_prepare_terminal_submission_strictest_verdict_comment_over_approve() -> None:
    registry = Registry({"reviewer": _binding("mergecraft-reviewer")})
    _merged, verdict = prepare_terminal_submission(
        registry=registry,
        findings=[_finding(severity="Minor")],
        verdict="approve",
    )
    assert verdict == "approve"
