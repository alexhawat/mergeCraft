"""Model diversity policy — verification must not share the authoring family (AP3, #45).

Generalizes ``PINNED_JUDGE_MODELS`` from a single hard-coded Claude entry into a
declared rule: the verifier's executed model must come from a different provider
family than the authoring (reviewer / specialist) model.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.agents.registry import AgentRole, ResolvedAgentModel, resolve_agent_model
from mergecraft.agents.verifier import pinned_judge_model
from mergecraft.models import MODEL_ALIASES, get_model_provider, resolve_display_alias
from mergecraft.utils.agent_resolve import effective_model_chain, pick_runnable_slug_from_chain

if TYPE_CHECKING:
    from mergecraft.agents.registry import Registry
    from mergecraft.config.settings import RepoSettings


class ModelDiversityViolation(ValueError):
    """Raised when verification would run on the authoring provider family."""


def model_family(slug: str) -> str:
    """Coarse provider family for diversity checks (e.g. ``anthropic``, ``openai``)."""
    pinned_claude = pinned_judge_model("claude")
    if pinned_claude is not None and slug == pinned_claude:
        return "anthropic"
    alias = resolve_display_alias(slug)
    if alias is not None:
        return alias.provider
    for entry in MODEL_ALIASES:
        if entry.slug == slug or entry.resolve == slug:
            return entry.provider
    if "/" in slug:
        return get_model_provider(slug)
    msg = f"cannot resolve model family for slug {slug!r}"
    raise ValueError(msg)


def assert_verification_diverse(
    *,
    authoring_slug: str,
    verification_slug: str,
) -> None:
    """Reject verification on the same provider family as the authoring model."""
    if model_family(authoring_slug) == model_family(verification_slug):
        msg = (
            f"verification model {verification_slug!r} shares the authoring family "
            f"{model_family(authoring_slug)!r} with {authoring_slug!r}"
        )
        raise ModelDiversityViolation(msg)


def resolve_diverse_verification_model(
    *,
    authoring_slug: str,
    registry: Registry,
    settings: RepoSettings,
) -> ResolvedAgentModel:
    """Pick a runnable verifier slug from a different provider family."""
    verifier = registry.resolve_role(AgentRole.verifier)
    candidates = list(verifier.model_chain) + effective_model_chain(settings)
    seen: set[str] = set()
    authoring_family = model_family(authoring_slug)

    for slug in candidates:
        if slug in seen:
            continue
        seen.add(slug)
        if model_family(slug) == authoring_family:
            continue
        runnable = pick_runnable_slug_from_chain(
            [slug],
            allow_fallback=settings.allow_fallback,
        )
        if runnable is None:
            continue
        assert_verification_diverse(
            authoring_slug=authoring_slug,
            verification_slug=runnable,
        )
        return ResolvedAgentModel(
            requested_model=slug,
            executed_model=runnable,
            recorded_model=runnable,
            dispatched_model=runnable,
        )

    msg = (
        f"no verification model in a different family from authoring "
        f"{authoring_slug!r} ({authoring_family!r})"
    )
    raise ModelDiversityViolation(msg)


def enforce_policy_for_harness(
    *,
    registry: Registry,
    settings: RepoSettings,
    harness: str,
) -> None:
    """Ensure model-diversity policy can be satisfied for this harness roster."""
    del harness
    reviewer = registry.resolve_role(AgentRole.reviewer)
    authoring = resolve_agent_model(reviewer, settings=settings).dispatched_model
    resolve_diverse_verification_model(
        authoring_slug=authoring,
        registry=registry,
        settings=settings,
    )


__all__ = [
    "ModelDiversityViolation",
    "assert_verification_diverse",
    "enforce_policy_for_harness",
    "model_family",
    "resolve_diverse_verification_model",
]
