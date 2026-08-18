"""Finding deduplication before the judge (DG1, G1).

Collapse duplicate defects reported by multiple lenses or paraphrased wording
at the same location. Distinct categories on one line stay separate.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mergecraft.analyzers.finding import Finding

_TOKEN_RE = re.compile(r"[a-z0-9]{3,}", re.IGNORECASE)
_DOMAIN_HINTS: tuple[tuple[str, ...], ...] = (
    ("sql", "query", "injection", "unsanitized", "binding"),
    ("timeout", "retry", "loop"),
    ("secret", "token", "credential", "password"),
)


def _normalize_path(path: str) -> str:
    text = path.strip().replace("\\", "/")
    for prefix in ("./", "a/", "b/"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    return text


def _message_tokens(message: str) -> set[str]:
    return {match.group(0).casefold() for match in _TOKEN_RE.finditer(message)}


def _messages_semantically_similar(first: str, second: str) -> bool:
    left = first.casefold().strip()
    right = second.casefold().strip()
    if not left or not right:
        return left == right
    if SequenceMatcher(None, left, right).ratio() >= 0.4:
        return True
    shared = _message_tokens(left) & _message_tokens(right)
    if len(shared) >= 2:
        return True
    for group in _DOMAIN_HINTS:
        if (
            any(token in left for token in group)
            and any(token in right for token in group)
            and len(_message_tokens(left) & set(group)) >= 1
            and len(_message_tokens(right) & set(group)) >= 1
        ):
            return True
    return False


def _location_key(finding: Finding) -> tuple[str, int, int, str]:
    return (
        _normalize_path(finding.path),
        finding.start_line,
        finding.end_line,
        finding.category,
    )


def dedupe_findings(findings: list[Finding]) -> list[Finding]:
    """Return findings with duplicate defects collapsed to one row each."""
    if not findings:
        return []

    buckets: dict[tuple[str, int, int, str], list[Finding]] = {}
    for finding in findings:
        buckets.setdefault(_location_key(finding), []).append(finding)

    deduped: list[Finding] = []
    for bucket in buckets.values():
        clusters: list[list[Finding]] = []
        for finding in bucket:
            placed = False
            for cluster in clusters:
                if _messages_semantically_similar(cluster[0].message, finding.message):
                    cluster.append(finding)
                    placed = True
                    break
            if not placed:
                clusters.append([finding])
        for cluster in clusters:
            deduped.append(cluster[0])
    return deduped


__all__ = ["dedupe_findings"]
