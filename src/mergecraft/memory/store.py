"""Repository memory validation and dismissal-signal eligibility.

Live validation consumes the learnings document. Dismissal ingestion exposes
only an evidence/approval eligibility result; it does not write learnings.
Negative-memory filtering, TTLs and contradictions live in utils.memory.

Exports:
    IngestResult — Whether a dismissal satisfies the evidence/approval requirement.
    MemoryValidationReport — Structure, staleness and conflict status.
    MemoryStoreError — Missing or invalid learnings document.
    validate_memory_store — Validate a repository's learnings file.
    ingest_dismissal_signal — Evaluate repeated evidence or explicit approval.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from mergecraft.utils.learnings import ACTIVE_SECTION_HEADING, STAGING_SECTION_HEADING
from mergecraft.utils.memory import (
    MemoryEntry,
    apply_recency_weighting,
    detect_contradicting_memories,
    parse_memory_entries_from_learnings,
)

MIN_HISTORICAL_EVIDENCE: Final[int] = 2
_SECTION_HEADING_PREFIX: Final[str] = "## "


@dataclass(frozen=True, slots=True)
class IngestResult:
    """Eligibility result for a dismissal signal; does not itself persist memory."""

    durable: bool


@dataclass(frozen=True, slots=True)
class MemoryValidationReport:
    """Structure, stale-entry, and contradiction status for a repo store."""

    valid: bool
    stale_ids: tuple[str, ...]
    conflict_ids: tuple[str, ...]


class MemoryStoreError(ValueError):
    """The on-disk memory document is missing or not a valid learnings file."""


def _has_memory_document_layout(text: str) -> bool:
    headings = {
        line.strip().lower()
        for line in text.splitlines()
        if line.startswith(_SECTION_HEADING_PREFIX)
    }
    active = f"{_SECTION_HEADING_PREFIX}{ACTIVE_SECTION_HEADING}".lower()
    staging = f"{_SECTION_HEADING_PREFIX}{STAGING_SECTION_HEADING}".lower()
    return active in headings or staging in headings


def validate_memory_store(repo: object) -> MemoryValidationReport:
    """Validate ``repo``'s ``.mergecraft/learnings.md`` store.

    Args:
        repo: Repository root (``Path``-like).

    Returns:
        Report of validity plus stale and conflicting entry ids.

    Raises:
        MemoryStoreError: Missing file or not a sectioned memory document.
    """
    root = Path(str(repo))
    path = root / ".mergecraft" / "learnings.md"
    if not path.is_file():
        msg = f"corrupt memory store: missing {path}"
        raise MemoryStoreError(msg)
    text = path.read_text(encoding="utf-8")
    if not _has_memory_document_layout(text):
        msg = "corrupt memory store: not a valid memory document"
        raise MemoryStoreError(msg)
    now = datetime.now(UTC)
    entries: list[MemoryEntry] = []
    for raw in parse_memory_entries_from_learnings(text):
        entries.append(
            MemoryEntry(
                id=raw["id"],
                text=raw["text"],
                recorded_at=now,
                ttl_days=365,
            )
        )
    weighted = apply_recency_weighting(entries, now=now)
    stale = tuple(entry.id for entry, weight in weighted if weight == 0.0)
    conflicts = detect_contradicting_memories(entries, now=now)
    conflict_ids = tuple(
        sorted({item.left_id for item in conflicts} | {item.right_id for item in conflicts})
    )
    return MemoryValidationReport(valid=True, stale_ids=stale, conflict_ids=conflict_ids)


def ingest_dismissal_signal(
    *,
    reason_code: str,
    fingerprint: str,
    evidence_count: int,
    approved: bool = False,
) -> IngestResult:
    """Evaluate a dismissal code against repeated evidence or explicit approval."""
    del fingerprint
    if not reason_code.strip():
        msg = "dismissal reason_code is required"
        raise ValueError(msg)
    durable = approved or evidence_count >= MIN_HISTORICAL_EVIDENCE
    return IngestResult(durable=durable)


__all__ = [
    "MIN_HISTORICAL_EVIDENCE",
    "IngestResult",
    "MemoryStoreError",
    "MemoryValidationReport",
    "ingest_dismissal_signal",
    "validate_memory_store",
]
