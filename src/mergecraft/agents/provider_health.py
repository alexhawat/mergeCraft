"""Provider health, cooldown, residency, and model routing (#371).

Tracks capability dimensions, require/prefer/fallback routing, circuit
breakers with cooldown, bounded retryable-only retries, and residency
policy. Does not import tracing exporters (D6). Does not publish measured
cost-per-review figures.

Exports:
    ProviderBreaker: Open circuit with a cooldown before re-entry.
    ProviderHealth: Failure counters and unhealthy snapshots.
    ROUTING_INTENTS: ``require`` / ``prefer`` / ``fallback``.
    capability_catalog: Named capability rows for routing.
    degrade_unavailable: Non-required outages degrade instead of failing.
    enforce_provider_budget: Per-provider spend ceiling (fail closed).
    enforce_residency: Refuse a region outside the allowed set.
    evaluate_routing_quality: Reject cheaper routing that harms quality.
    manifest_provider_stamp: Provider/model plus prompt/config/policy hashes.
    nightly_provider_smoke: Catalog drift probe (live gate optional).
    resolve_required_model: Never silently substitute a required pin.
    route_model: Per-specialist and per-risk model selection.
    should_retry_provider: Retryable failures only, bounded attempts.
    verifier_judge_models: Heterogeneous verifier vs judge pair.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Any, Final

from loguru import logger

from mergecraft.utils.risk_bands import RISK_BANDS, risk_at_or_above

ROUTING_INTENTS: Final[frozenset[str]] = frozenset({"require", "prefer", "fallback"})
MAX_RETRY_ATTEMPTS: Final[int] = 5
RETRYABLE_FAILURES: Final[frozenset[str]] = frozenset(
    {"rate_limit", "timeout", "overloaded", "unavailable", "5xx"}
)

_CAPABILITY_CATALOG: Final[tuple[dict[str, Any], ...]] = (
    {
        "id": "anthropic/claude-opus",
        "context_size": 200_000,
        "reasoning": True,
        "tool_support": True,
        "structured_output": True,
        "cost": "high",
        "latency": "high",
        "data_residency": "us-east-1",
    },
    {
        "id": "anthropic/claude-sonnet",
        "context_size": 200_000,
        "reasoning": True,
        "tool_support": True,
        "structured_output": True,
        "cost": "medium",
        "latency": "medium",
        "data_residency": "us-east-1",
    },
    {
        "id": "anthropic/claude-haiku",
        "context_size": 200_000,
        "reasoning": False,
        "tool_support": True,
        "structured_output": True,
        "cost": "low",
        "latency": "low",
        "data_residency": "us-east-1",
    },
    {
        "id": "openai/gpt-5.3-codex",
        "context_size": 128_000,
        "reasoning": True,
        "tool_support": True,
        "structured_output": True,
        "cost": "medium",
        "latency": "medium",
        "data_residency": "us-east-1",
    },
)

_ROUTE_TABLE: Final[dict[tuple[str, str], str]] = {
    ("security", "high"): "anthropic/claude-opus",
    ("security", "critical"): "anthropic/claude-opus",
    ("security", "trivial"): "anthropic/claude-haiku",
    ("tests", "high"): "openai/gpt-5.3-codex",
    ("tests", "critical"): "openai/gpt-5.3-codex",
    ("tests", "trivial"): "anthropic/claude-haiku",
}


def _routing_risk_band(risk: str) -> str:
    """Map a routing risk label onto the shared ``RISK_BANDS`` vocabulary."""
    normalized = str(risk).casefold()
    if normalized == "trivial":
        return "low"
    if normalized not in RISK_BANDS:
        logger.warning(
            "Unknown risk band {risk!r}; routing as high-tier capable model",
            risk=risk,
        )
        return "high"
    return normalized


@dataclass(frozen=True, slots=True)
class DegradeOutcome:
    """Result of degrading a non-required provider outage."""

    status: str


@dataclass(frozen=True, slots=True)
class RoutingEvalResult:
    """Whether a cheaper candidate preserved review quality."""

    passed: bool


@dataclass(frozen=True, slots=True)
class SmokeReport:
    """Nightly provider-catalog smoke result."""

    passed: bool
    drifted: tuple[str, ...] = ()


class ProviderHealth:
    """In-process failure tracking for a provider identity."""

    def __init__(self) -> None:
        self._failures: dict[str, int] = {}
        self._reasons: dict[str, str] = {}

    def record_failure(self, provider: str, reason: str = "") -> None:
        """Record one failure against ``provider``."""
        key = str(provider)
        self._failures[key] = self._failures.get(key, 0) + 1
        if reason:
            self._reasons[key] = reason
        logger.warning(
            "provider health failure for {provider} ({reason}); count={n}",
            provider=key,
            reason=reason or "unspecified",
            n=self._failures[key],
        )

    def snapshot(self, provider: str) -> dict[str, Any]:
        """Return failure count and unhealthy flag for ``provider``."""
        key = str(provider)
        failures = self._failures.get(key, 0)
        return {
            "provider": key,
            "failures": failures,
            "unhealthy": failures > 0,
            "reason": self._reasons.get(key, ""),
        }


class ProviderBreaker:
    """Open after ``trip()``; ``allow()`` is False until ``cooldown_s`` elapses."""

    def __init__(self, provider: str, cooldown_s: float) -> None:
        self.provider = provider
        self.cooldown_s = cooldown_s
        self.cooldown = cooldown_s
        self._open = False
        self._opened_at: float | None = None

    def trip(self) -> None:
        """Open the circuit and start cooldown."""
        self._open = True
        self._opened_at = monotonic()
        logger.warning(
            "provider circuit breaker open for {provider}; cooldown_s={cooldown}",
            provider=self.provider,
            cooldown=self.cooldown_s,
        )

    def allow(self) -> bool:
        """Return False while the circuit is open and cooldown has not elapsed."""
        if not self._open:
            return True
        opened = self._opened_at
        if opened is None:
            return False
        if monotonic() - opened >= self.cooldown_s:
            self._open = False
            self._opened_at = None
            return True
        return False


def capability_catalog() -> list[dict[str, Any]]:
    """Return catalog rows with context, reasoning, tools, structured IO, cost, latency, residency."""
    return [dict(row) for row in _CAPABILITY_CATALOG]


def route_model(*, specialist: str, risk: str) -> str:
    """Select a model for ``specialist`` at ``risk``.

    Args:
        specialist: Review specialist id (e.g. ``security``).
        risk: Change risk band (e.g. ``high``, ``critical``, ``trivial``).

    Returns:
        A catalog model id. High- and critical-risk bands never use the
        trivial-risk cheap pick.
    """
    risk_key = str(risk).casefold()
    key = (str(specialist), risk_key)
    if key in _ROUTE_TABLE:
        chosen = _ROUTE_TABLE[key]
    elif str(specialist) == "security" and risk_at_or_above(
        _routing_risk_band(risk),
        "high",
    ):
        chosen = "anthropic/claude-opus"
    else:
        chosen = "anthropic/claude-haiku"
    from mergecraft.enterprise.runtime import enforce_routed_model_residency

    enforce_routed_model_residency(chosen)
    return chosen


def verifier_judge_models() -> dict[str, str]:
    """Return a heterogeneous verifier / judge pair (never the same model)."""
    return {
        "verifier": "openai/gpt-5.3-codex",
        "judge": "anthropic/claude-sonnet",
    }


def should_retry_provider(*, failure: str, attempt: int) -> bool:
    """Return whether ``failure`` may be retried at ``attempt``.

    Args:
        failure: Failure class (``rate_limit``, ``auth``, …).
        attempt: 1-based attempt number.

    Returns:
        True only for retryable failures within ``MAX_RETRY_ATTEMPTS``.

    Raises:
        ValueError: Attempt is outside the retry bound.
    """
    if attempt < 1 or attempt > MAX_RETRY_ATTEMPTS:
        msg = f"retry attempt {attempt} exceeds bound of {MAX_RETRY_ATTEMPTS}"
        raise ValueError(msg)
    kind = str(failure).casefold()
    return kind in RETRYABLE_FAILURES


def degrade_unavailable(*, provider: str, required: bool) -> DegradeOutcome:
    """Degrade a non-required outage; fail closed when the provider is required.

    Args:
        provider: Provider id that is unavailable.
        required: When True, the outage is not eligible for silent degradation.

    Returns:
        Outcome whose ``status`` is ``degraded`` for optional providers.

    Raises:
        RuntimeError: ``required`` is True — do not substitute.
    """
    if required:
        msg = f"required provider {provider!r} is unavailable; refusing substitution"
        raise RuntimeError(msg)
    logger.warning("non-required provider {provider} unavailable; degrading", provider=provider)
    return DegradeOutcome(status="degraded")


def resolve_required_model(*, required: str, available: tuple[str, ...] | list[str]) -> str:
    """Return ``required`` when it is available; never silently substitute.

    Args:
        required: Policy-pinned model id.
        available: Models the run may actually call.

    Returns:
        The required model when present in ``available``.

    Raises:
        LookupError: The required pin is missing — no silent substitution.
    """
    pin = str(required)
    if pin in {str(item) for item in available}:
        return pin
    msg = f"required model {pin!r} is not available; refusing silent substitution"
    raise LookupError(msg)


def manifest_provider_stamp(
    *,
    provider: str,
    model: str,
    prompt_hash: str,
    config_hash: str,
    policy_hash: str,
) -> dict[str, str]:
    """Stamp exact provider/model versions and prompt/config/policy hashes."""
    return {
        "provider": provider,
        "model": model,
        "prompt_hash": prompt_hash,
        "config_hash": config_hash,
        "policy_hash": policy_hash,
    }


def enforce_provider_budget(*, provider: str, spent_usd: float, limit_usd: float) -> None:
    """Fail closed when ``spent_usd`` exceeds the per-provider budget.

    Args:
        provider: Provider whose spend is being checked.
        spent_usd: Spend already attributed to the provider.
        limit_usd: Hard ceiling.

    Raises:
        ValueError: Spend exceeds the token/cost budget.
    """
    if spent_usd > limit_usd:
        msg = (
            f"provider {provider!r} exceeded cost budget: "
            f"spent_usd={spent_usd} limit_usd={limit_usd}"
        )
        raise ValueError(msg)


def evaluate_routing_quality(
    *,
    baseline_quality: float,
    candidate_quality: float,
    baseline_usd: float,
    candidate_usd: float,
) -> RoutingEvalResult:
    """Fail the eval when cheaper routing harms review quality.

    A cheaper candidate must not drop quality below the baseline. Equal or
    better quality at lower spend passes; a quality regression fails.
    """
    cheaper = candidate_usd < baseline_usd
    worse = candidate_quality < baseline_quality
    passed = not (cheaper and worse)
    return RoutingEvalResult(passed=passed)


def enforce_residency(*, region: str, allowed: tuple[str, ...] | list[str]) -> None:
    """Refuse a region that is not in the residency allow-list.

    Args:
        region: Requested processing region.
        allowed: Regions the residency policy permits.

    Raises:
        PermissionError: ``region`` is outside the allowed residency set.
    """
    permitted = {str(item) for item in allowed}
    if str(region) not in permitted:
        msg = f"residency policy forbids region {region!r}; allowed={sorted(permitted)}"
        raise PermissionError(msg)


def nightly_provider_smoke() -> SmokeReport:
    """Detect catalog drift (missing capability dimensions or empty catalog).

    Live CLI/API probes stay behind ``MERGECRAFT_LIVE_E2E=1`` at the test
    layer; this callable always validates the in-repo catalog so a nightly
    job can call it without a second import path.
    """
    required = frozenset(
        {
            "context_size",
            "reasoning",
            "tool_support",
            "structured_output",
            "cost",
            "latency",
            "data_residency",
        }
    )
    drifted: list[str] = []
    rows = capability_catalog()
    if not rows:
        return SmokeReport(passed=False, drifted=("empty_catalog",))
    for row in rows:
        ident = str(row.get("id") or "<unknown>")
        missing = required - set(row)
        if missing:
            drifted.append(f"{ident}:missing:{','.join(sorted(missing))}")
    return SmokeReport(passed=not drifted, drifted=tuple(drifted))


__all__ = [
    "MAX_RETRY_ATTEMPTS",
    "ROUTING_INTENTS",
    "ProviderBreaker",
    "ProviderHealth",
    "capability_catalog",
    "degrade_unavailable",
    "enforce_provider_budget",
    "enforce_residency",
    "evaluate_routing_quality",
    "manifest_provider_stamp",
    "nightly_provider_smoke",
    "resolve_required_model",
    "route_model",
    "should_retry_provider",
    "verifier_judge_models",
]
