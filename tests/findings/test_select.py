"""Carryover selection: which findings outlive their pull request."""

from __future__ import annotations

from typing import Any

from mergecraft.findings.select import (
    CarryoverFinding,
    carryover_findings,
    carryover_key,
    carryover_keys_in,
    issue_body,
    issue_title,
    strip_marker,
)
from mergecraft.review_resolution import finding_fingerprints_in
from mergecraft.review_taxonomy import finding_fingerprint, stamp_finding_fingerprint

_PATH = "src/app.py"
_BODY = stamp_finding_fingerprint(path=_PATH, body="Missing timeout on the retry loop.")
_FP = next(iter(finding_fingerprints_in(_BODY)))


def _thread(
    *,
    thread_id: str = "T1",
    body: str = _BODY,
    path: str = _PATH,
    line: int | None = 42,
    resolved: bool = False,
    outdated: bool = False,
    replies: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    comments: list[dict[str, Any]] = [
        {
            "id": 1,
            "body": body,
            "path": path,
            "line": line,
            "author": "mergecraft[bot]",
            "url": "https://github.com/o/r/pull/7#discussion_r1",
            "createdAt": "2026-08-13T07:13:58Z",
        }
    ]
    comments.extend(replies or [])
    return {
        "threadId": thread_id,
        "isResolved": resolved,
        "isOutdated": outdated,
        "comments": comments,
    }


def _human_reply(body: str = "Not an issue, the caller already retries.") -> dict[str, Any]:
    return {"id": 2, "body": body, "path": _PATH, "line": 42, "author": "alex"}


def test_unresolved_mergecraft_thread_carries_over() -> None:
    findings = carryover_findings([_thread()])

    assert len(findings) == 1
    assert findings[0].fingerprint == _FP
    assert findings[0].path == _PATH
    assert findings[0].line == 42
    assert findings[0].url.endswith("#discussion_r1")


def test_resolved_thread_is_dropped_unless_asked_for() -> None:
    threads = [_thread(resolved=True)]

    assert carryover_findings(threads) == []
    assert len(carryover_findings(threads, include_resolved=True)) == 1


def test_human_authored_thread_is_never_carried_over() -> None:
    human = _thread(body="I think this loop is wrong.")

    assert carryover_findings([human]) == []


def test_thread_a_human_answered_is_left_alone_by_default() -> None:
    threads = [_thread(replies=[_human_reply()])]

    assert carryover_findings(threads) == []

    kept = carryover_findings(threads, include_answered=True)
    assert len(kept) == 1
    assert kept[0].answered_by == ["alex"]


def test_mergecraft_replying_to_itself_does_not_count_as_an_answer() -> None:
    own_reply = {
        "id": 2,
        "body": stamp_finding_fingerprint(path=_PATH, body="Still open after 3f1186e."),
        "author": "mergecraft[bot]",
    }

    findings = carryover_findings([_thread(replies=[own_reply])])

    assert len(findings) == 1
    assert findings[0].answered_by == []


def test_outdated_anchor_is_reported_rather_than_dropped() -> None:
    findings = carryover_findings([_thread(outdated=True, line=None)])

    assert len(findings) == 1
    assert findings[0].is_outdated is True
    assert findings[0].line is None


def test_body_carries_forward_without_the_marker() -> None:
    finding = carryover_findings([_thread()])[0]

    assert "mergecraft-finding" not in finding.body
    assert finding.body == "Missing timeout on the retry loop."


def test_unstamped_comment_gets_the_fingerprint_it_would_have_had() -> None:
    """A comment predating fingerprints still needs a stable identity."""
    text = "Legacy finding.\n\n*via mergecraft*"
    findings = carryover_findings([_thread(body=text)])

    assert findings[0].fingerprint == finding_fingerprint(path=_PATH, body=text)


def test_empty_thread_is_skipped() -> None:
    assert carryover_findings([{"threadId": "T9", "comments": []}]) == []


def test_strip_marker_tolerates_the_legacy_prefix() -> None:
    legacy = "Body text.\n\n<!-- pullfrog-finding:v1:abc123 -->"

    assert strip_marker(legacy) == "Body text."


def test_issue_title_names_the_pr_and_the_anchor() -> None:
    finding = carryover_findings([_thread()])[0]

    title = issue_title(finding, pull_number=161)

    assert title.startswith("[carryover #161] src/app.py:42 — ")
    assert "Missing timeout on the retry loop." in title


def test_issue_title_is_bounded_and_keeps_snake_case_identifiers() -> None:
    finding = CarryoverFinding(
        fingerprint="abc",
        path="src/mergecraft/config/settings.py",
        line=323,
        body="`setup_timeout_s` has no camelCase alias while its sibling does, "
        + ("and that matters because " * 12),
    )

    title = issue_title(finding, pull_number=161)

    assert len(title) <= 110
    assert title.endswith("…")
    assert "setup_timeout_s" in title


def test_issue_title_survives_a_pathologically_long_path() -> None:
    finding = CarryoverFinding(
        fingerprint="abc", path="src/" + "nested/" * 30 + "mod.py", line=1, body="Broken."
    )

    title = issue_title(finding, pull_number=9)

    assert len(title) <= 110
    assert title.startswith("[carryover #9] ")


def test_issue_body_embeds_the_fingerprint_for_the_next_run() -> None:
    finding = carryover_findings([_thread()])[0]

    body = issue_body(finding, pull_number=161)

    assert finding_fingerprints_in(body) == frozenset({_FP})
    assert "Carried over from #161" in body
    assert "src/app.py:42" in body
    assert "#discussion_r1" in body


def test_issue_body_flags_an_outdated_anchor_and_human_replies() -> None:
    finding = carryover_findings(
        [_thread(outdated=True, replies=[_human_reply()])], include_answered=True
    )[0]

    body = issue_body(finding, pull_number=7)

    assert "outdated" in body
    assert "`alex`" in body


def test_a_thread_with_unread_comments_is_skipped_by_default() -> None:
    """Truncated comments mean a human reply could be hiding past the cap."""
    threads = [_thread() | {"commentsTruncated": True}]

    assert carryover_findings(threads) == []
    assert len(carryover_findings(threads, include_answered=True)) == 1


def test_issue_body_carries_a_pr_scoped_key_and_a_bare_fingerprint() -> None:
    finding = carryover_findings([_thread()])[0]

    body = issue_body(finding, pull_number=161)

    assert carryover_keys_in(body) == frozenset({carryover_key(pull_number=161, fingerprint=_FP)})
    assert finding_fingerprints_in(body) == frozenset({_FP})


def test_carryover_keys_are_scoped_per_pull_request() -> None:
    same = carryover_key(pull_number=7, fingerprint=_FP)

    assert same != carryover_key(pull_number=8, fingerprint=_FP)
    assert carryover_keys_in("nothing here") == frozenset()
