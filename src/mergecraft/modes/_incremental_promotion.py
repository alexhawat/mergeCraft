"""Incremental deferred-finding promotion (RC9, W3 ledger).

Promotes ledger ``deferred`` records when the incremental diff touches their cited
path, reusing the checkout incremental changed-path set.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from mergecraft.analyzers.budget import DEFERRED_SECTION_HEADING
from mergecraft.review_taxonomy import finding_fingerprint

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mergecraft.findings.ledger import FindingLedger

_DEFERRED_ROW_RE = re.compile(
    r"^\*\*(?:Critical|Major|Minor|Trivial)\*\*\s+`([^`]+)`\s+—\s+(.*)\s*$",
    re.MULTILINE,
)


def _path_from_anchor(anchor: str) -> str:
    return anchor.split(":", 1)[0] if ":" in anchor else anchor


def deferred_findings_from_reviews(reviews: Sequence[dict[str, Any]]) -> list[dict[str, object]]:
    """Parse deferred overflow rows from the newest mergeCraft review body."""
    for review in reversed(list(reviews)):
        body = str(review.get("body") or "")
        if DEFERRED_SECTION_HEADING not in body:
            continue
        section = body[body.index(DEFERRED_SECTION_HEADING) :]
        rows: list[dict[str, object]] = []
        for match in _DEFERRED_ROW_RE.finditer(section):
            anchor = match.group(1)
            message = match.group(2).strip()
            path = _path_from_anchor(anchor)
            if path and message:
                rows.append({"path": path, "body": message})
        if rows:
            return rows
    return []


def promote_deferred_for_incremental_paths(
    book: FindingLedger,
    *,
    deferred_findings: Sequence[dict[str, Any]],
    incremental_changed_paths: Sequence[str],
    round_index: int,
    recorded_at: str,
) -> frozenset[str]:
    """Promote deferred ledger rows whose cited path intersects the incremental diff."""
    _ = round_index
    changed = frozenset(incremental_changed_paths)
    deferred_fps = {record.fingerprint for record in book.records() if record.state == "deferred"}
    promoted: set[str] = set()
    for row in deferred_findings:
        path = str(row.get("path") or "").strip()
        if not path or path not in changed:
            continue
        fingerprint = str(row.get("fingerprint") or "").strip()
        if not fingerprint:
            body = str(row.get("body") or row.get("message") or "")
            fingerprint = finding_fingerprint(path=path, body=body)
        if fingerprint not in deferred_fps:
            continue
        book.promote(
            fingerprint,
            reason=f"Incremental diff touched {path}.",
            recorded_at=recorded_at,
        )
        promoted.add(fingerprint)
    return frozenset(promoted)


__all__ = [
    "deferred_findings_from_reviews",
    "promote_deferred_for_incremental_paths",
]
