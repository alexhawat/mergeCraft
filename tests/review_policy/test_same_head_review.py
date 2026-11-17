"""Same-head SHA review skip (#1490)."""

from __future__ import annotations

from pathlib import Path

import pytest

from mergecraft.action.review_policy import _is_completed_review
from mergecraft.findings.ledger import DETERMINISTIC_RECORD_MARKER, REVIEW_BODY_MARKER
from mergecraft.review_policy.same_head_review import (
    trusted_completed_review_on_head,
)


def _completed_body() -> str:
    return (
        f"{DETERMINISTIC_RECORD_MARKER}\n"
        "### mergeCraft run record\n"
        "\n"
        "- **Outcome:** `passed`\n"
        "- **Verdict diagnostic:** `approved`\n"
        "- **Decision:** `success` — ok\n"
        "- **Publication path:** `publish_pull_request_review`\n"
        f"{REVIEW_BODY_MARKER}\n"
        "prose"
    )


def test_trusted_completed_review_on_matching_head() -> None:
    sha = "a" * 40
    review = {
        "commit_id": sha,
        "state": "APPROVED",
        "body": _completed_body(),
    }
    assert _is_completed_review(review)
    found = trusted_completed_review_on_head([review], sha)
    assert found is not None
    assert found["commit_id"] == sha


def test_inconclusive_review_does_not_skip() -> None:
    sha = "b" * 40
    review = {
        "commit_id": sha,
        "state": "COMMENTED",
        "body": (
            f"{DETERMINISTIC_RECORD_MARKER}\n"
            "### mergeCraft run record\n"
            "\n"
            "- **Outcome:** `inconclusive`\n"
            f"{REVIEW_BODY_MARKER}\n"
        ),
    }
    assert trusted_completed_review_on_head([review], sha) is None


def test_trusted_completed_review_rejects_invalid_sha() -> None:
    review = {"commit_id": "abc", "state": "APPROVED", "body": _completed_body()}
    assert trusted_completed_review_on_head([review], "abc") is None


def test_review_looks_spoofed_without_body_marker() -> None:
    from mergecraft.review_policy.same_head_review import review_looks_spoofed

    assert review_looks_spoofed({"body": f"{DETERMINISTIC_RECORD_MARKER}\nno marker"})
    assert not review_looks_spoofed({"body": _completed_body()})


@pytest.mark.asyncio
async def test_evaluate_same_head_skip_returns_reason(tmp_path: Path) -> None:
    from mergecraft.action.review_state import RunContext
    from mergecraft.config.settings import RepoSettings
    from mergecraft.review_policy.same_head_review import evaluate_same_head_skip
    from tests.support.publication import RecordingReviewGitHub, publication_ctx

    sha = "e" * 40
    tctx = publication_ctx(tmp_path, github=RecordingReviewGitHub(), trust_tier="trusted")
    run = RunContext(
        settings=RepoSettings(),
        tool_state=tctx.tool_state,
        tool_context=tctx,
    )

    async def _fake_list(_ctx: object, *, pull_number: int) -> list[dict]:
        return [
            {
                "commit_id": sha,
                "state": "APPROVED",
                "body": _completed_body(),
                "html_url": "https://example.com/r/2",
            }
        ]

    import mergecraft.mcp.checkout as checkout_mod

    checkout_mod.list_mergecraft_reviews = _fake_list  # type: ignore[method-assign]
    reason = await evaluate_same_head_skip(run, head_sha=sha, pull_number=7)
    assert reason is not None
    assert "trusted mergeCraft review" in reason
