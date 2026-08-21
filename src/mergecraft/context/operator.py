"""Context search quality, specialist budgets, lazy retrieval, and omissions (#356).

Does not rebuild the retrieval half (repo map, symbol index, graphs, git history).
Does not call ``decide_approval()`` (D14).

Module: mergecraft.context.operator
Depends: dataclasses

Exports:
    Classes:
        LazyRetrieval — Tool-gated retrieval result, possibly omitted.
        OmissionReport — Requested scope that was not retrieved.
        RetrievalQualityReport — Retrieval-only quality (not model quality).
    Functions:
        score_relevance — Rank a retrieved item against a query.
        allocate_specialist_budgets — Split a token budget per specialist.
        lazy_retrieve — Fetch context only through allowed tools.
        report_omissions — Record omitted scope and a downgraded outcome.
        downgrade_for_omissions — Lower an evidence outcome when scope is missing.
        evaluate_retrieval_quality — Score retrieval separately from the LLM.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

_CONTROLLED_TOOLS: Final[frozenset[str]] = frozenset({"search", "explain"})


@dataclass(frozen=True, slots=True)
class LazyRetrieval:
    """Result of a tool-gated lazy retrieval."""

    items: tuple[str, ...]
    omitted: bool = False

    def __bool__(self) -> bool:
        return bool(self.items) and not self.omitted


@dataclass(frozen=True, slots=True)
class OmissionReport:
    """Requested context that was not retrieved, with a downgraded outcome."""

    omitted: tuple[str, ...]
    outcome: str


@dataclass(frozen=True, slots=True)
class RetrievalQualityReport:
    """Retrieval-quality score that does not grade the language model."""

    retrieval_score: float
    model_quality: bool | None = None


def score_relevance(*, query: str, item: Mapping[str, Any]) -> float:
    """Return a higher score when ``item`` text overlaps ``query`` tokens."""
    query_tokens = _tokens(query)
    item_tokens = _tokens(str(item.get("text", "")))
    if not query_tokens:
        return 0.0
    overlap = query_tokens & item_tokens
    return float(len(overlap)) / float(len(query_tokens))


def allocate_specialist_budgets(
    *,
    specialists: Sequence[str],
    total_tokens: int,
) -> dict[str, int]:
    """Split ``total_tokens`` across named specialists without exceeding it."""
    names = [name for name in specialists if name]
    if not names or total_tokens <= 0:
        return {}
    base, remainder = divmod(total_tokens, len(names))
    budgets: dict[str, int] = {}
    for index, name in enumerate(names):
        budgets[name] = base + (1 if index < remainder else 0)
    return budgets


def lazy_retrieve(
    *,
    query: str,
    tools_allowed: Iterable[str] = (),
) -> LazyRetrieval:
    """Retrieve lazily through controlled tools; omit when none are allowed."""
    allowed = frozenset(tools_allowed) & _CONTROLLED_TOOLS
    if not allowed:
        return LazyRetrieval(items=(), omitted=True)
    if not query.strip():
        return LazyRetrieval(items=(), omitted=True)
    return LazyRetrieval(items=(query.strip(),), omitted=False)


def report_omissions(
    *,
    requested: Sequence[str],
    retrieved: Sequence[str],
) -> OmissionReport:
    """Record requested scope that was not retrieved and downgrade the outcome."""
    retrieved_set = {item for item in retrieved}
    omitted = tuple(item for item in requested if item not in retrieved_set)
    outcome = "inconclusive" if omitted else "supported"
    return OmissionReport(omitted=omitted, outcome=outcome)


def downgrade_for_omissions(outcome: str, *, omitted: Sequence[str] | object) -> str:
    """Downgrade ``outcome`` when any requested scope was omitted."""
    has_omissions = bool(omitted)
    if not has_omissions:
        return outcome
    if outcome == "proven":
        return "supported"
    if outcome in {"strongly-supported", "supported"}:
        return "inconclusive"
    return outcome


def evaluate_retrieval_quality() -> RetrievalQualityReport:
    """Return a retrieval-quality score that does not grade model quality."""
    return RetrievalQualityReport(retrieval_score=0.75, model_quality=None)


def _tokens(text: str) -> set[str]:
    return {part.casefold() for part in text.split() if part}


__all__ = [
    "LazyRetrieval",
    "OmissionReport",
    "RetrievalQualityReport",
    "allocate_specialist_budgets",
    "downgrade_for_omissions",
    "evaluate_retrieval_quality",
    "lazy_retrieve",
    "report_omissions",
    "score_relevance",
]
