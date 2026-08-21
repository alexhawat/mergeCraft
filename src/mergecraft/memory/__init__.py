"""Repo and organization review memory — validation, kinds, effectiveness (#360).

Exports:
    MEMORY_KINDS: Factual / policy / preference / FP-suppression kinds.
    FalsePositiveMemory: Scoped FP suppression with TTL.
    OrganizationMemoryBackend: Pluggable org memory API.
    activate_learned_behaviour: Historical validation before activation.
    ingest_reviewer_signal: Repeated evidence or explicit approval.
    ingest_dismissal_signal: Consume #355 dismissal codes (does not define them).
    detect_over_suppression: Guard against over-suppression.
    evaluate_memory_effectiveness: Precision up, recall not down.
    validate_memory_store: Fail closed on a corrupt store.
"""

from __future__ import annotations

from mergecraft.memory.store import (
    MEMORY_KINDS,
    MIN_HISTORICAL_EVIDENCE,
    FalsePositiveMemory,
    IngestResult,
    LocalMemoryBackend,
    MemoryBackend,
    MemoryEffectivenessReport,
    MemoryStoreError,
    MemoryValidationReport,
    OrganizationMemoryBackend,
    OverSuppressionReport,
    activate_learned_behaviour,
    detect_over_suppression,
    evaluate_memory_effectiveness,
    ingest_dismissal_signal,
    ingest_reviewer_signal,
    validate_memory_store,
)

__all__ = [
    "MEMORY_KINDS",
    "MIN_HISTORICAL_EVIDENCE",
    "FalsePositiveMemory",
    "IngestResult",
    "LocalMemoryBackend",
    "MemoryBackend",
    "MemoryEffectivenessReport",
    "MemoryStoreError",
    "MemoryValidationReport",
    "OrganizationMemoryBackend",
    "OverSuppressionReport",
    "activate_learned_behaviour",
    "detect_over_suppression",
    "evaluate_memory_effectiveness",
    "ingest_dismissal_signal",
    "ingest_reviewer_signal",
    "validate_memory_store",
]
