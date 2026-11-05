"""Human finding outcomes classifier (#1165)."""

from __future__ import annotations

from mergecraft.findings.outcomes import classify_thread_outcome

_MERGEcraft_MARKER = "<!-- mergecraft-finding:v1:abc123def456 -->\n*via mergecraft*"


def test_resolved_thread_is_fixed() -> None:
    thread = {
        "id": "t1",
        "isResolved": True,
        "comments": [
            {
                "author": "mergecraft[bot]",
                "body": _MERGEcraft_MARKER,
                "path": "a.py",
                "line": 1,
            }
        ],
    }
    outcome, _reason = classify_thread_outcome(
        thread, publishers=frozenset({"mergecraft[bot]"}), merged=True
    )
    assert outcome == "fixed"


def test_human_rejection() -> None:
    thread = {
        "id": "t2",
        "isResolved": False,
        "comments": [
            {
                "author": "mergecraft[bot]",
                "body": _MERGEcraft_MARKER,
                "path": "a.py",
                "line": 1,
            },
            {"author": "human", "body": "This is wrong — not valid."},
        ],
    }
    outcome, _reason = classify_thread_outcome(
        thread, publishers=frozenset({"mergecraft[bot]"}), merged=False
    )
    assert outcome == "rejected"


def test_merged_with_open_thread_is_ignored() -> None:
    thread = {
        "id": "t3",
        "isResolved": False,
        "comments": [
            {
                "author": "mergecraft[bot]",
                "body": _MERGEcraft_MARKER,
                "path": "a.py",
                "line": 1,
            }
        ],
    }
    outcome, _reason = classify_thread_outcome(
        thread, publishers=frozenset({"mergecraft[bot]"}), merged=True
    )
    assert outcome == "ignored"
