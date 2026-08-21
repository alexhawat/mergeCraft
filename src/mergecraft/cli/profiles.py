"""Named review profiles — model chain, analyzer focus, and budget bundles (CC4).

Eight product profiles: fast, standard, deep, security, api_compatibility,
migration, monorepo, cross_repo. CLI hyphens map to the canonical names.
Selection from change risk is automatic; an explicit CLI or policy profile
wins. Budget exhaustion is never a clean pass (#369).

Exports:
    ProfileName: Canonical review-profile identifier.
    ReviewProfile: Resolved operator bundle selected by ``--profile``.
    apply_profile_env: Temporarily apply a profile's env overrides.
    parse_profile_name: Parse a CLI/policy profile token.
    profile_budget_exhaustion_outcome: Map profile budget exhaustion to a run outcome.
    profile_env_overrides: Env patches that apply a profile's budget bundle.
    resolve_profile: Look up a named ``ReviewProfile``.
    resolve_review_profile: Resolve CLI, then policy, then risk auto-select.
    select_profile_from_risk: Pick a profile from a change-risk band.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from mergecraft.utils.run_bounds import BudgetExhausted, budget_exhaustion_outcome

if TYPE_CHECKING:
    from mergecraft.run_outcome import RunOutcome

ProfileName = Literal[
    "fast",
    "standard",
    "deep",
    "security",
    "api_compatibility",
    "migration",
    "monorepo",
    "cross_repo",
]
RiskName = Literal["trivial", "low", "medium", "high", "critical"]

_PROFILE_ORDER: Final[tuple[ProfileName, ...]] = (
    "fast",
    "standard",
    "deep",
    "security",
    "api_compatibility",
    "migration",
    "monorepo",
    "cross_repo",
)
_RISK_ORDER: Final[tuple[RiskName, ...]] = (
    "trivial",
    "low",
    "medium",
    "high",
    "critical",
)
_RISK_TO_PROFILE: Final[dict[str, ProfileName]] = {
    "trivial": "fast",
    "low": "fast",
    "medium": "standard",
    "high": "security",
    "critical": "security",
}


@dataclass(frozen=True, slots=True)
class ReviewProfile:
    """Resolved operator bundle selected by ``--profile``."""

    name: ProfileName
    model_chain: tuple[str, ...] | None
    analyzers_security_only: bool
    token_budget: int
    cost_budget_usd: float
    tool_call_budget: int
    latency_budget_ms: int


_PROFILES: Final[dict[str, ReviewProfile]] = {
    "fast": ReviewProfile(
        name="fast",
        model_chain=("anthropic/claude-haiku-4-5",),
        analyzers_security_only=False,
        token_budget=500_000,
        cost_budget_usd=5.0,
        tool_call_budget=100,
        latency_budget_ms=120_000,
    ),
    "standard": ReviewProfile(
        name="standard",
        model_chain=None,
        analyzers_security_only=False,
        token_budget=1_500_000,
        cost_budget_usd=15.0,
        tool_call_budget=250,
        latency_budget_ms=240_000,
    ),
    "deep": ReviewProfile(
        name="deep",
        model_chain=None,
        analyzers_security_only=False,
        token_budget=4_000_000,
        cost_budget_usd=100.0,
        tool_call_budget=1_000,
        latency_budget_ms=900_000,
    ),
    "security": ReviewProfile(
        name="security",
        model_chain=("anthropic/claude-sonnet",),
        analyzers_security_only=True,
        token_budget=2_000_000,
        cost_budget_usd=25.0,
        tool_call_budget=500,
        latency_budget_ms=300_000,
    ),
    "api_compatibility": ReviewProfile(
        name="api_compatibility",
        model_chain=("anthropic/claude-sonnet",),
        analyzers_security_only=False,
        token_budget=1_000_000,
        cost_budget_usd=15.0,
        tool_call_budget=200,
        latency_budget_ms=240_000,
    ),
    "migration": ReviewProfile(
        name="migration",
        model_chain=None,
        analyzers_security_only=False,
        token_budget=3_000_000,
        cost_budget_usd=50.0,
        tool_call_budget=750,
        latency_budget_ms=600_000,
    ),
    "monorepo": ReviewProfile(
        name="monorepo",
        model_chain=None,
        analyzers_security_only=False,
        token_budget=4_000_000,
        cost_budget_usd=100.0,
        tool_call_budget=1_000,
        latency_budget_ms=900_000,
    ),
    "cross_repo": ReviewProfile(
        name="cross_repo",
        model_chain=None,
        analyzers_security_only=False,
        token_budget=3_000_000,
        cost_budget_usd=50.0,
        tool_call_budget=750,
        latency_budget_ms=600_000,
    ),
}


def parse_profile_name(raw: str | None) -> ProfileName | None:
    """Parse a CLI or policy profile token into a canonical name.

    Args:
        raw: Profile token, or ``None`` when unset.

    Returns:
        Canonical ``ProfileName``, or ``None`` when ``raw`` is ``None``.

    Raises:
        ValueError: The token is not one of the eight named profiles.
    """
    if raw is None:
        return None
    key = raw.strip().lower().replace("-", "_")
    profile = _PROFILES.get(key)
    if profile is None:
        allowed = ", ".join(_PROFILE_ORDER)
        msg = f"unknown profile {raw!r} (expected one of: {allowed})"
        raise ValueError(msg)
    return profile.name


def resolve_profile(name: str | None) -> ReviewProfile | None:
    """Look up the named review profile.

    Args:
        name: Canonical or hyphenated profile token, or ``None``.

    Returns:
        The matching ``ReviewProfile``, or ``None`` when ``name`` is ``None``.
    """
    parsed = parse_profile_name(name)
    if parsed is None:
        return None
    return _PROFILES[parsed]


def select_profile_from_risk(risk: str) -> ReviewProfile:
    """Pick a review profile from a change-risk band.

    Args:
        risk: Risk token (``trivial``, ``low``, ``medium``, ``high``, ``critical``).

    Returns:
        The auto-selected ``ReviewProfile``.

    Raises:
        ValueError: The risk token is unknown.
    """
    key = risk.strip().lower().replace("-", "_")
    name = _RISK_TO_PROFILE.get(key)
    if name is None:
        allowed = ", ".join(_RISK_ORDER)
        msg = f"unknown risk {risk!r} (expected one of: {allowed})"
        raise ValueError(msg)
    return _PROFILES[name]


def resolve_review_profile(
    *,
    risk: str | None = None,
    cli_name: str | None = None,
    policy_name: str | None = None,
) -> ReviewProfile:
    """Resolve a profile: CLI, then policy, then risk auto-select.

    Args:
        risk: Change-risk band used when neither override is set.
        cli_name: Explicit CLI ``--profile`` token; wins over policy and risk.
        policy_name: Policy-pinned profile; wins over risk when CLI is unset.

    Returns:
        The winning ``ReviewProfile``.

    Raises:
        ValueError: A provided name or risk token is unknown, or nothing selected.
    """
    if cli_name is not None:
        chosen = resolve_profile(cli_name)
        if chosen is None:
            msg = "unknown profile for CLI override"
            raise ValueError(msg)
        return chosen
    if policy_name is not None:
        chosen = resolve_profile(policy_name)
        if chosen is None:
            msg = "unknown profile for policy override"
            raise ValueError(msg)
        return chosen
    if risk is None:
        msg = "unknown risk: no risk band and no CLI or policy profile"
        raise ValueError(msg)
    return select_profile_from_risk(risk)


def profile_budget_exhaustion_outcome(*, profile: str) -> RunOutcome:
    """Map named-profile budget exhaustion to ``inconclusive`` (never passed).

    Args:
        profile: Canonical or hyphenated profile name whose budget was exhausted.

    Returns:
        ``RunOutcome.inconclusive``.

    Raises:
        ValueError: The profile name is unknown.
    """
    resolved = resolve_profile(profile)
    if resolved is None:
        msg = f"unknown profile {profile!r}"
        raise ValueError(msg)
    return budget_exhaustion_outcome(
        BudgetExhausted("token", f"profile {resolved.name} budget exhausted")
    )


def profile_env_overrides(profile: ReviewProfile) -> dict[str, str]:
    """Env patches that apply a profile's budget bundle."""
    return {
        "MERGECRAFT_TOKEN_BUDGET": str(profile.token_budget),
        "MERGECRAFT_COST_BUDGET_USD": str(profile.cost_budget_usd),
        "MERGECRAFT_TOOL_CALL_BUDGET": str(profile.tool_call_budget),
        "MERGECRAFT_LATENCY_BUDGET_MS": str(profile.latency_budget_ms),
        "MERGECRAFT_PROFILE": profile.name,
    }


@contextmanager
def apply_profile_env(
    profile: ReviewProfile | None,
    *,
    env: Mapping[str, str] | None = None,
) -> Iterator[None]:
    """Temporarily apply a profile's env overrides for one CLI invocation."""
    if profile is None:
        yield
        return
    lookup = env if env is not None else os.environ
    previous: dict[str, str | None] = {}
    for key, value in profile_env_overrides(profile).items():
        previous[key] = lookup.get(key)
        os.environ[key] = value
    try:
        yield
    finally:
        for key, prev_value in previous.items():
            if prev_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev_value


__all__ = [
    "ProfileName",
    "ReviewProfile",
    "RiskName",
    "apply_profile_env",
    "parse_profile_name",
    "profile_budget_exhaustion_outcome",
    "profile_env_overrides",
    "resolve_profile",
    "resolve_review_profile",
    "select_profile_from_risk",
]
