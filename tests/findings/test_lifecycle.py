"""DG2 finding lifecycle — disputed, waived, stale, resolved-by-change (G7).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG2).
Implementation: **DG2.2** — lifecycle states on top of ``findings/threads.py``.
"""

from __future__ import annotations

from typing import Any

import pytest

from mergecraft.findings.select import carryover_findings
from mergecraft.review_taxonomy import stamp_finding_fingerprint

_PATH = "src/app.py"
_BODY = stamp_finding_fingerprint(path=_PATH, body="Missing timeout on the retry loop.")


def _thread(*, resolved: bool = False, outdated: bool = False) -> dict[str, Any]:
    return {
        "threadId": "T1",
        "isResolved": resolved,
        "isOutdated": outdated,
        "comments": [
            {
                "id": 1,
                "body": _BODY,
                "path": _PATH,
                "line": 42,
                "author": "mergecraft[bot]",
                "url": "https://github.com/o/r/pull/7#discussion_r1",
                "createdAt": "2026-08-13T07:13:58Z",
            }
        ],
    }


class _FakeGitHub:
    """Minimal GraphQL stub for ``fetch_review_threads``."""

    def __init__(self, *, nodes: list[dict[str, Any]]) -> None:
        self._nodes = nodes

    async def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        return {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {"totalCount": len(self._nodes), "nodes": self._nodes}
                }
            }
        }


def test_disputed_state_is_recorded() -> None:
    """A challenged finding records ``disputed`` with a reason (G7)."""
    from mergecraft.findings.lifecycle import dispute_finding, lifecycle_state

    record = dispute_finding(
        fingerprint="abc123",
        reason="The caller already retries with backoff.",
    )

    assert record.state == "disputed"
    assert record.reason == "The caller already retries with backoff."
    assert lifecycle_state(record) == "disputed"


def test_waived_state_carries_reason_and_expiry() -> None:
    """Waivers carry an explicit reason and expiry — not a silent suppression."""
    from mergecraft.findings.lifecycle import waive_finding

    record = waive_finding(
        fingerprint="def456",
        reason="Accepted risk for this release train.",
        expires_at="2026-12-31T23:59:59Z",
    )

    assert record.state == "waived"
    assert record.reason == "Accepted risk for this release train."
    assert record.expires_at == "2026-12-31T23:59:59Z"


@pytest.mark.asyncio
async def test_resolved_by_change_still_works() -> None:
    """Regression pin: resolved threads stay normalized and out of carryover."""
    from mergecraft.findings.threads import fetch_review_threads

    resolved_node = {
        "id": "T-resolved",
        "isResolved": True,
        "isOutdated": True,
        "comments": {
            "nodes": [
                {
                    "databaseId": 9,
                    "body": _BODY,
                    "author": {"login": "mergecraft[bot]"},
                    "path": _PATH,
                    "line": 42,
                    "originalLine": 40,
                    "url": "https://github.com/o/r/pull/7#discussion_r9",
                    "createdAt": "2026-08-14T07:13:58Z",
                }
            ]
        },
    }
    github = _FakeGitHub(nodes=[resolved_node])

    page = await fetch_review_threads(github, "o", "r", 7, include_resolved=False)
    assert page.threads == []

    page_resolved = await fetch_review_threads(github, "o", "r", 7, include_resolved=True)
    thread = page_resolved.threads[0]
    assert thread["isResolved"] is True
    assert thread["isOutdated"] is True

    normalized = [
        {
            "threadId": thread["threadId"],
            "isResolved": thread["isResolved"],
            "isOutdated": thread["isOutdated"],
            "comments": thread["comments"],
        }
    ]
    assert carryover_findings(normalized) == []


def test_stale_finding_is_distinguishable_from_resolved() -> None:
    """Stale anchors are not conflated with findings resolved by the change."""
    from mergecraft.findings.lifecycle import lifecycle_state_from_thread

    stale = _thread(outdated=True, resolved=False)
    resolved = _thread(outdated=True, resolved=True)

    assert lifecycle_state_from_thread(stale) == "stale"
    assert lifecycle_state_from_thread(resolved) == "resolved-by-change"
