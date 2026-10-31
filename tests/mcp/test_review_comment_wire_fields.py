"""Inline review comments reach GitHub with only the fields it accepts.

GitHub's create-review endpoint maps ``comments[]`` onto the GraphQL
``DraftPullRequestReviewThread`` input and answers any unknown key with a 422
(``Variable $threads ... invalid value for N.fingerprint (Field is not defined
on DraftPullRequestReviewThread)``). The publisher's internal ``fingerprint``
key did exactly that on every review, so the recovery ladder fell back to a
bare COMMENT review and every inline comment was lost. The fingerprint must
keep travelling as the hidden body marker that dedup and carryover read.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import pytest
from tests.support.publication import (
    RecordingReviewGitHub,
    finding,
    inline_fingerprints,
    publication_ctx,
    submission_fingerprints,
    submit_verdict,
)

from mergecraft.mcp.review import _github_review_request, publish_pull_request_review

if TYPE_CHECKING:
    from pathlib import Path

# The REST names of the GraphQL thread fields GitHub accepts:
# path, line, side, startLine, startSide, body.
_GITHUB_COMMENT_FIELDS = frozenset({"path", "line", "side", "start_line", "start_side", "body"})


class _StrictReviewGitHub(RecordingReviewGitHub):
    """Rejects a review the way GitHub does when a comment carries an unknown field."""

    async def create_review(
        self, owner: str, repo: str, pull_number: int, **payload: Any
    ) -> dict[str, Any]:
        for index, comment in enumerate(payload.get("comments") or []):
            unknown = sorted(set(comment) - _GITHUB_COMMENT_FIELDS)
            if unknown:
                self.review_payloads.append(dict(payload))
                request = httpx.Request("POST", "https://api.github.com/repos/acme/demo/pulls/7")
                message = (
                    f"Variable $threads of type [DraftPullRequestReviewThread] was provided "
                    f"invalid value for {index}.{unknown[0]} (Field is not defined on "
                    f"DraftPullRequestReviewThread)"
                )
                response = httpx.Response(
                    422,
                    request=request,
                    json={"message": "Unprocessable Entity", "errors": [message]},
                )
                raise httpx.HTTPStatusError("422", request=request, response=response)
        return await super().create_review(owner, repo, pull_number, **payload)


def _two_findings() -> list[dict[str, Any]]:
    return [
        finding("Unchecked return value from the parser.", line=12),
        finding("Off-by-one in the page loop.", line=20),
    ]


def test_wire_request_keeps_only_github_comment_fields() -> None:
    """Every key outside GitHub's thread input is dropped; accepted keys pass unchanged."""
    payload: dict[str, Any] = {
        "event": "REQUEST_CHANGES",
        "body": "Review body",
        "commit_id": "abc123",
        "comments": [
            {
                "path": "src/app.py",
                "body": "Finding.\n<!-- mergecraft-finding:abc -->",
                "line": 20,
                "side": "RIGHT",
                "start_line": 18,
                "start_side": "RIGHT",
                "fingerprint": "abc",
                "collateral": ["src/other.py"],
            }
        ],
    }

    request = _github_review_request(payload)

    assert request["comments"] == [
        {
            "path": "src/app.py",
            "body": "Finding.\n<!-- mergecraft-finding:abc -->",
            "line": 20,
            "side": "RIGHT",
            "start_line": 18,
            "start_side": "RIGHT",
        }
    ]
    assert {k: v for k, v in request.items() if k != "comments"} == {
        "event": "REQUEST_CHANGES",
        "body": "Review body",
        "commit_id": "abc123",
    }
    # The caller's payload keeps its fingerprint for the 422 recovery ladder.
    assert payload["comments"][0]["fingerprint"] == "abc"


def test_wire_request_without_comments_is_unchanged() -> None:
    payload: dict[str, Any] = {"event": "COMMENT", "body": "Body"}

    assert _github_review_request(payload) == payload


@pytest.mark.asyncio
async def test_published_inline_comments_carry_only_github_fields(tmp_path: Path) -> None:
    """The posted ``comments[]`` hold only accepted fields, and stay inline."""
    github = _StrictReviewGitHub()
    ctx = publication_ctx(tmp_path, github=github, trust_tier="trusted")
    await submit_verdict(ctx, "request_changes", _two_findings())

    result = await publish_pull_request_review(ctx)

    assert result["success"] is True
    assert "commentFallbackDueTo422" not in result
    assert ctx.tool_state.review_comment_fallback_applied is False
    assert len(github.review_payloads) == 1
    posted = github.review_payloads[0]
    comments = list(posted.get("comments") or [])
    assert len(comments) == 2
    for comment in comments:
        assert set(comment) <= _GITHUB_COMMENT_FIELDS
    assert sorted((str(c["path"]), int(c["line"])) for c in comments) == [
        ("src/app.py", 12),
        ("src/app.py", 20),
    ]


@pytest.mark.asyncio
async def test_fingerprints_survive_as_body_markers_and_in_the_ledger(tmp_path: Path) -> None:
    """Dedup and carryover still see every finding after the key is stripped."""
    github = _StrictReviewGitHub()
    ctx = publication_ctx(tmp_path, github=github, trust_tier="trusted")
    await submit_verdict(ctx, "request_changes", _two_findings())
    expected = submission_fingerprints(ctx)
    assert len(expected) == 2

    await publish_pull_request_review(ctx)

    posted = github.review_payloads[0]
    assert inline_fingerprints(posted) == expected
    ledger = ctx.tool_state.finding_ledger
    assert ledger is not None
    assert {record.fingerprint for record in ledger.records() if record.state == "open"} >= (
        expected
    )
    receipt = ctx.tool_state.review
    assert receipt is not None
    assert receipt.inline_fingerprints is not None
    assert set(receipt.inline_fingerprints) == expected
