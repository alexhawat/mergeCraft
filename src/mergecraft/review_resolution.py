"""Resolution transition for findings a re-review no longer raises (C4).

``stamp_finding_fingerprint()`` gives every inline finding a stable identity, and
an ``IncrementalReview`` uses that identity to avoid re-raising a finding it
already posted. The opposite transition was missing: a finding that *was* raised,
whose code the new commits touched, and which the fresh review no longer raises,
is fixed — its thread should stop asking the author to act.

This module makes no network calls. It decides which review threads that
transition applies to; the MCP layer fetches and resolves them.

Exports:
    finding_fingerprints_in: Extract finding identities from comment text.
    is_mergecraft_comment: Whether a comment body was written by the reviewer.
    resolvable_thread_ids: Pick threads a re-review has evidently resolved.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Final

from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

_FINDING_MARKER_RE: Final[re.Pattern[str]] = re.compile(
    r"<!-- mergecraft-finding:v1:([0-9a-f]+) -->"
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


def _comment_line(comment: dict[str, Any]) -> int | None:
    """Return the comment's anchored line, or ``None`` when GitHub gave none."""
    raw = comment.get("line")
    if isinstance(raw, bool) or not isinstance(raw, int | str):
        return None
    try:
        line = int(raw)
    except ValueError:
        return None
    return line if line > 0 else None


def _line_was_touched(
    path: str, line: int | None, changed_lines: Mapping[str, Sequence[range]]
) -> bool:
    """Whether ``line`` of ``path`` falls inside one of the changed ranges."""
    if not path or line is None:
        return False
    return any(line in hunk for hunk in changed_lines.get(path) or ())


def _is_expected_publisher_comment(comment: dict[str, Any], publishers: frozenset[str]) -> bool:
    """Whether ``comment`` carries a mergeCraft marker and an expected-publisher author.

    Thread comments name their author as a bare login (``author``); the shared
    authorship rule reads ``user.login``, so the login is lifted into that shape
    rather than re-implementing the rule here.
    """
    # Imported here: ``mergecraft.review`` pulls in the agent and MCP packages,
    # which import this module back through ``findings.select``.
    from mergecraft.review.authorship import is_mergecraft_authored

    login = str(comment.get("author") or "").strip()
    if not login:
        return False
    item = {"body": str(comment.get("body") or ""), "user": {"login": login}}
    return is_mergecraft_authored(item, publishers=publishers)


def resolvable_thread_ids(
    threads: list[dict[str, Any]],
    *,
    current_fingerprints: frozenset[str] | set[str],
    changed_lines: Mapping[str, Sequence[range]],
    publishers: frozenset[str],
) -> list[str]:
    """Return the ids of threads this run has evidently resolved.

    A thread qualifies only when every one of these holds:

    - it is still open (an already-resolved thread needs nothing);
    - mergeCraft raised it — at least one comment carries a finding fingerprint;
    - **every comment is mergeCraft's**: its body carries a mergeCraft marker
      *and* its author login is in ``publishers``, the run's expected-publisher
      set. The marker alone proves nothing (anyone can type it), and a human
      reply makes the thread a conversation that must not be closed because the
      code moved. A comment with no author is not attributable;
    - the code it points at changed: the root comment's anchored line falls
      inside a ``changed_lines`` range for its path, or GitHub marks the thread
      outdated. A thread whose line nobody touched does not qualify merely
      because something else in the file moved, and an unknown line proves
      nothing;
    - none of the thread's fingerprints are in ``current_fingerprints``.

    An empty ``publishers`` set proves no authorship, so nothing resolves and
    one line says why. The shared ``github-actions[bot]`` login never counts as
    a publisher, even when a caller passes it.

    Args:
        threads: Threads in the shape ``get_review_comments`` returns.
        current_fingerprints: Fingerprints still raised anywhere in this run's
            submission (inline, demoted to the body, or deferred).
        changed_lines: ``{path: [range, ...]}`` of new-file lines the commits
            under review touched.
        publishers: The run's expected-publisher logins.

    Returns:
        Thread ids, in input order. Empty when nothing qualifies.
    """
    # Imported here: ``mergecraft.review`` pulls in the agent and MCP packages,
    # which import this module back through ``findings.select``.
    from mergecraft.review.authorship import GITHUB_ACTIONS_BOT_LOGIN

    # The shared Actions login is never an expected publisher, whoever passes it.
    publishers = frozenset(
        login for login in publishers if login.strip().casefold() != GITHUB_ACTIONS_BOT_LOGIN
    )
    if not publishers:
        logger.info(
            "thread retirement skipped: no expected publisher identity proves which "
            "review threads mergeCraft wrote, so none are resolved"
        )
        return []
    still_raised = set(current_fingerprints)
    resolvable: list[str] = []
    for thread in threads or []:
        thread_id = str(thread.get("threadId") or "")
        if not thread_id or thread.get("isResolved"):
            continue
        comments = list(thread.get("comments") or [])
        if not comments:
            continue
        if not all(_is_expected_publisher_comment(c, publishers) for c in comments):
            continue
        fingerprints: set[str] = set()
        for comment in comments:
            fingerprints |= finding_fingerprints_in(str(comment.get("body") or ""))
        if not fingerprints:
            continue
        # The thread's anchor is its root comment; replies share it.
        anchor = comments[0]
        touched = bool(thread.get("isOutdated")) or _line_was_touched(
            str(anchor.get("path") or ""), _comment_line(anchor), changed_lines
        )
        if not touched:
            continue
        if fingerprints & still_raised:
            continue
        resolvable.append(thread_id)
    return resolvable


__all__ = ["finding_fingerprints_in", "is_mergecraft_comment", "resolvable_thread_ids"]
