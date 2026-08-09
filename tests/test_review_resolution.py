"""Resolution transition: findings a re-review no longer raises (C4)."""

from __future__ import annotations

from typing import Any

from mergecraft.review_resolution import finding_fingerprints_in, resolvable_thread_ids
from mergecraft.review_taxonomy import stamp_finding_fingerprint

_FIXED = stamp_finding_fingerprint(path="src/app.py", body="Unchecked index.")
_STILL_THERE = stamp_finding_fingerprint(path="src/app.py", body="Missing timeout.")
_FIXED_FP = next(iter(finding_fingerprints_in(_FIXED)))
_STILL_FP = next(iter(finding_fingerprints_in(_STILL_THERE)))


def _thread(
    *,
    thread_id: str = "T1",
    body: str = _FIXED,
    path: str = "src/app.py",
    resolved: bool = False,
    extra_comments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    comments = [{"body": body, "path": path, "author": "mergecraft"}]
    comments.extend(extra_comments or [])
    return {"threadId": thread_id, "isResolved": resolved, "comments": comments}


def test_fingerprints_are_extracted_from_a_stamped_body() -> None:
    assert finding_fingerprints_in(_FIXED) == frozenset({_FIXED_FP})
    assert finding_fingerprints_in("no marker here") == frozenset()


def test_thread_is_resolvable_when_its_finding_is_gone_from_touched_code() -> None:
    assert resolvable_thread_ids(
        [_thread()],
        current_fingerprints=frozenset({_STILL_FP}),
        changed_paths={"src/app.py"},
    ) == ["T1"]


def test_re_raised_finding_is_never_resolved() -> None:
    assert (
        resolvable_thread_ids(
            [_thread()],
            current_fingerprints=frozenset({_FIXED_FP}),
            changed_paths={"src/app.py"},
        )
        == []
    )


def test_untouched_file_is_never_resolved() -> None:
    """An incremental scope that never looked at the file proves nothing about it."""
    assert (
        resolvable_thread_ids(
            [_thread()],
            current_fingerprints=frozenset(),
            changed_paths={"src/other.py"},
        )
        == []
    )


def test_thread_with_a_human_reply_is_left_alone() -> None:
    thread = _thread(
        extra_comments=[{"body": "Disagree, keeping this.", "path": "src/app.py", "author": "dev"}]
    )
    assert (
        resolvable_thread_ids(
            [thread], current_fingerprints=frozenset(), changed_paths={"src/app.py"}
        )
        == []
    )


def test_already_resolved_and_unstamped_threads_are_skipped() -> None:
    threads = [
        _thread(thread_id="T-resolved", resolved=True),
        _thread(thread_id="T-unstamped", body="plain comment *via mergecraft*"),
    ]
    assert (
        resolvable_thread_ids(
            threads, current_fingerprints=frozenset(), changed_paths={"src/app.py"}
        )
        == []
    )
