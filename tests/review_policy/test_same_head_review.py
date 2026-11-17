"""Same-head SHA review skip (#1490)."""

from __future__ import annotations

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
