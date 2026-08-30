"""W1.3 — server-stamped ``raised_by`` (wave plan 14, implementation W4)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from mergecraft.agents.ensemble import finding_key
from mergecraft.agents.registry import AgentRole
from mergecraft.analyzers.budget import default_inline_budget, place_findings
from mergecraft.mcp.verdict import SubmitReviewVerdictParams
from mergecraft.review.terminal_submission import (
    _group_findings_by_reviewer,
    merge_reviewer_findings,
    prepare_terminal_submission,
    verdict_from_merged_findings,
)
from tests.publication_attribution.support import two_reviewer_registry


def _finding(
    *,
    path: str = "src/a.py",
    body: str = "issue",
    line: int = 10,
    severity: str = "Major",
    raised_by: str | list[str] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "path": path,
        "body": body,
        "line": line,
        "severity": severity,
    }
    if raised_by is not None:
        row["raised_by"] = raised_by
    return row


def test_reviewer2_finding_arrives_with_raised_by_at_terminal_submission() -> None:
    """Dispatch pairing must stamp ``raised_by`` before flattening reaches terminal prep."""
    registry = two_reviewer_registry()
    raw = _finding(body="from reviewer2 dispatch", severity="Minor")
    stamped = merge_reviewer_findings([("reviewer2", [raw])], apply_placement=False)
    merged, _verdict = prepare_terminal_submission(
        registry=registry,  # type: ignore[arg-type]
        findings=stamped,
        verdict="approve",
    )
    assert len(merged) == 1
    assert merged[0].get("raised_by") == "reviewer2"


def test_identical_finding_from_two_reviewers_lists_both_agents() -> None:
    """``terminal_submission.py:72`` list branch — both reviewers on one row."""
    finding = _finding(body="shared defect", severity="Minor")
    merged = merge_reviewer_findings(
        [
            ("mergecraft-reviewer", [finding]),
            ("reviewer2", [dict(finding)]),
        ],
        apply_placement=False,
    )
    assert len(merged) == 1
    raised = merged[0].get("raised_by")
    assert isinstance(raised, list)
    assert set(raised) == {"mergecraft-reviewer", "reviewer2"}


def test_unknown_provenance_never_defaults_to_primary_reviewer() -> None:
    """D7 false-attribution guard — ``unknown`` must not land in the primary group."""
    registry = two_reviewer_registry()
    reviewers = registry.resolve_roles(AgentRole.reviewer)  # type: ignore[attr-defined]
    findings = [_finding(body="orphan", raised_by="unknown")]
    groups = _group_findings_by_reviewer(findings, reviewers)
    group_keys = {agent_id for agent_id, _rows in groups}
    assert "unknown" in group_keys
    primary_rows = [
        row for agent_id, rows in groups if agent_id == "mergecraft-reviewer" for row in rows
    ]
    assert all(row.get("raised_by") != "unknown" for row in primary_rows)


def test_submit_review_verdict_schema_rejects_agent_supplied_raised_by() -> None:
    """D6 — agents cannot forge ``raised_by``; containment is server-side stamping only."""
    payload = {
        "verdict": "request_changes",
        "summary": "One issue.",
        "findings": [
            {
                "path": "src/a.py",
                "body": "bug",
                "severity": "Major",
                "raised_by": "forged-reviewer",
            }
        ],
    }
    with pytest.raises((ValidationError, ValueError)) as exc_info:
        SubmitReviewVerdictParams.model_validate(payload)
    message = str(exc_info.value).lower()
    assert "raised_by" in message or "extra" in message


def test_finding_key_ignores_raised_by_for_dedup() -> None:
    """D8 — dedup identity stays ``(path, body, line)``."""
    left = _finding(body="same", raised_by="reviewer-a")
    right = _finding(body="same", raised_by="reviewer-b")
    assert finding_key(left) == finding_key(right)
    merged = merge_reviewer_findings(
        [
            ("reviewer-a", [left]),
            ("reviewer-b", [right]),
        ],
        apply_placement=False,
    )
    assert len(merged) == 1


def test_verdict_and_severity_unaffected_by_raised_by() -> None:
    """D8 — ``raised_by`` is display-only; verdict logic is unchanged."""
    base = [_finding(severity="Major")]
    tagged = [_finding(severity="Major", raised_by="reviewer2")]
    assert verdict_from_merged_findings(base) == verdict_from_merged_findings(tagged)


def test_inline_placement_unaffected_by_raised_by() -> None:
    """D8 — inline budget placement must not branch on ``raised_by``."""
    rows = [
        _finding(path=f"src/{index}.py", body=f"issue {index}", line=index, severity="Major")
        for index in range(default_inline_budget() + 2)
    ]
    without = place_findings([], inline_budget=default_inline_budget(), agent_findings=rows)
    with_tags = place_findings(
        [],
        inline_budget=default_inline_budget(),
        agent_findings=[dict(row, raised_by="reviewer2") for row in rows],
    )
    assert len(without.inline) == len(with_tags.inline)
    assert len(without.mechanical) == len(with_tags.mechanical)
