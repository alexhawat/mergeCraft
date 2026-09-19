"""Jev architecture checklist — fan-out routing, state filtering, stakes (issues #724/#729).

Patterns for TypeSafe System One / Jev call sites. Routing uses answers **and**
confidence; noul at 0.5 is a coin-flip act threshold, not a medium-intensity
label. Arithmetic and counts stay in Python — Jev answers judgment questions only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final, Literal

from mergecraft.jev.pack_registry import DEFAULT_THRESHOLDS, state_fields_for
from mergecraft.jev.types import NOUL_ACT_FLOOR
from mergecraft.utils.fence import Fence, render_untrusted

if TYPE_CHECKING:
    from collections.abc import Mapping

    from mergecraft.config.settings import RepoSettings
    from mergecraft.jev.questions import QuestionPack

Stakes = Literal["read_only", "routing", "escalate"]

_STAKES_FLOORS: Final[dict[Stakes, float]] = {
    "read_only": NOUL_ACT_FLOOR,
    "routing": 0.6,
    "escalate": 0.9,
}


def confidence_floor(
    *,
    stakes: Stakes,
    settings: RepoSettings | None = None,
    threshold_key: str | None = None,
) -> float:
    """Return the confidence floor for ``stakes``, optionally overridden by config.

    Args:
        stakes: ``read_only`` (~0.5), ``routing`` (~0.6), or ``escalate`` (~0.9).
        settings: Loaded repo settings. When omitted, falls back to defaults.
        threshold_key: Optional ``{pack_id}.{name}`` key in ``jev.thresholds``.

    Returns:
        float: Inclusive-lower floor in ``[0, 1]``.
    """
    if threshold_key is not None:
        configured = _settings_threshold(threshold_key, settings)
        if configured is not None:
            return configured
    return _STAKES_FLOORS[stakes]


def route_choice(
    *,
    choice: str,
    confidence: float,
    act_on: frozenset[str],
    floor: float,
) -> bool:
    """Route on answer **and** confidence — never choice alone (checklist item 4).

    Args:
        choice: Selected option token.
        confidence: Calibrated choice confidence in ``[0, 1]``.
        act_on: Choices that may trigger downstream code when above ``floor``.
        floor: Inclusive-lower confidence required to act.

    Returns:
        bool: ``True`` when ``choice`` is in ``act_on`` and ``confidence >= floor``.
    """
    return choice in act_on and float(confidence) >= float(floor)


def route_noul(*, noul: float, floor: float = NOUL_ACT_FLOOR) -> bool:
    """Act when a noul probability meets the floor.

    At the default floor (0.5) a noul is a coin flip — not "medium intensity".
    Do not port thresholds between noul and choice primitives.

    Args:
        noul: Yes-probability in ``[0, 1]``.
        floor: Inclusive-lower act threshold.

    Returns:
        bool: ``True`` when ``noul >= floor``.
    """
    return float(noul) >= float(floor)


def build_system_one_questions(
    pack: QuestionPack,
    *,
    speculative: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Fan-out one ``system_one`` question map, including optional speculative asks.

    Speculative questions are sent in the same call; callers ignore unused answers
    in code (checklist item 1).

    Args:
        pack: Versioned question pack.
        speculative: Extra question objects merged after the pack battery.

    Returns:
        dict[str, Any]: ``questions=`` payload for ``system_one``.
    """
    merged = dict(pack.as_system_one())
    if speculative:
        merged.update(dict(speculative))
    return merged


def filter_state_for_pack(
    pack_id: str,
    state: dict[str, Any],
    *,
    trust_tier: str = "trusted",
    fence: Fence | None = None,
) -> dict[str, Any]:
    """Keep only fields the pack needs; fence untrusted string content (checklist 3, 10).

    Args:
        pack_id: Versioned pack id.
        state: Raw caller payload.
        trust_tier: ``trusted`` or ``untrusted``.
        fence: Optional per-run fence nonce carrier for untrusted tiers.

    Returns:
        dict[str, Any]: Filtered (and optionally fenced) state for ``system_one``.
    """
    allowed = state_fields_for(pack_id)
    if not allowed:
        return dict(state)
    filtered: dict[str, Any] = {}
    for key in allowed:
        if key not in state:
            continue
        value = state[key]
        if trust_tier == "untrusted" and isinstance(value, str):
            run_fence = fence if fence is not None else Fence()
            value = render_untrusted(
                value,
                author="unknown",
                tier=trust_tier,
                label=f"jev.{pack_id}.{key}",
                nonce=run_fence.nonce,
            )
        filtered[key] = value
    return filtered


def _settings_threshold(key: str, settings: RepoSettings | None) -> float | None:
    if settings is None:
        from mergecraft.config.settings import default_settings

        settings = default_settings()
    raw = settings.jev.thresholds.get(key)
    if raw is None:
        raw = DEFAULT_THRESHOLDS.get(key)
    if isinstance(raw, int | float) and not isinstance(raw, bool):
        return float(raw)
    return None


__all__ = [
    "Stakes",
    "build_system_one_questions",
    "confidence_floor",
    "filter_state_for_pack",
    "route_choice",
    "route_noul",
]
