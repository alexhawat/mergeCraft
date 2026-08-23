"""Incremental deferred-finding promotion (RC9, W3 ledger).

Promotes ledger ``deferred`` records when the incremental diff touches their cited
path, reusing the checkout incremental changed-path set.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.review_taxonomy import finding_fingerprint

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mergecraft.findings.ledger import FindingLedger
    from mergecraft.findings.lifecycle import LifecycleRecord


def deferred_rows_from_ledger(book: FindingLedger) -> list[dict[str, object]]:
    """Return deferred ledger rows as publish-shaped dicts for promotion."""
    rows: list[dict[str, object]] = []
    for record in book.records():
        if record.state != "deferred":
            continue
        rows.append(
            {
                "fingerprint": record.fingerprint,
                "path": _path_from_record(record),
            }
        )
    return rows


def _path_from_record(record: LifecycleRecord) -> str:
    if record.reason and record.reason.startswith("path:"):
        return record.reason.removeprefix("path:")
    return ""


def promote_deferred_for_incremental_paths(
    book: FindingLedger,
    *,
    deferred_findings: Sequence[dict[str, Any]],
    incremental_changed_paths: Sequence[str],
    round_index: int,
    recorded_at: str,
) -> frozenset[str]:
    """Promote deferred ledger rows whose cited path intersects the incremental diff."""
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
            round_index=round_index,
        )
        promoted.add(fingerprint)
    return frozenset(promoted)


__all__ = [
    "deferred_rows_from_ledger",
    "promote_deferred_for_incremental_paths",
]
