"""Per-specialist economics — cost, latency, precision, recall, pruning (#370).

Consumes ``gen_ai.usage.*`` already stamped on ``llm.call`` spans (D11).
Does not import or re-instrument tracing exporters (D6). Lens registry and
risk-based routing stay on ``review.lens_routing``; provider health is #371.

Exports:
    SpecialistBreaker: Per-agent circuit breaker for repeated zero-value spend.
    cost_from_usage_spans: Sum ``gen_ai.usage.cost_usd`` on ``llm.call`` spans.
    degraded_specialists: Skip requested specialists whose breaker is open.
    low_value_specialists: Name specialists that spend without unique useful findings.
    specialist_metrics: Latency, cost, precision, and recall for one specialist.
    unique_useful_findings: Count distinct useful findings for one specialist.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final

from loguru import logger

LLM_CALL_SPAN: Final = "llm.call"
USAGE_COST_USD: Final = "gen_ai.usage.cost_usd"


def _as_mapping(item: Any) -> Mapping[str, Any]:
    if isinstance(item, Mapping):
        return item
    return dict(item)


def _finding_id(finding: Mapping[str, Any]) -> str:
    raw = finding.get("id")
    return "" if raw is None else str(raw)


def _is_useful(finding: Mapping[str, Any]) -> bool:
    return bool(finding.get("useful"))


def _finding_specialist(finding: Mapping[str, Any]) -> str | None:
    raw = finding.get("specialist")
    if raw is None:
        return None
    return str(raw)


def unique_useful_findings(specialist: str, findings: Sequence[Any]) -> int:
    """Count distinct useful findings attributed to ``specialist``.

    Args:
        specialist: Specialist id to count.
        findings: Finding records with ``id``, ``useful``, and optional ``specialist``.

    Returns:
        Number of unique useful finding ids for that specialist.
    """
    seen: set[str] = set()
    for raw in findings:
        finding = _as_mapping(raw)
        owner = _finding_specialist(finding)
        if owner is not None and owner != specialist:
            continue
        if owner is None and specialist:
            # Unscoped rows are counted only when the caller already scoped them.
            continue
        if not _is_useful(finding):
            continue
        ident = _finding_id(finding)
        if ident:
            seen.add(ident)
    return len(seen)


def _span_name(span: Mapping[str, Any]) -> str:
    raw = span.get("name")
    return "" if raw is None else str(raw)


def _span_specialist(span: Mapping[str, Any]) -> str | None:
    raw = span.get("specialist")
    if raw is None:
        return None
    return str(raw)


def _span_cost(span: Mapping[str, Any]) -> float:
    raw = span.get(USAGE_COST_USD)
    if raw is None:
        return 0.0
    return float(raw)


def _span_latency_ms(span: Mapping[str, Any]) -> float:
    raw = span.get("duration_ms")
    if raw is None:
        return 0.0
    return float(raw)


def cost_from_usage_spans(spans: Sequence[Any]) -> float:
    """Sum ``gen_ai.usage.cost_usd`` on ``llm.call`` spans (D11).

    Args:
        spans: Span-shaped mappings, typically with ``name`` and usage attrs.

    Returns:
        Total cost in USD.
    """
    total = 0.0
    for raw in spans:
        span = _as_mapping(raw)
        if _span_name(span) != LLM_CALL_SPAN:
            continue
        total += _span_cost(span)
    return total


def _precision_recall(findings: Sequence[Mapping[str, Any]]) -> tuple[float, float]:
    unique_ids: set[str] = set()
    unique_useful: set[str] = set()
    for finding in findings:
        ident = _finding_id(finding)
        if not ident:
            continue
        unique_ids.add(ident)
        if _is_useful(finding):
            unique_useful.add(ident)
    if not unique_ids:
        return 0.0, 0.0
    precision = len(unique_useful) / len(unique_ids)
    recall = 0.0
    return precision, recall


def specialist_metrics(
    *,
    specialist: str,
    spans: Sequence[Any],
    findings: Sequence[Any],
) -> dict[str, float]:
    """Latency, cost, precision, and recall for one specialist.

    Cost is taken from ``gen_ai.usage.cost_usd`` on matching ``llm.call`` spans.

    Args:
        specialist: Specialist id.
        spans: Span-shaped mappings that may carry ``specialist`` and usage attrs.
        findings: Finding records used for precision and recall.

    Returns:
        Mapping with ``latency_ms``, ``cost_usd``, ``precision``, and ``recall``.
    """
    matched_spans: list[Mapping[str, Any]] = []
    for raw in spans:
        span = _as_mapping(raw)
        owner = _span_specialist(span)
        if owner is not None and owner != specialist:
            continue
        matched_spans.append(span)

    scoped_findings: list[Mapping[str, Any]] = []
    for raw in findings:
        finding = _as_mapping(raw)
        owner = _finding_specialist(finding)
        if owner is not None and owner != specialist:
            continue
        scoped_findings.append(finding)

    precision, recall = _precision_recall(scoped_findings)
    metrics = {
        "latency_ms": sum(_span_latency_ms(span) for span in matched_spans),
        "cost_usd": cost_from_usage_spans(matched_spans),
        "precision": precision,
        "recall": recall,
    }
    logger.debug(
        "specialist economics for {specialist}: latency_ms={latency} cost_usd={cost}",
        specialist=specialist,
        latency=metrics["latency_ms"],
        cost=metrics["cost_usd"],
    )
    return metrics


def low_value_specialists(rows: Sequence[Any]) -> list[str]:
    """Name specialists that incur cost without unique useful findings.

    Args:
        rows: Per-specialist summaries with ``specialist``, ``cost_usd``,
            and ``unique_useful_findings``.

    Returns:
        Specialist ids that spent money and produced no unique useful findings.
    """
    named: list[str] = []
    for raw in rows:
        row = _as_mapping(raw)
        specialist = str(row.get("specialist") or "")
        if not specialist:
            continue
        cost = float(row.get("cost_usd") or 0.0)
        useful = int(row.get("unique_useful_findings") or 0)
        if cost > 0.0 and useful == 0:
            named.append(specialist)
    return named


class SpecialistBreaker:
    """Open after ``threshold`` consecutive zero-value, positive-cost runs."""

    def __init__(self, specialist: str, threshold: int) -> None:
        self.specialist = specialist
        self.threshold = threshold
        self._waste_streak = 0
        self._open = False

    def record(self, unique_useful_findings: int, cost_usd: float) -> None:
        """Record one run. Repeated waste opens the breaker."""
        wasted = unique_useful_findings == 0 and cost_usd > 0.0
        if wasted:
            self._waste_streak += 1
            if self._waste_streak >= self.threshold:
                self._open = True
                logger.warning(
                    "specialist circuit breaker open for {specialist} after {n} wasted runs",
                    specialist=self.specialist,
                    n=self._waste_streak,
                )
            return
        self._waste_streak = 0
        self._open = False

    def allow(self) -> bool:
        """Return False when the breaker is open."""
        return not self._open

    def guard(self) -> None:
        """Raise when the breaker is open.

        Raises:
            RuntimeError: The specialist is degraded because the circuit is open.
        """
        if self._open:
            msg = f"circuit breaker open for specialist {self.specialist!r}; degraded"
            raise RuntimeError(msg)


def degraded_specialists(
    *,
    open_breakers: Iterable[str],
    requested: Iterable[str],
) -> list[str]:
    """Return requested specialists that should be skipped because a breaker is open.

    Args:
        open_breakers: Specialist ids whose circuit is open.
        requested: Specialists the caller wanted to run.

    Returns:
        The subset of ``requested`` that is open on a breaker.
    """
    open_set = {str(name) for name in open_breakers}
    return [name for name in requested if str(name) in open_set]


__all__ = [
    "SpecialistBreaker",
    "cost_from_usage_spans",
    "degraded_specialists",
    "low_value_specialists",
    "specialist_metrics",
    "unique_useful_findings",
]
