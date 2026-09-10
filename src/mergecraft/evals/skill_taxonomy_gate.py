"""Taxonomy drift gate for the code-review skill (RS4, D8).

Reads expected finding vocabulary from :mod:`mergecraft.review_taxonomy` and
:mod:`mergecraft.findings.severity` at check time — never diffs
``REVIEW-CHECKS.md`` prose, so rewording the human catalog cannot mask drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from mergecraft.findings.severity import BLOCKING_SEVERITIES
from mergecraft.review_taxonomy import (
    FINDING_CATEGORIES,
    FINDING_CONFIDENCES,
    FINDING_EFFORTS,
    FINDING_SEVERITIES,
    WITHDRAWN_FINDINGS_HEADING,
)

_DEFAULT_SKILL_ROOT: Final[Path] = (
    Path(__file__).resolve().parents[3] / ".github" / "skills" / "code-review"
)


def default_taxonomy() -> dict[str, tuple[str, ...]]:
    """Return the live taxonomy tuples the skill must name."""
    return {
        "FINDING_CATEGORIES": tuple(FINDING_CATEGORIES),
        "FINDING_SEVERITIES": tuple(FINDING_SEVERITIES),
        "FINDING_EFFORTS": tuple(FINDING_EFFORTS),
        "FINDING_CONFIDENCES": tuple(FINDING_CONFIDENCES),
        "BLOCKING_SEVERITIES": tuple(sorted(BLOCKING_SEVERITIES)),
        "WITHDRAWN_FINDINGS_HEADING": (WITHDRAWN_FINDINGS_HEADING,),
    }


def skill_instruction_text(skill_root: Path) -> str:
    """Concatenate ``SKILL.md`` and every ``references/*.md`` file."""
    parts = [skill_root / "SKILL.md"]
    references = skill_root / "references"
    if references.is_dir():
        parts.extend(sorted(references.glob("*.md")))
    return "\n".join(path.read_text(encoding="utf-8") for path in parts)


@dataclass(frozen=True, slots=True)
class TaxonomyCoverage:
    """Outcome of scanning the skill tree against a taxonomy snapshot."""

    missing: list[str]
    taxonomy: dict[str, tuple[str, ...]]


def taxonomy_values_covered_by_skill(
    *,
    taxonomy: dict[str, tuple[str, ...]] | None = None,
    skill_root: Path | None = None,
) -> TaxonomyCoverage:
    """Return taxonomy values absent from the rendered skill instruction bundle."""
    resolved_taxonomy = taxonomy if taxonomy is not None else default_taxonomy()
    root = skill_root or _DEFAULT_SKILL_ROOT
    text = skill_instruction_text(root)
    missing: list[str] = []
    for values in resolved_taxonomy.values():
        for value in values:
            if value not in text:
                missing.append(value)
    return TaxonomyCoverage(missing=missing, taxonomy=resolved_taxonomy)


__all__ = [
    "TaxonomyCoverage",
    "default_taxonomy",
    "skill_instruction_text",
    "taxonomy_values_covered_by_skill",
]
