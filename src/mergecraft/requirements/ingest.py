"""Ticket and spec ingest with nonce fencing and requirement states (#352).

External requirement text is treated as untrusted data. Extraction runs on the
raw body; the nonce fence is retained so review prompts can cite the same
envelope the rest of mergeCraft uses. Suggestions are never written back to
the reviewed tree (D13).

A body may also declare the paths the change is expected to touch with a
``Scope paths:`` block (#1056 part 3); :func:`parse_scope_paths` reads it into a
:class:`ScopeDeclaration`. The globs are data: they are bounded, fail closed,
are matched against the diff's path list only and never open a file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

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
class ScopeDeclaration:
    """The ``Scope paths:`` block of one untrusted body (#1056 part 3).

    Attributes:
        declared (bool): ``True`` when the body has a ``Scope paths:`` block, even
            an empty or rejected one; ``False`` when it has none.
        globs (tuple[str, ...]): The accepted globs, in order; ``()`` when the block
            listed none or any item broke a bound.
        source_ref (str): Where the body came from (``"pr_description"``,
            ``"linked_issue#<n>"``); ``""`` when unknown.
        rejected (tuple[str, ...]): The items that broke a bound (all of them when
            the count bound broke); non-empty means the declaration is invalid.
    """

    declared: bool
    globs: tuple[str, ...]
    source_ref: str
    rejected: tuple[str, ...]


SCOPE_MAX_GLOBS = 64
"""Most globs one ``Scope paths:`` block may list; one more rejects all of them."""

SCOPE_MAX_GLOB_CHARS = 200
"""Longest accepted glob, in characters."""

_SCOPE_HEADER_RE = re.compile(
    r"^[ ]{0,3}(?:#{2,3}[ \t]+)?(?:\*\*|__)?[ \t]*scope[ \t]+paths[ \t]*"
    r"(?:(?:\*\*|__)[ \t]*:|:[ \t]*(?:\*\*|__)?)[ \t]*$",
    re.IGNORECASE,
)
_HEADING_RE = re.compile(r"^[ ]{0,3}#{1,6}(?:[ \t]|$)")
_LIST_ITEM_RE = re.compile(r"^[ \t]*[-*][ \t]+(.*)$")
_FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})[^`]*$")
_WILDCARD_ONLY_CHARS = frozenset("*?./")


def _closes_fence(line: str, marker: str) -> bool:
    """Whether ``line`` closes a fence opened with ``marker`` (same character, as long)."""
    stripped = line.strip()
    return stripped.startswith(marker[0] * len(marker)) and not stripped.strip(marker[0])


def _visible_header(lines: list[str]) -> int | None:
    """The first ``Scope paths:`` header outside an HTML comment and a code fence.

    A block inside ``<!-- … -->`` (an opener on the header line included) or a
    backtick / tilde fence is not rendered, so it is not a declaration.
    """
    in_comment = False
    fence: str | None = None
    for index, line in enumerate(lines):
        if fence is not None:
            if _closes_fence(line, fence):
                fence = None
            continue
        visible = line
        if in_comment:
            close = visible.find("-->")
            if close == -1:
                continue
            in_comment = False
            visible = visible[close + 3 :]
        while (opener := visible.find("<!--")) != -1:
            close = visible.find("-->", opener + 4)
            if close == -1:
                in_comment = True
                visible = visible[:opener]
                break
            visible = visible[:opener] + visible[close + 3 :]
        if in_comment:
            # A header before an unclosed opener would have its items hidden by
            # the comment: no declaration starts on this line.
            continue
        opened = _FENCE_RE.match(visible)
        if opened is not None:
            fence = opened.group(1)
            continue
        if _SCOPE_HEADER_RE.match(visible):
            return index
    return None


def _scope_block(lines: list[str]) -> tuple[int, int, list[str]] | None:
    """Locate the first visible ``Scope paths:`` block: ``(start, end, raw items)`` or ``None``.

    ``start`` is the header line and ``end`` is one past the block's last line.
    Items are list entries (``-`` / ``*``) or the lines of one fenced block; the
    block stops at a blank line after the first item, the next heading, the
    closing fence (or, for an unclosed fence, the next heading), or any other
    line. A header inside an HTML comment or a code fence is skipped.
    """
    start = _visible_header(lines)
    if start is None:
        return None
    index = start + 1
    while index < len(lines) and not lines[index].strip():
        index += 1
    items: list[str] = []
    if index >= len(lines) or _HEADING_RE.match(lines[index]):
        return start, index, items
    fence = _FENCE_RE.match(lines[index])
    if fence is not None:
        marker = fence.group(1)
        index += 1
        while index < len(lines):
            line = lines[index]
            if _HEADING_RE.match(line):
                break
            index += 1
            if _closes_fence(line, marker):
                break
            if line.strip():
                items.append(line)
        return start, index, items
    while index < len(lines):
        item = _LIST_ITEM_RE.match(lines[index])
        if item is None or _HEADING_RE.match(lines[index]):
            break
        items.append(item.group(1))
        index += 1
    return start, index, items


def _clean_scope_item(raw: str) -> str:
    """Trim spaces and tabs and unwrap one pair of backticks (validated afterwards)."""
    value = raw.strip(" \t")
    if len(value) >= 2 and value.startswith("`") and value.endswith("`"):
        value = value[1:-1].strip(" ")
    return value


def scope_glob_problem(glob: str) -> str | None:
    """Why ``glob`` cannot be a declared scope glob, or ``None`` when it is acceptable.

    Args:
        glob (str): One cleaned item from a ``Scope paths:`` block.

    Returns:
        str | None: A short reason (``"too long"``, ``"control character"``,
        ``"absolute"``, ``"parent segment"``, ``"matches everything"``), or ``None``.
    """
    if len(glob) > SCOPE_MAX_GLOB_CHARS:
        return "too long"
    if not all(char.isprintable() for char in glob):
        return "control character"
    if glob.startswith(("/", "\\")):
        return "absolute"
    if ".." in glob.replace("\\", "/").split("/"):
        return "parent segment"
    if set(glob) <= _WILDCARD_ONLY_CHARS:
        return "matches everything"
    return None


def parse_scope_paths(body: str, *, source_ref: str = "") -> ScopeDeclaration:
    """Parse the ``Scope paths:`` block of an untrusted body; never reads a file.

    The block starts at a line ``Scope paths:`` (any case; bare, bold, or a
    ``##`` / ``###`` heading) and lists globs as ``-`` / ``*`` items or the lines
    of one fenced block. Every bound fails the whole declaration closed: more
    than :data:`SCOPE_MAX_GLOBS` items, an item over :data:`SCOPE_MAX_GLOB_CHARS`
    characters, a non-printable character, a leading ``/``, a ``..`` segment, or
    a glob made only of wildcards (``*``, ``**``, ``**/*``, ``**/*.*``) gives
    ``declared=True, globs=()`` with the offenders in ``rejected``.

    Args:
        body (str): The untrusted text (a pull request or issue body).
        source_ref (str): Recorded on the declaration as-is.

    Returns:
        ScopeDeclaration: ``declared=False`` when the body has no block.

    Examples:
        >>> parse_scope_paths("Scope paths:\\n- docs/**\\n").globs
        ('docs/**',)
    """
    lines = body.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    block = _scope_block(lines)
    if block is None:
        return ScopeDeclaration(declared=False, globs=(), source_ref=source_ref, rejected=())
    items = [item for item in (_clean_scope_item(raw) for raw in block[2]) if item]
    if len(items) > SCOPE_MAX_GLOBS:
        return ScopeDeclaration(
            declared=True, globs=(), source_ref=source_ref, rejected=tuple(items)
        )
    rejected = tuple(item for item in items if scope_glob_problem(item) is not None)
    if rejected:
        return ScopeDeclaration(declared=True, globs=(), source_ref=source_ref, rejected=rejected)
    return ScopeDeclaration(declared=True, globs=tuple(items), source_ref=source_ref, rejected=())


def _without_scope_block(body: str) -> str:
    """``body`` with its ``Scope paths:`` block removed (scope globs are not criteria)."""
    lines = body.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    block = _scope_block(lines)
    if block is None:
        return body
    start, end, _items = block
    return "\n".join(lines[:start] + lines[end:])


@dataclass(frozen=True, slots=True)
class IngestResult:
    """Ingested requirements plus the nonce-fenced external text.

    ``scope`` is the body's ``Scope paths:`` declaration (``declared=False`` when
    it has none); its globs are never acceptance criteria.
    """

    source: str
    source_ref: str
    fenced_text: str
    requirements: tuple[Requirement, ...]
    scope: ScopeDeclaration


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
    scope = parse_scope_paths(body, source_ref=source_ref)
    criteria = extract_acceptance_criteria(_without_scope_block(body)) if body else []
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
        scope=scope,
    )


__all__ = [
    "REQUIREMENT_SOURCES",
    "REQUIREMENT_STATES",
    "SCOPE_MAX_GLOBS",
    "SCOPE_MAX_GLOB_CHARS",
    "IngestResult",
    "Requirement",
    "RequirementState",
    "ScopeDeclaration",
    "ingest_requirements",
    "parse_scope_paths",
    "scope_glob_problem",
]
