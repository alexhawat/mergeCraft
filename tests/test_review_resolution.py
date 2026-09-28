"""Resolution transition: findings a re-review no longer raises (C4).

A thread is retired only when every one of these holds:

* it is open, and every comment in it is mergeCraft's: the body carries a
  mergeCraft marker **and** the author login is in the run's expected-publisher
  set (the shared ``github-actions[bot]`` login never is);
* its anchored line falls inside an incremental-diff hunk for its path
  (``changed_lines``), or GitHub marks it outdated. A thread whose line nobody
  touched does not qualify just because something else in the file moved;
* none of its fingerprints are still raised anywhere in the terminal
  submission (inline, demoted to the body, or deferred).

An unknown line or an unknown author resolves nothing, and an empty publisher
set resolves nothing and says so once. The signature is
``resolvable_thread_ids(threads, *, current_fingerprints, changed_lines,
publishers)``.
"""

from __future__ import annotations

from typing import Any

import pytest

from mergecraft.review_resolution import finding_fingerprints_in, resolvable_thread_ids
from mergecraft.review_taxonomy import stamp_finding_fingerprint

_FIXED = stamp_finding_fingerprint(path="src/app.py", body="Unchecked index.")
_STILL_THERE = stamp_finding_fingerprint(path="src/app.py", body="Missing timeout.")
_FIXED_FP = next(iter(finding_fingerprints_in(_FIXED)))
_STILL_FP = next(iter(finding_fingerprints_in(_STILL_THERE)))

_PUBLISHER = "mergecraft-app[bot]"
_PUBLISHERS = frozenset({_PUBLISHER})
# The hunk the new commits touched: lines 10-15 of ``src/app.py``.
_TOUCHED: dict[str, list[range]] = {"src/app.py": [range(10, 16)]}


def _thread(
    *,
    thread_id: str = "T1",
    body: str = _FIXED,
    path: str = "src/app.py",
    line: int | None = 12,
    author: str | None = _PUBLISHER,
    outdated: bool = False,
    resolved: bool = False,
    extra_comments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    comments = [{"body": body, "path": path, "line": line, "author": author}]
    comments.extend(extra_comments or [])
    return {
        "threadId": thread_id,
        "isResolved": resolved,
        "isOutdated": outdated,
        "comments": comments,
    }


def _resolve(
    threads: list[dict[str, Any]],
    *,
    current: frozenset[str] = frozenset(),
    lines: dict[str, list[range]] | None = None,
    publishers: frozenset[str] = _PUBLISHERS,
) -> list[str]:
    return resolvable_thread_ids(
        threads,
        current_fingerprints=current,
        changed_lines=_TOUCHED if lines is None else lines,
        publishers=publishers,
    )


def test_fingerprints_are_extracted_from_a_stamped_body() -> None:
    assert finding_fingerprints_in(_FIXED) == frozenset({_FIXED_FP})
    assert finding_fingerprints_in("no marker here") == frozenset()


# ── the five original cases, on the line-and-author signature ────────────────


def test_thread_is_resolvable_when_its_finding_is_gone_from_touched_code() -> None:
    assert _resolve([_thread()], current=frozenset({_STILL_FP})) == ["T1"]


def test_re_raised_finding_is_never_resolved() -> None:
    assert _resolve([_thread()], current=frozenset({_FIXED_FP})) == []


def test_untouched_file_is_never_resolved() -> None:
    """An incremental scope that never looked at the file proves nothing about it."""
    assert _resolve([_thread()], lines={"src/other.py": [range(1, 100)]}) == []


def test_thread_with_a_human_reply_is_left_alone() -> None:
    thread = _thread(
        extra_comments=[
            {"body": "Disagree, keeping this.", "path": "src/app.py", "line": 12, "author": "dev"}
        ]
    )
    assert _resolve([thread]) == []


def test_already_resolved_and_unstamped_threads_are_skipped() -> None:
    threads = [
        _thread(thread_id="T-resolved", resolved=True),
        _thread(thread_id="T-unstamped", body="plain comment *via mergecraft*"),
    ]
    assert _resolve(threads) == []


# ── line overlap ──────────────────────────────────────────────────────────────


def test_a_thread_whose_line_is_outside_every_hunk_stays_open_even_when_its_file_changed() -> None:
    """The file moved, but not the line the finding pointed at."""
    assert _resolve([_thread(line=3)]) == []


@pytest.mark.parametrize("line", [10, 15])
def test_hunk_boundaries_are_inclusive(line: int) -> None:
    assert _resolve([_thread(line=line)]) == ["T1"]


@pytest.mark.parametrize("line", [9, 16])
def test_the_line_just_outside_a_hunk_does_not_qualify(line: int) -> None:
    assert _resolve([_thread(line=line)]) == []


def test_an_outdated_thread_qualifies_without_line_overlap() -> None:
    """GitHub marks the thread outdated: the anchored code is gone."""
    assert _resolve([_thread(line=3, outdated=True)]) == ["T1"]


def test_an_unknown_line_resolves_nothing() -> None:
    assert _resolve([_thread(line=None)]) == []


def test_no_changed_lines_resolves_only_outdated_threads() -> None:
    threads = [_thread(thread_id="T-current"), _thread(thread_id="T-outdated", outdated=True)]
    assert _resolve(threads, lines={}) == ["T-outdated"]


# ── author identity ───────────────────────────────────────────────────────────


def test_a_marked_thread_by_a_login_outside_the_publisher_set_stays_open() -> None:
    """Anyone can type the marker; the author is what proves mergeCraft posted it."""
    assert _resolve([_thread(author="mallory")]) == []


def test_a_marked_thread_by_the_shared_actions_bot_stays_open() -> None:
    """``github-actions[bot]`` is a shared identity any same-repo workflow can post as."""
    assert _resolve([_thread(author="github-actions[bot]")]) == []


def test_a_comment_with_no_author_resolves_nothing() -> None:
    assert _resolve([_thread(author=None)]) == []


def test_an_empty_publisher_set_resolves_nothing_and_says_so_once() -> None:
    from loguru import logger

    captured: list[str] = []
    sink_id = logger.add(lambda message: captured.append(str(message)), level="INFO")
    try:
        resolved = _resolve(
            [_thread(thread_id="T1"), _thread(thread_id="T2", outdated=True)],
            publishers=frozenset(),
        )
    finally:
        logger.remove(sink_id)

    assert resolved == []
    about_identity = [line for line in captured if "publisher" in line.lower()]
    assert len(about_identity) == 1, captured


def test_an_expected_publisher_outdated_thread_whose_finding_is_gone_resolves() -> None:
    """Happy path, the fail-safe rules do not over-reject."""
    threads = [_thread(line=3, outdated=True)]
    assert _resolve(threads, current=frozenset({_STILL_FP})) == ["T1"]
