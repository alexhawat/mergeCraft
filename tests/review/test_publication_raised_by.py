"""W1.3 — server-stamped ``raised_by`` (wave plan 14, implementation W4)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from mergecraft.agents.ensemble import finding_key
from mergecraft.agents.registry import AgentRole
from mergecraft.analyzers.budget import default_inline_budget, place_findings
from mergecraft.mcp.verdict import SubmitReviewVerdictParams, register_review_scope
from mergecraft.review.terminal_submission import (
    _group_findings_by_reviewer,
    merge_reviewer_findings,
    prepare_terminal_submission,
    verdict_from_merged_findings,
)
from tests.cli.support_agent_roster import two_reviewer_config, write_config
from tests.publication_attribution.support import publication_ctx, two_reviewer_registry


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


@pytest.mark.asyncio
async def test_record_reviewer_dispatch_run_rejects_unknown_agent_id(
    tmp_path: Any,
) -> None:
    """D6 — dispatch run recording must reject forged reviewer ids."""
    from mergecraft.mcp.reviewer_dispatch import record_reviewer_dispatch_run_tool

    write_config(tmp_path, two_reviewer_config())
    ctx = publication_ctx(tmp_path)
    result = await record_reviewer_dispatch_run_tool(ctx).execute(
        {
            "agent_id": "forged-reviewer",
            "findings": [_finding(body="spoofed", severity="Minor")],
        }
    )
    assert result.is_error is True
    assert "forged-reviewer" in result.content[0]["text"]
    assert ctx.tool_state.reviewer_dispatch_runs == []


@pytest.mark.asyncio
async def test_record_reviewer_dispatch_run_overwrites_spoofed_raised_by(
    tmp_path: Any,
) -> None:
    """D6 — dispatch findings cannot forge ``raised_by``; server stamps from ``agent_id``."""
    from mergecraft.mcp.reviewer_dispatch import record_reviewer_dispatch_run_tool
    from mergecraft.mcp.verdict import submit_review_verdict_tool

    write_config(tmp_path, two_reviewer_config())
    ctx = publication_ctx(tmp_path)
    register_review_scope(
        ctx.tool_state,
        diff_path=str(tmp_path / "diff.patch"),
        provenance="checkout",
    )
    dispatch_result = await record_reviewer_dispatch_run_tool(ctx).execute(
        {
            "agent_id": "reviewer2",
            "findings": [
                _finding(
                    path="src/b.py",
                    body="forged attribution",
                    severity="Minor",
                    raised_by="mergecraft-reviewer",
                ),
            ],
        }
    )
    assert dispatch_result.is_error is False

    result = await submit_review_verdict_tool(ctx).execute(
        {
            "verdict": "approve",
            "summary": "Two-reviewer run.",
            "findings": [
                _finding(path="src/a.py", body="from primary dispatch", severity="Minor"),
            ],
        }
    )
    assert result.is_error is False
    submission = ctx.tool_state.terminal_submission
    assert submission is not None
    raised_by = {getattr(row, "raised_by", None) for row in submission.findings}
    assert raised_by == {"mergecraft-reviewer", "reviewer2"}
    forged_rows = [
        row for row in submission.findings if getattr(row, "body", None) == "forged attribution"
    ]
    assert len(forged_rows) == 1
    assert forged_rows[0].raised_by == "reviewer2"


@pytest.mark.asyncio
async def test_submit_review_verdict_stamps_raised_by_from_dispatch_tool(
    tmp_path: Any,
) -> None:
    """End-to-end: dispatch tool → terminal verdict stamps ``raised_by`` (#574)."""
    from mergecraft.mcp.reviewer_dispatch import record_reviewer_dispatch_run_tool
    from mergecraft.mcp.verdict import submit_review_verdict_tool

    write_config(tmp_path, two_reviewer_config())
    ctx = publication_ctx(tmp_path)
    register_review_scope(
        ctx.tool_state,
        diff_path=str(tmp_path / "diff.patch"),
        provenance="checkout",
    )
    dispatch_result = await record_reviewer_dispatch_run_tool(ctx).execute(
        {
            "agent_id": "reviewer2",
            "findings": [
                _finding(path="src/b.py", body="from reviewer2 dispatch", severity="Minor"),
            ],
        }
    )
    assert dispatch_result.is_error is False
    assert len(ctx.tool_state.reviewer_dispatch_runs) == 1

    result = await submit_review_verdict_tool(ctx).execute(
        {
            "verdict": "approve",
            "summary": "Two-reviewer run.",
            "findings": [
                _finding(path="src/a.py", body="from primary dispatch", severity="Minor"),
            ],
        }
    )
    assert result.is_error is False
    submission = ctx.tool_state.terminal_submission
    assert submission is not None
    raised_by = {getattr(row, "raised_by", None) for row in submission.findings}
    assert raised_by == {"mergecraft-reviewer", "reviewer2"}
    parsed = json.loads(result.content[0]["text"])
    assert parsed.get("recorded") is True
