"""Resolution transition for findings a re-review no longer raises (C4).

``stamp_finding_fingerprint()`` gives every inline finding a stable identity, and
an ``IncrementalReview`` uses that identity to avoid re-raising a finding it
already posted. The opposite transition was missing: a finding that *was* raised,
whose code the new commits touched, and which the fresh review no longer raises,
is fixed — its thread should stop asking the author to act.

This module is pure. It decides which review threads that transition applies to;
the MCP layer does the network calls.

Exports:
    finding_fingerprints_in: Extract finding identities from comment text.
    is_mergecraft_comment: Whether a comment body was written by the reviewer.
    resolvable_thread_ids: Pick threads a re-review has evidently resolved.
"""

from __future__ import annotations

import re
from typing import Any, Final

_FINDING_MARKER_RE: Final[re.Pattern[str]] = re.compile(
    r"<!-- (?:pullfrog|mergecraft)-finding:v1:([0-9a-f]+) -->"
)
_FOOTER_MARKER: Final[str] = "*via mergecraft*"


def finding_fingerprints_in(text: str) -> frozenset[str]:
    """Return every finding fingerprint stamped into ``text``."""
    return frozenset(_FINDING_MARKER_RE.findall(text or ""))


def is_mergecraft_comment(body: str) -> bool:
    """Return whether ``body`` was written by mergeCraft rather than a human.

    A stamped finding fingerprint is the strong signal; the review footer covers
    comments posted before fingerprints existed.
    """
    return bool(_FINDING_MARKER_RE.search(body or "")) or _FOOTER_MARKER in (body or "")


def resolvable_thread_ids(
    threads: list[dict[str, Any]],
    *,
    current_fingerprints: frozenset[str] | set[str],
    changed_paths: frozenset[str] | set[str],
) -> list[str]:
    """Return the ids of threads this run has evidently resolved.

    A thread qualifies only when every one of these holds:

    - it is still open (an already-resolved thread needs nothing);
    - mergeCraft raised it — at least one comment carries a finding fingerprint;
    - **nobody else spoke in it** — every comment is mergeCraft's. A human reply
      makes the thread a conversation, and closing a conversation because the
      code moved is rude and loses context;
    - the thread's file is in ``changed_paths``, i.e. the commits under review
      actually touched that file. Without this, a finding in untouched code
      would be "resolved" purely because the incremental scope never looked at
      it;
    - none of the thread's fingerprints were raised again in this run.

    Args:
        threads: Threads in the shape ``get_review_comments`` returns.
        current_fingerprints: Fingerprints raised by the review just posted.
        changed_paths: Paths touched since the last reviewed commit.

    Returns:
        Thread ids, in input order. Empty when nothing qualifies.
    """
    resolvable: list[str] = []
    for thread in threads or []:
        thread_id = str(thread.get("threadId") or "")
        if not thread_id or thread.get("isResolved"):
            continue
        comments = list(thread.get("comments") or [])
        if not comments:
            continue
        if not all(is_mergecraft_comment(str(c.get("body") or "")) for c in comments):
            continue
        fingerprints: set[str] = set()
        paths: set[str] = set()
        for comment in comments:
            fingerprints |= finding_fingerprints_in(str(comment.get("body") or ""))
            path = str(comment.get("path") or "")
            if path:
                paths.add(path)
        if not fingerprints:
            continue
        if not paths & set(changed_paths):
            continue
        if fingerprints & set(current_fingerprints):
            continue
        resolvable.append(thread_id)
    return resolvable


__all__ = ["finding_fingerprints_in", "is_mergecraft_comment", "resolvable_thread_ids"]
