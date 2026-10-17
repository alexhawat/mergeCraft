"""Carry-over authorship: a thread is mergeCraft's only through the shared authorship rule.

The sweep used to decide "mergeCraft raised this" from the root comment's body marker
alone, and "a human answered" from a reply lacking the marker. Anyone can type either
string. The rule is now the one thread retirement uses: the marker **and** an author in
the run's expected-publisher set; ``github-actions[bot]`` never counts; an empty set
trusts nothing.
"""

from __future__ import annotations

from typing import Any

from mergecraft.findings.select import carryover_findings
from mergecraft.review_resolution import finding_fingerprints_in
from mergecraft.review_taxonomy import stamp_finding_fingerprint

_PATH = "src/app.py"
_BODY = stamp_finding_fingerprint(path=_PATH, body="Missing timeout on the retry loop.")
_FP = next(iter(finding_fingerprints_in(_BODY)))
_APP = "mergecraft-app[bot]"
_PUBLISHERS = frozenset({_APP})


def _comment(*, comment_id: int, body: str, author: str) -> dict[str, Any]:
    return {
        "id": comment_id,
        "body": body,
        "path": _PATH,
        "line": 42,
        "author": author,
        "url": f"https://github.com/o/r/pull/7#discussion_r{comment_id}",
        "createdAt": "2026-08-13T07:13:58Z",
    }


def _thread(*comments: dict[str, Any]) -> dict[str, Any]:
    return {"threadId": "T1", "isResolved": False, "isOutdated": False, "comments": list(comments)}


def _root(author: str, body: str = _BODY) -> dict[str, Any]:
    return _comment(comment_id=1, body=body, author=author)


def test_a_user_who_copies_the_marker_does_not_get_a_thread_swept() -> None:
    forged = _thread(_root("some-user"))

    assert carryover_findings([forged], publishers=_PUBLISHERS) == []


def test_marker_plus_an_expected_publisher_is_swept() -> None:
    findings = carryover_findings([_thread(_root(_APP))], publishers=_PUBLISHERS)

    assert [f.fingerprint for f in findings] == [_FP]
    assert findings[0].author == _APP


def test_an_empty_publisher_set_sweeps_nothing() -> None:
    assert carryover_findings([_thread(_root(_APP))], publishers=frozenset()) == []


def test_the_shared_actions_login_never_counts_even_when_passed() -> None:
    shared = "github-actions[bot]"
    findings = carryover_findings([_thread(_root(shared))], publishers=frozenset({shared, _APP}))

    assert findings == []


def test_a_publisher_comment_without_a_marker_is_not_a_finding() -> None:
    plain = _thread(_root(_APP, body="Thanks for the update."))

    assert carryover_findings([plain], publishers=_PUBLISHERS) == []


def test_author_match_is_case_insensitive() -> None:
    thread = _thread(_root("MergeCraft-App[BOT]"))

    assert len(carryover_findings([thread], publishers=_PUBLISHERS)) == 1


def test_a_mergecraft_reply_without_a_marker_is_not_a_human_answer() -> None:
    own_reply = _comment(comment_id=2, body="Still open after the latest push.", author=_APP)

    findings = carryover_findings([_thread(_root(_APP), own_reply)], publishers=_PUBLISHERS)

    assert len(findings) == 1
    assert findings[0].answered_by == []


def test_a_human_reply_carrying_a_copied_marker_still_answers_the_thread() -> None:
    pasted = _comment(comment_id=2, body=f"Not an issue.\n{_BODY}", author="alex")

    assert carryover_findings([_thread(_root(_APP), pasted)], publishers=_PUBLISHERS) == []
    kept = carryover_findings(
        [_thread(_root(_APP), pasted)], publishers=_PUBLISHERS, include_answered=True
    )
    assert kept[0].answered_by == ["alex"]


def test_a_reply_with_no_named_author_is_treated_as_a_human_answer() -> None:
    anonymous = _comment(comment_id=2, body="ok", author="")

    assert carryover_findings([_thread(_root(_APP), anonymous)], publishers=_PUBLISHERS) == []
