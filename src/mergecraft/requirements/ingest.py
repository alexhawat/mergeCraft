"""Ticket and spec ingest with nonce fencing and requirement states (#352).

External requirement text is treated as untrusted data. Extraction runs on the
raw body; the nonce fence is retained so review prompts can cite the same
envelope the rest of mergeCraft uses. Suggestions are never written back to
the reviewed tree (D13).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Literal

from mergecraft.requirements.criteria import (
    AcceptanceCriterion,
    ChangeMap,
    CriterionMapping,
    extract_acceptance_criteria,
    map_criteria_to_evidence,
)
from mergecraft.utils.fence import Fence, render_untrusted

if TYPE_CHECKING:
    from pathlib import Path

RequirementSource = Literal[
    "pr_description",
    "linked_issue",
    "local_spec",
    "github_issue",
    "gitlab_issue",
    "jira",
    "linear",
    "adr",
    "acceptance_criteria",
]

REQUIREMENT_SOURCES: frozenset[str] = frozenset(
    {
        "pr_description",
        "linked_issue",
        "local_spec",
        "github_issue",
        "gitlab_issue",
        "jira",
        "linear",
        "adr",
        "acceptance_criteria",
    }
)

_LOCAL_SPEC_CANDIDATES: tuple[str, ...] = (
    "SPEC.md",
    "spec.md",
    "ACCEPTANCE.md",
    "docs/SPEC.md",
    "docs/acceptance.md",
)

_NEGATIVE_HINTS: frozenset[str] = frozenset(
    {"must not", "must never", "should not", "do not", "don't", "never "}
)


class RequirementState(StrEnum):
    """Named outcomes for one atomic requirement against the change under review."""

    SATISFIED = "satisfied"
    PARTIALLY_SATISFIED = "partially_satisfied"
    CONTRADICTED = "contradicted"
    NOT_EVIDENCED = "not_evidenced"
    OUT_OF_SCOPE = "out_of_scope"


REQUIREMENT_STATES: frozenset[str] = frozenset(state.value for state in RequirementState)


@dataclass(frozen=True, slots=True)
class Requirement:
    """One atomic requirement with a stable id, source citation, and state."""

    requirement_id: str
    text: str
    source: str
    source_ref: str
    state: RequirementState
    kind: str
    evidence_paths: tuple[str, ...]
    fenced_source: str


@dataclass(frozen=True, slots=True)
class IngestResult:
    """Ingested requirements plus the nonce-fenced external text."""

    source: str
    source_ref: str
    fenced_text: str
    requirements: tuple[Requirement, ...]


def _read_local_spec(repo_root: Path) -> tuple[str, str]:
    for relative in _LOCAL_SPEC_CANDIDATES:
        path = repo_root / relative
        if path.is_file():
            return path.read_text(encoding="utf-8"), relative
    adr_dir = repo_root / "docs" / "adr"
    if adr_dir.is_dir():
        for path in sorted(adr_dir.glob("*.md")):
            if path.is_file():
                return path.read_text(encoding="utf-8"), str(path.relative_to(repo_root))
    return "", ""


def _resolve_body(
    *,
    source: str,
    text: str,
    pr_description: str,
    linked_issue: str,
    local_spec: str,
    repo_root: Path | None,
) -> tuple[str, str]:
    if text:
        return text, source
    if source == "pr_description" and pr_description:
        return pr_description, "pr_description"
    if source == "linked_issue" and linked_issue:
        return linked_issue, "linked_issue"
    if source == "local_spec" and local_spec:
        return local_spec, "local_spec"
    if source in {"local_spec", "adr", "acceptance_criteria"} and repo_root is not None:
        body, ref = _read_local_spec(repo_root)
        return body, ref or source
    if pr_description:
        return pr_description, "pr_description"
    if linked_issue:
        return linked_issue, "linked_issue"
    if local_spec:
        return local_spec, "local_spec"
    if repo_root is not None:
        body, ref = _read_local_spec(repo_root)
        return body, ref or source
    return "", source


def _is_negative_requirement(text: str) -> bool:
    lowered = text.casefold()
    return any(hint in lowered for hint in _NEGATIVE_HINTS)


def _state_for(mapping: CriterionMapping, *, change_map: ChangeMap) -> RequirementState:
    if mapping.evidence_kind == "tests":
        return RequirementState.SATISFIED
    if mapping.evidence_kind == "code":
        if _is_negative_requirement(mapping.criterion.text):
            return RequirementState.CONTRADICTED
        return RequirementState.PARTIALLY_SATISFIED
    if change_map.changed_paths and not mapping.evidence_paths:
        tokens = {token.lower() for token in mapping.criterion.text.split() if len(token) > 3}
        path_blob = " ".join(change_map.changed_paths).casefold()
        if tokens and not any(token.casefold() in path_blob for token in tokens):
            return RequirementState.OUT_OF_SCOPE
    return RequirementState.NOT_EVIDENCED


def _stable_id(index: int) -> str:
    return f"REQ-{index:03d}"


def _kind_for(text: str) -> str:
    lowered = text.casefold()
    if "compat" in lowered or "backward" in lowered:
        return "compatibility"
    if "must not" in lowered or "non-goal" in lowered or "out of scope" in lowered:
        return "constraint"
    return "acceptance"


def ingest_requirements(
    *,
    source: str,
    text: str = "",
    pr_description: str = "",
    linked_issue: str = "",
    local_spec: str = "",
    repo_root: Path | None = None,
    change_map: ChangeMap | None = None,
) -> IngestResult:
    """Ingest untrusted requirement text and return atomic, cited requirements.

    Args:
        source: Named ingest source (``pr_description``, ``linked_issue``,
            ``local_spec``, plus ticket-system aliases).
        text: Pre-resolved body. When set, it wins over source-specific fields.
        pr_description: Pull-request description body.
        linked_issue: Linked issue / ticket body.
        local_spec: Local specification file contents.
        repo_root: Checkout used to discover ``SPEC.md`` and ADR files.
        change_map: Optional changed paths/symbols used to assign states.

    Returns:
        IngestResult: Fenced source text and zero or more requirements.
    """
    if source not in REQUIREMENT_SOURCES:
        msg = f"unknown requirement source {source!r}"
        raise ValueError(msg)
    body, source_ref = _resolve_body(
        source=source,
        text=text,
        pr_description=pr_description,
        linked_issue=linked_issue,
        local_spec=local_spec,
        repo_root=repo_root,
    )
    fence = Fence()
    fenced = render_untrusted(
        body,
        author="requirements-ingest",
        tier="untrusted",
        label=source,
        nonce=fence.nonce,
    )
    criteria = extract_acceptance_criteria(body) if body else []
    resolved_map = change_map or ChangeMap(changed_paths=(), touched_symbols=())
    mappings = map_criteria_to_evidence(criteria, change_map=resolved_map)
    requirements: list[Requirement] = []
    for index, mapping in enumerate(mappings, start=1):
        criterion: AcceptanceCriterion = mapping.criterion
        requirements.append(
            Requirement(
                requirement_id=_stable_id(index),
                text=criterion.text,
                source=source,
                source_ref=source_ref,
                state=_state_for(mapping, change_map=resolved_map),
                kind=_kind_for(criterion.text),
                evidence_paths=mapping.evidence_paths,
                fenced_source=fenced,
            )
        )
    return IngestResult(
        source=source,
        source_ref=source_ref,
        fenced_text=fenced,
        requirements=tuple(requirements),
    )


__all__ = [
    "REQUIREMENT_SOURCES",
    "REQUIREMENT_STATES",
    "IngestResult",
    "Requirement",
    "RequirementSource",
    "RequirementState",
    "ingest_requirements",
]
