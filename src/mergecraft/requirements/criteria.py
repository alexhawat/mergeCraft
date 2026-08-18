"""Acceptance-criteria extraction, evidence mapping, and scope-creep detection."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AcceptanceCriterion:
    """One atomic acceptance criterion from ticket text."""

    text: str


@dataclass(frozen=True, slots=True)
class ChangeMap:
    """Changed paths and touched symbols for a pull request."""

    changed_paths: tuple[str, ...]
    touched_symbols: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CriterionMapping:
    """Mapping from a criterion to supporting code, tests, or missing evidence."""

    criterion: AcceptanceCriterion
    evidence_kind: str
    evidence_paths: tuple[str, ...] = ()


_CHECKLIST_ITEM_RE = re.compile(
    r"^\s*[-*]\s*(?:\[[ xX]\]\s*)?(.+?)\s*$",
    re.MULTILINE,
)
_ACCEPTANCE_SECTION_RE = re.compile(
    r"(?is)##\s*acceptance\s+criteria\s*\n(.*?)(?:\n##\s|\Z)",
)


def extract_acceptance_criteria(ticket_body: str) -> list[AcceptanceCriterion]:
    """Extract atomic checklist items from ticket acceptance-criteria sections."""
    section = _ACCEPTANCE_SECTION_RE.search(ticket_body)
    scope = section.group(1) if section else ticket_body
    items: list[AcceptanceCriterion] = []
    for match in _CHECKLIST_ITEM_RE.finditer(scope):
        text = match.group(1).strip()
        if text and not text.startswith("#"):
            items.append(AcceptanceCriterion(text=text))
    return items


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in re.findall(r"[a-zA-Z][a-zA-Z0-9_]*", text)}


def _keyword_overlap(criterion: str, symbol: str) -> bool:
    crit_tokens = _tokens(criterion)
    sym_tokens = _tokens(symbol.replace("_", " "))
    if not crit_tokens or not sym_tokens:
        return False
    return len(crit_tokens & sym_tokens) >= 1


def map_criteria_to_evidence(
    criteria: list[AcceptanceCriterion],
    *,
    change_map: ChangeMap,
) -> list[CriterionMapping]:
    """Map each criterion to code, tests, or explicit missing evidence."""
    mappings: list[CriterionMapping] = []
    code_paths = [p for p in change_map.changed_paths if p.startswith("src/")]
    test_paths = [
        p
        for p in change_map.changed_paths
        if p.startswith("tests/") or "/test_" in p or p.endswith("_test.py")
    ]
    for criterion in criteria:
        matched_code = [
            path
            for path in code_paths
            if _keyword_overlap(criterion.text, path)
            or any(_keyword_overlap(criterion.text, sym) for sym in change_map.touched_symbols)
        ]
        matched_tests = [
            path
            for path in test_paths
            if _keyword_overlap(criterion.text, path)
            or any(_keyword_overlap(criterion.text, sym) for sym in change_map.touched_symbols)
        ]
        if matched_tests:
            mappings.append(
                CriterionMapping(
                    criterion=criterion,
                    evidence_kind="tests",
                    evidence_paths=tuple(matched_tests),
                )
            )
        elif matched_code or (
            code_paths
            and any(_keyword_overlap(criterion.text, sym) for sym in change_map.touched_symbols)
        ):
            paths = tuple(matched_code or code_paths)
            mappings.append(
                CriterionMapping(
                    criterion=criterion,
                    evidence_kind="code",
                    evidence_paths=paths,
                )
            )
        else:
            mappings.append(
                CriterionMapping(
                    criterion=criterion,
                    evidence_kind="missing",
                    evidence_paths=(),
                )
            )
    return mappings


def find_unimplemented_criteria(mappings: list[CriterionMapping]) -> list[AcceptanceCriterion]:
    """Return criteria with no supporting code or test evidence."""
    return [mapping.criterion for mapping in mappings if mapping.evidence_kind == "missing"]


def detect_scope_creep(
    *,
    stated_intent: str,
    change_map: ChangeMap,
) -> list[str]:
    """Detect changed paths that exceed the stated ticket intent."""
    intent_tokens = _tokens(stated_intent)
    creep: list[str] = []
    for path in change_map.changed_paths:
        path_tokens = _tokens(path.replace("/", " "))
        if path_tokens & intent_tokens:
            continue
        path_evidence = any(
            _keyword_overlap(stated_intent, sym)
            and (_keyword_overlap(path, sym) or _tokens(sym) & path_tokens)
            for sym in change_map.touched_symbols
        )
        if not path_evidence:
            creep.append(path)
    return creep


__all__ = [
    "AcceptanceCriterion",
    "ChangeMap",
    "CriterionMapping",
    "detect_scope_creep",
    "extract_acceptance_criteria",
    "find_unimplemented_criteria",
    "map_criteria_to_evidence",
]
