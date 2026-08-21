"""Which review threads survive a merge, and what they become.

This module is pure. It decides which of a pull request's inline threads still
represent open work at merge time, and renders each into issue text; the sweep
layer does the network calls.

The selection is deliberately conservative — a carryover issue nobody wanted is
worse than a finding that stays on the PR, because the first trains maintainers
to ignore the label. A thread carries over only when mergeCraft raised it, the
author never resolved it, and no human ever answered it. A human reply means
somebody already made a call on that finding, and re-filing it overrules them.

Exports:
    CarryoverFinding: One surviving inline finding, ready to file.
    carryover_findings: Pure selection over fetched threads.
    issue_body: Render the issue body for one finding.
    issue_title: Render the issue title for one finding.
"""

from __future__ import annotations

import re
from typing import Any, Final

from pydantic import BaseModel, Field

from mergecraft.review_resolution import finding_fingerprints_in, is_mergecraft_comment
from mergecraft.review_taxonomy import (
    FINDING_MARKER_PREFIX,
    finding_fingerprint,
)

_MARKER_RE: Final[re.Pattern[str]] = re.compile(r"<!-- mergecraft-finding:v1:[0-9a-f]+ -->")
# The dedupe key is scoped to the pull request, not just the finding. A finding
# reintroduced by a later PR is a regression and deserves its own issue; keying
# on the fingerprint alone would let a long-closed issue silently suppress it.
CARRYOVER_MARKER_PREFIX: Final[str] = "<!-- mergecraft-carryover:v1:"
_CARRYOVER_RE: Final[re.Pattern[str]] = re.compile(
    r"<!-- mergecraft-carryover:v1:(\d+):([0-9a-f]+) -->"
)
_SENTENCE_END_RE: Final[re.Pattern[str]] = re.compile(r"(?<=[.!?])\s")
# Backticks and asterisks only: `_` carries meaning inside the identifiers these
# findings quote, and stripping it turns `setup_timeout_s` into `setuptimeouts`.
_INLINE_MARKUP_RE: Final[re.Pattern[str]] = re.compile(r"[`*]+")
_WHITESPACE_RE: Final[re.Pattern[str]] = re.compile(r"\s+")

# GitHub accepts 256; a title that long is unreadable in a list view.
_TITLE_LIMIT: Final[int] = 110

DEFAULT_LABEL: Final[str] = "mergecraft-carryover"


class CarryoverFinding(BaseModel):
    """One inline finding that outlived its pull request.

    Attributes:
        fingerprint: Stable finding identity — the stamped marker when present,
            otherwise recomputed from path and body so pre-fingerprint comments
            still dedupe.
        path: Repository-relative file the thread anchors to.
        line: Anchor line, or ``None`` when GitHub dropped it as outdated.
        body: The finding text, with the fingerprint marker stripped.
        url: Permalink to the review comment.
        thread_id: GraphQL thread node id.
        comment_id: REST database id of the thread's root comment.
        author: Login that raised the finding.
        created_at: ISO-8601 timestamp of the root comment.
        is_resolved: Whether GitHub reports the thread resolved.
        is_outdated: Whether GitHub moved the anchor off the current diff.
        answered_by: Non-mergeCraft logins that replied in the thread.
    """

    fingerprint: str
    path: str
    line: int | None = None
    body: str
    url: str = ""
    thread_id: str = ""
    comment_id: int | None = None
    author: str = ""
    created_at: str = ""
    is_resolved: bool = False
    is_outdated: bool = False
    answered_by: list[str] = Field(default_factory=list)


def strip_marker(body: str) -> str:
    """Return ``body`` without its finding fingerprint marker."""
    return _MARKER_RE.sub("", body or "").strip()


def carryover_key(*, pull_number: int, fingerprint: str) -> str:
    """Return the dedupe identity for one finding on one pull request."""
    return f"{pull_number}:{fingerprint}"


def carryover_keys_in(text: str) -> frozenset[str]:
    """Return every carryover key recorded in ``text``."""
    return frozenset(f"{pr}:{fp}" for pr, fp in _CARRYOVER_RE.findall(text or ""))


def _fingerprint_for(*, path: str, body: str) -> str:
    """Return the thread's stamped fingerprint, or derive one from its content.

    Deriving uses the same hash as ``stamp_finding_fingerprint`` so a comment
    predating fingerprints still gets a stable, deterministic identity. It is
    not guaranteed to equal what a fresh stamp of the same finding would
    produce — the derivation hashes whatever the posted comment ended up
    containing, trailer text included — which is enough for dedupe, since both
    sides of the comparison derive it the same way.
    """
    stamped = sorted(finding_fingerprints_in(body))
    if stamped:
        return stamped[0]
    return finding_fingerprint(path=path, body=body)


def carryover_findings(
    threads: list[dict[str, Any]],
    *,
    include_resolved: bool = False,
    include_answered: bool = False,
) -> list[CarryoverFinding]:
    """Return the findings a merge would bury, in thread order.

    A thread qualifies only when every one of these holds:

    - it is still open, unless ``include_resolved`` — a resolved thread is a
      finding the author already dealt with;
    - mergeCraft raised it — the root comment carries a finding fingerprint or
      the review footer. Human review threads belong to their humans;
    - nobody else spoke in it, unless ``include_answered`` — a human reply means
      the finding already got an answer, and re-filing it overrules that answer;
    - its comments were read in full, unless ``include_answered``. A thread
      longer than one page might hold a human reply past the cap, and a sweep
      that cannot see every reply cannot claim nobody answered.

    Args:
        threads: Threads in the shape :func:`fetch_review_threads` returns.
        include_resolved: Keep threads the author resolved.
        include_answered: Keep threads a human replied to, and threads whose
            comment list was truncated.

    Returns:
        Findings in input order. Empty when nothing qualifies.
    """
    findings: list[CarryoverFinding] = []
    for thread in threads or []:
        comments = list(thread.get("comments") or [])
        if not comments:
            continue

        root = comments[0]
        root_body = str(root.get("body") or "")
        if not is_mergecraft_comment(root_body):
            continue
        if thread.get("isResolved") and not include_resolved:
            continue

        answered_by = [
            str(c.get("author") or "")
            for c in comments[1:]
            if not is_mergecraft_comment(str(c.get("body") or ""))
        ]
        if not include_answered and (answered_by or thread.get("commentsTruncated")):
            continue

        path = str(root.get("path") or "")
        line_raw = root.get("line")
        findings.append(
            CarryoverFinding(
                fingerprint=_fingerprint_for(path=path, body=root_body),
                path=path,
                line=int(line_raw) if isinstance(line_raw, int) else None,
                body=strip_marker(root_body),
                url=str(root.get("url") or ""),
                thread_id=str(thread.get("threadId") or ""),
                comment_id=root.get("id") if isinstance(root.get("id"), int) else None,
                author=str(root.get("author") or ""),
                created_at=str(root.get("createdAt") or ""),
                is_resolved=bool(thread.get("isResolved")),
                is_outdated=bool(thread.get("isOutdated")),
                answered_by=answered_by,
            )
        )
    return findings


def _summarize(body: str) -> str:
    """Return a one-line gist of a finding body for use in a title."""
    first_line = next(
        (
            line.strip()
            for line in strip_marker(body).splitlines()
            if line.strip() and not line.lstrip().startswith(("#", ">", "```", "<"))
        ),
        "",
    )
    sentence = _SENTENCE_END_RE.split(first_line, maxsplit=1)[0] if first_line else ""
    cleaned = _WHITESPACE_RE.sub(" ", _INLINE_MARKUP_RE.sub("", sentence)).strip()
    return cleaned or "unresolved review finding"


def _anchor(finding: CarryoverFinding) -> str:
    """Return ``path:line`` (or just ``path``) for display."""
    if not finding.path:
        return "(no file)"
    return f"{finding.path}:{finding.line}" if finding.line else finding.path


def issue_title(finding: CarryoverFinding, *, pull_number: int) -> str:
    """Return the issue title for ``finding``, bounded to a readable length."""
    prefix = f"[carryover #{pull_number}] {_anchor(finding)} — "
    summary = _summarize(finding.body)
    room = _TITLE_LIMIT - len(prefix)
    if room < 20:  # pathologically long path — let the summary carry the title
        prefix = f"[carryover #{pull_number}] "
        room = _TITLE_LIMIT - len(prefix)
    if len(summary) > room:
        summary = summary[: room - 1].rstrip() + "…"
    return f"{prefix}{summary}"


def issue_body(finding: CarryoverFinding, *, pull_number: int) -> str:
    """Return the issue body for ``finding``, carrying its identity forward.

    Two trailing markers. The carryover key is what makes the sweep idempotent:
    a later run reads it back out of the filed issue and skips this finding on
    this pull request, while leaving the same finding free to be filed again if
    a later pull request reintroduces it. The bare finding fingerprint is kept
    alongside it so anything already reading finding markers still sees one.
    """
    lines = [
        f"Carried over from #{pull_number}. mergeCraft raised this inline and the "
        "thread was never resolved before the pull request closed.",
        "",
        f"- **File:** `{_anchor(finding)}`",
    ]
    if finding.url:
        lines.append(f"- **Thread:** {finding.url}")
    if finding.author:
        raised = f"- **Raised by:** `{finding.author}`"
        if finding.created_at:
            raised += f" on {finding.created_at}"
        lines.append(raised)
    if finding.is_outdated:
        lines.append(
            "- **Note:** GitHub marked the anchor outdated — the code may have "
            "moved since the finding was written."
        )
    if finding.answered_by:
        replied = ", ".join(f"`{login}`" for login in dict.fromkeys(finding.answered_by))
        lines.append(f"- **Replied in thread:** {replied}")

    lines += [
        "",
        "---",
        "",
        finding.body,
        "",
        "---",
        "",
        f"{CARRYOVER_MARKER_PREFIX}{pull_number}:{finding.fingerprint} -->",
        f"{FINDING_MARKER_PREFIX}{finding.fingerprint} -->",
    ]
    return "\n".join(lines)


__all__ = [
    "CARRYOVER_MARKER_PREFIX",
    "DEFAULT_LABEL",
    "CarryoverFinding",
    "carryover_findings",
    "carryover_key",
    "carryover_keys_in",
    "issue_body",
    "issue_title",
    "strip_marker",
]
