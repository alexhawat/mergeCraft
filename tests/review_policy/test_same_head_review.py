"""Same-head SHA review skip (#1490)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mergecraft.action.review_policy import _is_completed_review
from mergecraft.findings.ledger import DETERMINISTIC_RECORD_MARKER, REVIEW_BODY_MARKER
from mergecraft.review_policy.same_head_review import (
    trusted_completed_review_on_head,
)


def _completed_body() -> str:
    """A completed comment in the legacy record layout without a risk row."""
    return (
        f"{DETERMINISTIC_RECORD_MARKER}\n"
        "### mergeCraft run record\n"
        "\n"
        "- **Outcome:** `passed`\n"
        "- **Verdict diagnostic:** `approved`\n"
        "- **Decision:** `success` — ok\n"
        "- **Publication path:** `publish_pull_request_review`\n"
        "\n### Pre-merge checks\n"
        f"{REVIEW_BODY_MARKER}\n"
        "prose"
    )


def test_trusted_completed_review_on_matching_head() -> None:
    sha = "a" * 40
    review = {
        "commit_id": sha,
        "state": "COMMENTED",
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
        "body": _completed_body().replace("`passed`", "`inconclusive`"),
    }
    assert trusted_completed_review_on_head([review], sha) is None


def test_trusted_completed_review_rejects_invalid_sha() -> None:
    review = {"commit_id": "abc", "state": "APPROVED", "body": _completed_body()}
    assert trusted_completed_review_on_head([review], "abc") is None


def test_commented_review_requires_body_marker() -> None:
    sha = "c" * 40
    review = {
        "commit_id": sha,
        "state": "COMMENTED",
        "body": _completed_body().replace(REVIEW_BODY_MARKER, ""),
    }
    assert trusted_completed_review_on_head([review], sha) is None


@pytest.mark.parametrize("review_id", [None, 0, True, "123"])
async def test_same_head_skip_without_numeric_review_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, review_id: object
) -> None:
    from mergecraft.review_policy.same_head_review import evaluate_same_head_skip
    from tests.support.publication import RecordingReviewGitHub, publication_ctx

    sha = "e" * 40
    tctx = publication_ctx(tmp_path, github=RecordingReviewGitHub(), trust_tier="trusted")

    async def _fake_list(_ctx: object, *, pull_number: int) -> list[dict[str, Any]]:
        assert pull_number == 7
        return [
            {
                "commit_id": sha,
                "state": "CHANGES_REQUESTED",
                "body": _completed_body(),
                "id": review_id,
                "html_url": "https://example.com/?token=review-url-canary",
            }
        ]

    monkeypatch.setattr("mergecraft.mcp.checkout.list_mergecraft_reviews", _fake_list)
    decision = await evaluate_same_head_skip(tctx, head_sha=sha, pull_number=7)
    assert decision is not None
    assert f"prior review on `{sha[:12]}`" in decision.reason
    assert "review-url-canary" not in decision.reason
    assert decision.relied_on_checks == ()


@pytest.mark.parametrize(
    ("state", "skips"),
    [
        pytest.param("APPROVED", False, id="approved-is-reviewed-again"),
        pytest.param("COMMENTED", False, id="passed-record-is-reviewed-again"),
        pytest.param("CHANGES_REQUESTED", True, id="changes-requested-is-reused"),
    ],
)
async def test_same_head_skip_reuses_only_requested_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str, *, skips: bool
) -> None:
    """A pass on the same head never skips: the skip has no proof to grant approval."""
    from mergecraft.review_policy.same_head_review import evaluate_same_head_skip
    from tests.support.publication import RecordingReviewGitHub, publication_ctx

    sha = "f" * 40
    tctx = publication_ctx(tmp_path, github=RecordingReviewGitHub(), trust_tier="trusted")

    async def _fake_list(_ctx: object, *, pull_number: int) -> list[dict[str, Any]]:
        return [{"commit_id": sha, "state": state, "body": _completed_body(), "id": 9}]

    monkeypatch.setattr("mergecraft.mcp.checkout.list_mergecraft_reviews", _fake_list)
    decision = await evaluate_same_head_skip(tctx, head_sha=sha, pull_number=7)
    assert (decision is not None) is skips
    assert skips is ("requested changes" in getattr(decision, "reason", ""))


async def test_a_later_pass_on_the_same_head_is_reviewed_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the newest completed review counts: a pass after requested changes reviews."""
    from mergecraft.review_policy.same_head_review import evaluate_same_head_skip
    from tests.support.publication import RecordingReviewGitHub, publication_ctx

    sha = "d" * 40
    tctx = publication_ctx(tmp_path, github=RecordingReviewGitHub(), trust_tier="trusted")

    async def _fake_list(_ctx: object, *, pull_number: int) -> list[dict[str, Any]]:
        return [
            {"commit_id": sha, "state": "CHANGES_REQUESTED", "body": "", "id": 1},
            {"commit_id": sha, "state": "APPROVED", "body": "", "id": 2},
        ]

    monkeypatch.setattr("mergecraft.mcp.checkout.list_mergecraft_reviews", _fake_list)
    assert await evaluate_same_head_skip(tctx, head_sha=sha, pull_number=7) is None
