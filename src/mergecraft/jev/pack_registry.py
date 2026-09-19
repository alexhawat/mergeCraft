"""Versioned Jev pack registry — questions, thresholds, and state fields in one place.

Maintainers review and edit pack metadata here. Question text lives in the
factories below; numeric floors and corpus row ids are co-located with each pack
so thresholds do not drift from the pack version (checklist item 11).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from mergecraft.jev.types import (
    ALIGN_PACK_ID,
    ALIGN_THRESHOLD_CORPUS_IDS,
    CERTAIN_CONFIDENCE_FLOOR,
    CLAIM_PACK_ID,
    EVIDENCE_PACK_ID,
    LENS_PACK_ID,
    LENS_THRESHOLD_CORPUS_IDS,
    LIKELY_CONFIDENCE_FLOOR,
    NOUL_ACT_FLOOR,
    UNIT_PACK_ID,
    UNIT_THRESHOLD_CORPUS_IDS,
)

# Default confidence / noul floors keyed as ``{pack_id}.{threshold_name}``.
DEFAULT_THRESHOLDS: Final[dict[str, float]] = {
    "unit/v1.certain": CERTAIN_CONFIDENCE_FLOOR,
    "unit/v1.likely": LIKELY_CONFIDENCE_FLOOR,
    "lens/v1.likely": LIKELY_CONFIDENCE_FLOOR,
    "align/v1.same_defect": LIKELY_CONFIDENCE_FLOOR,
    "align/v1.is_withdrawn_reraise": NOUL_ACT_FLOOR,
    "evidence/v1.relation": NOUL_ACT_FLOOR,
}


@dataclass(frozen=True, slots=True)
class PackRegistryEntry:
    """One versioned pack: allowed state fields, floors, and eval corpus ids."""

    pack_id: str
    state_fields: frozenset[str]
    threshold_keys: frozenset[str]
    corpus_ids: tuple[str, ...]


PACK_REGISTRY: Final[dict[str, PackRegistryEntry]] = {
    UNIT_PACK_ID: PackRegistryEntry(
        pack_id=UNIT_PACK_ID,
        state_fields=frozenset({"path", "hunk", "unit_id"}),
        threshold_keys=frozenset({"unit/v1.certain", "unit/v1.likely"}),
        corpus_ids=UNIT_THRESHOLD_CORPUS_IDS,
    ),
    EVIDENCE_PACK_ID: PackRegistryEntry(
        pack_id=EVIDENCE_PACK_ID,
        state_fields=frozenset({"claim", "section", "path", "start_line", "end_line"}),
        threshold_keys=frozenset({"evidence/v1.relation"}),
        corpus_ids=(),
    ),
    CLAIM_PACK_ID: PackRegistryEntry(
        pack_id=CLAIM_PACK_ID,
        state_fields=frozenset({"claim", "findings_table", "terminal_verdict"}),
        threshold_keys=frozenset(),
        corpus_ids=(),
    ),
    ALIGN_PACK_ID: PackRegistryEntry(
        pack_id=ALIGN_PACK_ID,
        state_fields=frozenset(
            {"finding", "path", "withdrawn", "left", "right", "left_path", "right_path"}
        ),
        threshold_keys=frozenset(
            {"align/v1.same_defect", "align/v1.is_withdrawn_reraise"},
        ),
        corpus_ids=ALIGN_THRESHOLD_CORPUS_IDS,
    ),
    LENS_PACK_ID: PackRegistryEntry(
        pack_id=LENS_PACK_ID,
        state_fields=frozenset({"diff", "paths"}),
        threshold_keys=frozenset({"lens/v1.likely"}),
        corpus_ids=LENS_THRESHOLD_CORPUS_IDS,
    ),
}


def registry_entry(pack_id: str) -> PackRegistryEntry | None:
    """Return registry metadata for ``pack_id``, or ``None`` when unknown."""
    return PACK_REGISTRY.get(pack_id)


def state_fields_for(pack_id: str) -> frozenset[str]:
    """Allowed ``system_one`` state keys for ``pack_id``."""
    entry = registry_entry(pack_id)
    if entry is None:
        return frozenset()
    return entry.state_fields


__all__ = [
    "DEFAULT_THRESHOLDS",
    "PACK_REGISTRY",
    "PackRegistryEntry",
    "registry_entry",
    "state_fields_for",
]
