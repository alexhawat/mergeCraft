"""Named review profiles — model chain, analyzer focus, and budget bundles (CC4)."""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Final, Literal

ProfileName = Literal["fast", "deep", "security"]

_PROFILE_NAMES: Final[frozenset[str]] = frozenset({"fast", "deep", "security"})


@dataclass(frozen=True, slots=True)
class ReviewProfile:
    """Resolved operator bundle selected by ``--profile``."""

    name: ProfileName
    model_chain: tuple[str, ...] | None
    analyzers_security_only: bool
    token_budget: int
    cost_budget_usd: float
    tool_call_budget: int


_PROFILES: Final[dict[ProfileName, ReviewProfile]] = {
    "fast": ReviewProfile(
        name="fast",
        model_chain=("anthropic/claude-haiku-4-5",),
        analyzers_security_only=False,
        token_budget=500_000,
        cost_budget_usd=5.0,
        tool_call_budget=100,
    ),
    "deep": ReviewProfile(
        name="deep",
        model_chain=None,
        analyzers_security_only=False,
        token_budget=4_000_000,
        cost_budget_usd=100.0,
        tool_call_budget=1_000,
    ),
    "security": ReviewProfile(
        name="security",
        model_chain=("anthropic/claude-sonnet",),
        analyzers_security_only=True,
        token_budget=2_000_000,
        cost_budget_usd=25.0,
        tool_call_budget=500,
    ),
}


def parse_profile_name(raw: str | None) -> ProfileName | None:
    if raw is None:
        return None
    key = raw.strip().lower()
    if key not in _PROFILE_NAMES:
        msg = f"unknown profile {raw!r} (expected one of: fast, deep, security)"
        raise ValueError(msg)
    return key  # type: ignore[return-value]  # — key verified against _PROFILE_NAMES above


def resolve_profile(name: str | None) -> ReviewProfile | None:
    parsed = parse_profile_name(name)
    if parsed is None:
        return None
    return _PROFILES[parsed]


def profile_env_overrides(profile: ReviewProfile) -> dict[str, str]:
    """Env patches that apply a profile's budget bundle."""
    return {
        "MERGECRAFT_TOKEN_BUDGET": str(profile.token_budget),
        "MERGECRAFT_COST_BUDGET_USD": str(profile.cost_budget_usd),
        "MERGECRAFT_TOOL_CALL_BUDGET": str(profile.tool_call_budget),
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
    target = dict(env if env is not None else os.environ)
    previous: dict[str, str | None] = {}
    for key, value in profile_env_overrides(profile).items():
        previous[key] = target.get(key)
        target[key] = value
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
    "apply_profile_env",
    "parse_profile_name",
    "profile_env_overrides",
    "resolve_profile",
]
