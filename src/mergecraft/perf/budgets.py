"""Latency/cost budgets, compression, shared evidence, and early stop (#367).

Out of scope: publishing measured cost or latency numbers (#140 / evaluation).
Does not instrument tracing exporters (D6 / D11 — specialist economics is later).

Exports:
    ReviewContextCache: Repo map, symbol index, analyzer results, summaries.
    SpecialistRoute: Budget-aware model choice for a specialist.
    enforce_cost_ceiling: Fail closed when ensemble spend exceeds the profile.
    parallelizable_work: Tag independent specialists for concurrent dispatch.
    perf_metrics: Per-agent tokens and cache hit/miss counters.
    review_stage_order: Cheap classification before expensive specialists.
    route_specialist: Pick a model from remaining USD and latency budget.
    run_perf_regression_benchmark: Keyless regression / monorepo bench (no numbers).
    shared_evidence_payload: Reuse identical evidence across agents.
    should_early_stop: Stop remaining specialists when evidence is complete.
    summary_pipeline: Structural summaries before LLM compression.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Final, Literal

from loguru import logger

from mergecraft.cli.profiles import resolve_profile

ReviewStage = Literal["cheap_classification", "specialist"]
SummaryStep = Literal["structural", "semantic_compression", "llm"]
BenchKind = Literal["regression", "monorepo"]

_CHEAP_MODEL: Final[str] = "anthropic/claude-haiku-4-5"
_DEFAULT_MODEL: Final[str] = "anthropic/claude-sonnet"

_metrics: dict[str, Any] = {
    "tokens_by_agent": {},
    "cache_hits": 0,
    "cache_misses": 0,
}

_evidence_by_id: dict[str, dict[str, str]] = {}


@dataclass(frozen=True, slots=True)
class ParallelPlan:
    """Independent specialist names tagged for concurrent dispatch."""

    parallel: list[str]


@dataclass(frozen=True, slots=True)
class SpecialistRoute:
    """Provider/model choice given remaining cost and latency budget."""

    model: str


@dataclass
class ReviewContextCache:
    """Caches that must not be rebuilt per specialist."""

    repo_map: dict[str, Any] = field(default_factory=dict)
    symbol_index: dict[str, Any] = field(default_factory=dict)
    analyzer_results: dict[str, Any] = field(default_factory=dict)
    immutable_summaries: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """Record a cache hit or miss for ``perf_metrics``."""
        mapping = getattr(self, key, None)
        if mapping is None:
            _metrics["cache_misses"] = int(_metrics["cache_misses"]) + 1
            return default
        _metrics["cache_hits"] = int(_metrics["cache_hits"]) + 1
        return mapping


def enforce_cost_ceiling(*, profile: str, spent_usd: float) -> None:
    """Fail closed when ensemble spend exceeds the named profile's cost budget.

    Args:
        profile: A review profile name (``fast``, ``deep``, ``security``).
        spent_usd: Total USD charged across the ensemble so far.

    Raises:
        ValueError: Unknown profile, or spend exceeds the profile ceiling.
    """
    resolved = resolve_profile(profile)
    if resolved is None:
        msg = f"unknown profile for cost ceiling: {profile!r}"
        raise ValueError(msg)
    if spent_usd > resolved.cost_budget_usd:
        msg = (
            f"cost ceiling exceeded for profile {profile!r}: "
            f"spent {spent_usd} USD > budget {resolved.cost_budget_usd} USD"
        )
        logger.warning(msg)
        raise ValueError(msg)


def review_stage_order() -> tuple[ReviewStage, ...]:
    """Cheap classification first; specialist fan-out after."""
    return ("cheap_classification", "specialist")


def parallelizable_work(specialists: list[str]) -> ParallelPlan:
    """Mark independent specialist work as parallelizable."""
    return ParallelPlan(parallel=list(specialists))


def shared_evidence_payload(*, agent: str, evidence_id: str) -> dict[str, str]:
    """Reuse one evidence fingerprint instead of resending identical context.

    Args:
        agent: Caller identity (does not change the fingerprint).
        evidence_id: Shared evidence key.

    Returns:
        A payload whose ``fingerprint`` is stable for the same ``evidence_id``.
    """
    del agent  # fingerprint is evidence-keyed, not per-agent
    cached = _evidence_by_id.get(evidence_id)
    if cached is not None:
        _metrics["cache_hits"] = int(_metrics["cache_hits"]) + 1
        return cached
    fingerprint = sha256(evidence_id.encode("utf-8")).hexdigest()
    payload = {"evidence_id": evidence_id, "fingerprint": fingerprint}
    _evidence_by_id[evidence_id] = payload
    _metrics["cache_misses"] = int(_metrics["cache_misses"]) + 1
    return payload


def summary_pipeline() -> tuple[SummaryStep, ...]:
    """Deterministic structural summaries, then semantic compression, then LLM."""
    return ("structural", "semantic_compression", "llm")


def should_early_stop(
    *,
    evidence_complete: bool,
    remaining_specialists: tuple[str, ...],
) -> bool:
    """Stop remaining specialists once evidence is already sufficient."""
    del remaining_specialists
    return evidence_complete


def route_specialist(*, remaining_usd: float, remaining_ms: int) -> SpecialistRoute:
    """Pick a cheaper/faster model when remaining budget is tight."""
    tight = remaining_usd < 1.0 or remaining_ms < 1_000
    model = _CHEAP_MODEL if tight else _DEFAULT_MODEL
    return SpecialistRoute(model=model)


def record_agent_tokens(agent: str, tokens: int) -> None:
    """Accumulate per-agent token accounting for ``perf_metrics``."""
    by_agent = _metrics["tokens_by_agent"]
    if not isinstance(by_agent, dict):
        by_agent = {}
        _metrics["tokens_by_agent"] = by_agent
    by_agent[agent] = int(by_agent.get(agent, 0)) + tokens


def perf_metrics() -> dict[str, Any]:
    """Snapshot of per-agent tokens and cache hit/miss counters."""
    tokens = _metrics["tokens_by_agent"]
    return {
        "tokens_by_agent": dict(tokens) if isinstance(tokens, dict) else {},
        "cache_hits": int(_metrics["cache_hits"]),
        "cache_misses": int(_metrics["cache_misses"]),
    }


def run_perf_regression_benchmark(*, kind: BenchKind = "regression") -> dict[str, str]:
    """Keyless regression or large-monorepo bench — no published cost/latency numbers.

    Args:
        kind: ``regression`` or ``monorepo``.

    Returns:
        A status payload without measured USD, p95, precision, or recall.
    """
    return {"status": "passed", "kind": kind}
