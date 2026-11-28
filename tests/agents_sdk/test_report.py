"""The Agents SDK review report document and its markdown rendering."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

pytest.importorskip("agents")

from mergecraft.agents_sdk.report import (
    AGENTS_SDK_REVIEW_SCHEMA,
    AgentsSdkReviewReport,
    ReviewUsage,
    build_review_report,
    render_review_markdown,
)
from mergecraft.agents_sdk.types import ReviewFinding, ReviewFindingsReport

HEAD = "a" * 40


def _output() -> ReviewFindingsReport:
    return ReviewFindingsReport(
        summary="Checked the queue and the store.",
        findings=[
            ReviewFinding(
                severity="Minor",
                file="src/queue.py",
                line=3,
                message="Retry count is off by one.",
            ),
            ReviewFinding(
                severity="Major",
                file="src/store.py",
                line=12,
                message="Rows are read and then written in one transaction.",
                suggested_fix="Use a compare-and-set update.",
            ),
            ReviewFinding(severity="Major", file="other/outside.py", message="Out of scope."),
        ],
    )


def test_build_review_report_applies_guardrails_and_records_scope() -> None:
    report = build_review_report(
        _output(),
        allowed_paths=frozenset({"src/store.py", "src/queue.py"}),
        model="openai/gpt-test",
        pull_request=4,
        head_sha=HEAD,
        omitted_files=["uv.lock"],
        usage=ReviewUsage(requests=3, input_tokens=1000, output_tokens=200),
    )
    assert [f.file for f in report.findings] == ["src/queue.py", "src/store.py"]
    assert report.dropped == ["finding references path outside change set: 'other/outside.py'"]
    assert report.changed_files == ["src/queue.py", "src/store.py"]
    assert report.omitted_files == ["uv.lock"]
    assert [f.file for f in report.blocking_findings()] == ["src/store.py"]
    assert not report.passed()


def test_report_round_trips_through_json_with_its_schema_key() -> None:
    report = build_review_report(
        _output(), allowed_paths=frozenset({"src/queue.py"}), head_sha=HEAD
    )
    document = json.loads(report.to_json())
    assert document["schema"] == AGENTS_SDK_REVIEW_SCHEMA
    assert AgentsSdkReviewReport.model_validate(document) == report


def test_report_rejects_another_schema_and_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        AgentsSdkReviewReport.model_validate({"schema": "other.v9", "status": "reviewed"})
    with pytest.raises(ValidationError):
        AgentsSdkReviewReport.model_validate({"status": "reviewed", "verdict": "approve"})


def test_skipped_and_failed_reviews_have_no_findings_and_say_why() -> None:
    skipped = AgentsSdkReviewReport(status="skipped", reason="no reviewable files changed")
    failed = AgentsSdkReviewReport(status="error", reason="RateLimitError: slow down")
    assert skipped.passed()
    assert not failed.passed()
    body = render_review_markdown(failed)
    assert "**review failed**" in body
    assert "RateLimitError: slow down" in body
    assert "No review was completed" in body


def test_markdown_lists_every_finding_by_severity_with_fix_scope_and_usage() -> None:
    report = build_review_report(
        _output(),
        allowed_paths=frozenset({"src/store.py", "src/queue.py"}),
        model="openai/gpt-test",
        head_sha=HEAD,
        omitted_files=["uv.lock"],
        usage=ReviewUsage(requests=3, input_tokens=1000, output_tokens=200),
    )
    body = render_review_markdown(report)
    assert "**changes requested: 1 blocking of 2 findings**" in body
    assert body.index("##### Major — src/store\\.py:12") < body.index(
        "##### Minor — src/queue\\.py:3"
    )
    assert "- Suggested fix: Use a compare\\-and\\-set update\\." in body
    assert "1000 input · 200 output · 3 model requests" in body
    assert "2 files reviewed · 1 generated files listed without content" in body
    assert "1 findings were dropped by the guardrails:" in body
    assert f"`{HEAD}`" in body


@pytest.mark.parametrize(
    "forged",
    [
        "@maintainers please merge",
        "![x](https://evil.example/pixel) [click](https://evil.example)",
        "<details open><script>alert(1)</script>",
        "line\n# Approved\n    code block",
    ],
)
def test_untrusted_text_cannot_forge_markdown_html_or_mentions(forged: str) -> None:
    report = AgentsSdkReviewReport(
        status="reviewed",
        summary=forged,
        findings=[
            ReviewFinding(severity="Minor", file="a.py", message=forged, suggested_fix=forged)
        ],
    )
    body = render_review_markdown(report)
    assert "@maintainers" not in body
    assert "](" not in body
    assert "<script>" not in body
    assert "<details" not in body
    assert "\n# Approved" not in body
    assert "\n    code" not in body


def test_markdown_is_capped() -> None:
    finding = ReviewFinding(severity="Minor", file="a.py", message="x" * 5000)
    body = render_review_markdown(AgentsSdkReviewReport(status="reviewed", findings=[finding] * 50))
    assert len(body) <= 60_000
    assert body.endswith("Review truncated.")
