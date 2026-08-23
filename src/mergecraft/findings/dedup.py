"""Finding deduplication before the judge (DG1, G1).

Collapse duplicate defects reported by multiple lenses or paraphrased wording
at the same location. Distinct categories on one line stay separate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

from mergecraft.review_policy.paths import normalize_repo_path
from mergecraft.review_policy.security_tokens import DOMAIN_HINT_GROUPS

if TYPE_CHECKING:
    from mergecraft.analyzers.finding import Finding

_TOKEN_RE = re.compile(r"[a-z0-9]{3,}", re.IGNORECASE)
_STOPWORDS = frozenset(
    {
        "all",
        "and",
        "are",
        "but",
        "can",
        "for",
        "from",
        "had",
        "has",
        "her",
        "him",
        "his",
        "how",
        "its",
        "may",
        "new",
        "not",
        "now",
        "old",
        "one",
        "our",
        "out",
        "see",
        "the",
        "too",
        "two",
        "use",
        "was",
        "way",
        "who",
        "you",
        "with",
        "this",
        "that",
        "have",
        "been",
        "will",
        "also",
        "when",
        "what",
        "some",
        "than",
        "them",
        "then",
        "into",
        "only",
        "over",
        "such",
        "just",
        "like",
        "very",
        "much",
        "many",
        "most",
        "other",
        "after",
    }
)
_HIGH_RATIO_THRESHOLD = 0.65
_MEDIUM_RATIO_THRESHOLD = 0.41
_MIN_SHARED_CONTENT_TOKENS = 3
_MIN_DOMAIN_TOKENS_PER_SIDE = 2
_SINGLE_DOMAIN_OVERLAP_RATIO = 0.28
_DIGIT_RE = re.compile(r"\d+")
_GENERIC_TOKENS = frozenset(
    {
        "also",
        "case",
        "change",
        "config",
        "default",
        "defect",
        "edge",
        "function",
        "input",
        "introduced",
        "lacks",
        "line",
        "missing",
        "number",
        "returns",
        "used",
        "validation",
        "value",
    }
)


@dataclass(frozen=True, slots=True)
class DedupeResult:
    """Findings after dedupe plus indices into the input list."""

    findings: list[Finding]
    kept_indices: list[int]


def _message_tokens(message: str) -> set[str]:
    return {match.group(0).casefold() for match in _TOKEN_RE.finditer(message)}


def _content_tokens(message: str) -> set[str]:
    return _message_tokens(message) - _STOPWORDS


def _digit_tokens(message: str) -> set[str]:
    return {match.group(0) for match in _DIGIT_RE.finditer(message)}


def _digits_compatible(left: str, right: str) -> bool:
    left_digits = _digit_tokens(left)
    right_digits = _digit_tokens(right)
    if not left_digits or not right_digits:
        return True
    return bool(left_digits & right_digits)


def _distinctive_shared_tokens(shared: set[str]) -> set[str]:
    return shared - _GENERIC_TOKENS


def _domain_overlap(left: str, right: str) -> tuple[int, bool]:
    """Return shared domain-token count and whether each side has enough domain tokens."""
    left_tokens = _message_tokens(left)
    right_tokens = _message_tokens(right)
    best_shared = 0
    best_each_side_two = False
    for group in DOMAIN_HINT_GROUPS:
        left_domain = left_tokens & group
        right_domain = right_tokens & group
        if not left_domain or not right_domain:
            continue
        shared = len(left_domain & right_domain)
        each_side_two = (
            len(left_domain) >= _MIN_DOMAIN_TOKENS_PER_SIDE
            and len(right_domain) >= _MIN_DOMAIN_TOKENS_PER_SIDE
        )
        if shared > best_shared or (
            shared == best_shared and each_side_two and not best_each_side_two
        ):
            best_shared = shared
            best_each_side_two = each_side_two
    return best_shared, best_each_side_two


def _messages_semantically_similar(first: str, second: str) -> bool:
    left = first.casefold().strip()
    right = second.casefold().strip()
    if not left or not right:
        return left == right
    if not _digits_compatible(left, right):
        return False
    ratio = SequenceMatcher(None, left, right).ratio()
    shared = _content_tokens(left) & _content_tokens(right)
    shared_domain, each_side_two = _domain_overlap(left, right)
    distinctive = _distinctive_shared_tokens(shared)
    digits_overlap = bool(_digit_tokens(left) & _digit_tokens(right))
    if ratio >= _HIGH_RATIO_THRESHOLD and (
        bool(distinctive) or digits_overlap or shared_domain >= 1
    ):
        return True
    if (
        len(shared) >= _MIN_SHARED_CONTENT_TOKENS
        and ratio >= _MEDIUM_RATIO_THRESHOLD
        and (shared_domain >= 2 or digits_overlap)
    ):
        return True
    return shared_domain == 1 and each_side_two and ratio >= _SINGLE_DOMAIN_OVERLAP_RATIO


def location_key(finding: Finding) -> tuple[str, int | None, int | None, str]:
    """Return the dedup bucket key for a finding (path, line span, message)."""
    return _location_key(finding)


def _location_key(finding: Finding) -> tuple[str, int | None, int | None, str]:
    return (
        normalize_repo_path(finding.path),
        finding.start_line,
        finding.end_line,
        finding.category,
    )


def dedupe_findings_with_indices(findings: list[Finding]) -> DedupeResult:
    """Return deduped findings and the input indices that survived."""
    if not findings:
        return DedupeResult(findings=[], kept_indices=[])

    indexed: list[tuple[int, Finding]] = list(enumerate(findings))
    buckets: dict[tuple[str, int | None, int | None, str], list[tuple[int, Finding]]] = {}
    for index, finding in indexed:
        buckets.setdefault(_location_key(finding), []).append((index, finding))

    deduped: list[Finding] = []
    kept_indices: list[int] = []
    for bucket in buckets.values():
        clusters: list[list[tuple[int, Finding]]] = []
        for index, finding in bucket:
            placed = False
            for cluster in clusters:
                if _messages_semantically_similar(cluster[0][1].message, finding.message):
                    cluster.append((index, finding))
                    placed = True
                    break
            if not placed:
                clusters.append([(index, finding)])
        for cluster in clusters:
            survivor_index, survivor = cluster[0]
            deduped.append(survivor)
            kept_indices.append(survivor_index)
    return DedupeResult(findings=deduped, kept_indices=kept_indices)


def dedupe_findings(findings: list[Finding]) -> list[Finding]:
    """Return findings with duplicate defects collapsed to one row each."""
    return dedupe_findings_with_indices(findings).findings


__all__ = ["DedupeResult", "dedupe_findings", "dedupe_findings_with_indices", "location_key"]
