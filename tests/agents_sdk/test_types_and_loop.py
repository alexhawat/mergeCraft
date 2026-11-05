"""Structured output parsing and review loop termination."""

from __future__ import annotations

import pytest

from mergecraft.agents_sdk.loop import run_review_loop
from mergecraft.agents_sdk.types import ReviewFinding, ReviewFindingsReport


def test_review_findings_report_parses_structured_output() -> None:
    payload = {
        "findings": [
            {
                "severity": "Major",
                "file": "src/demo.py",
                "line": 10,
                "message": "Division by zero",
                "suggested_fix": "Guard denominator",
            }
        ],
        "summary": "One issue",
    }
    report = ReviewFindingsReport.model_validate(payload)
    assert report.blocking_findings()[0].file == "src/demo.py"


@pytest.mark.asyncio
async def test_run_review_loop_stops_when_no_blocking_findings() -> None:
    calls = 0

    async def run_review() -> ReviewFindingsReport:
        nonlocal calls
        calls += 1
        return ReviewFindingsReport(
            findings=[
                ReviewFinding(
                    severity="Minor",
                    file="src/a.py",
                    message="nit",
                )
            ]
        )

    result = await run_review_loop(
        run_review=run_review,
        allowed_paths=frozenset({"src/a.py"}),
        max_rounds=5,
    )
    assert result.rounds == 1
    assert calls == 1
    assert not result.final_report.blocking_findings()


@pytest.mark.asyncio
async def test_run_review_loop_respects_max_rounds_with_fixes() -> None:
    rounds_seen = 0

    async def run_review() -> ReviewFindingsReport:
        return ReviewFindingsReport(
            findings=[
                ReviewFinding(
                    severity="Critical",
                    file="src/a.py",
                    message="still broken",
                )
            ]
        )

    async def apply_fixes(_report: ReviewFindingsReport) -> None:
        nonlocal rounds_seen
        rounds_seen += 1

    result = await run_review_loop(
        run_review=run_review,
        apply_fixes=apply_fixes,
        allowed_paths=frozenset({"src/a.py"}),
        max_rounds=2,
    )
    assert result.rounds == 2
    assert rounds_seen == 1
    assert result.final_report.blocking_findings()
