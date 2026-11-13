"""Repository memory validation and dismissal-signal eligibility.

Durable negative-memory storage and filtering live in mergecraft.utils.memory.
"""

from __future__ import annotations

from mergecraft.memory.store import (
    MIN_HISTORICAL_EVIDENCE,
    IngestResult,
    MemoryStoreError,
    MemoryValidationReport,
    ingest_dismissal_signal,
    validate_memory_store,
)

__all__ = [
    "MIN_HISTORICAL_EVIDENCE",
    "IngestResult",
    "MemoryStoreError",
    "MemoryValidationReport",
    "ingest_dismissal_signal",
    "validate_memory_store",
]
