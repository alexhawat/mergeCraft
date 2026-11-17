"""Jev ``risk/v1`` pack and diff-scoped risk questions (#1489)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from mergecraft.classify.blast_radius import LANE_REASON_CATALOGUE, Lane, LaneReason
from mergecraft.jev.types import NoulAnswer, SystemOneResponse

if TYPE_CHECKING:
    from mergecraft.config.settings import RepoSettings
    from mergecraft.jev.client import AsyncJevClient

from mergecraft.jev.types import RISK_PACK_ID

_RISK_QUESTIONS: Final[tuple[tuple[str, str, Lane], ...]] = (
    (
        "data_loss",
        "Does this diff delete or rewrite persisted data outside a migrations/ path?",
        "high",
    ),
    (
        "authz",
        "Does this diff change an authentication or authorization decision?",
        "high",
    ),
    (
        "secrets",
        "Does this diff handle, log, or transmit secrets or credentials?",
        "high",
    ),
    (
        "flag_enabled",
        "Does this diff enable a feature flag or change a flag default to on?",
        "high",
    ),
)


def risk_pack_questions() -> list[dict[str, Any]]:
    """TypeSafe question objects for one ``risk/v1`` call."""
    return [
        {
            "type": "noul",
            "name": name,
            "instructions": text,
        }
        for name, text, _lane in _RISK_QUESTIONS
    ]


def jev_reasons_from_answers(answers: dict[str, NoulAnswer], *, floor: Lane) -> list[LaneReason]:
    """Map affirmative noul answers to ``jev.*`` lane reasons (raise-only versus floor)."""
    reasons: list[LaneReason] = []
    for name, _text, lane in _RISK_QUESTIONS:
        answer = answers.get(name)
        if answer is None or answer.noul < 0.6:
            continue
        code = f"jev.{name}"
        reasons.append(
            LaneReason(
                code=code,
                lane=lane if _lane_rank(lane) > _lane_rank(floor) else floor,
                message=f"Jev risk/v1: {name.replace('_', ' ')} (noul={answer.noul:.2f})",
            )
        )
    return [r for r in reasons if _lane_rank(r.lane) > _lane_rank(floor)]


def _lane_rank(lane: Lane) -> int:
    return {"low": 0, "medium": 1, "high": 2}[lane]


def jev_skip_reasons(code: str) -> list[LaneReason]:
    """Record why Jev did not run, without lowering the deterministic lane."""
    key = f"jev.{code.replace('_', '.')}"
    return [
        LaneReason(
            code=key,
            lane=LANE_REASON_CATALOGUE["baseline.clean"],
            message=f"Jev risk grading did not run ({code})",
        )
    ]


async def evaluate_jev_risk(
    client: AsyncJevClient,
    *,
    diff_excerpt: str,
    floor: Lane,
) -> tuple[list[LaneReason], list[LaneReason]]:
    """One ``risk/v1`` battery over a bounded diff excerpt."""
    skip = client.availability_skip(pack_id=RISK_PACK_ID)
    if skip is not None:
        reason = skip.reason or "disabled"
        return [], jev_skip_reasons(str(reason))
    from mergecraft.jev.architecture import build_system_one_questions
    from mergecraft.jev.questions import get_pack

    questions = build_system_one_questions(get_pack(RISK_PACK_ID))
    result = await client.call(
        state={"diff": diff_excerpt[:120_000]},
        pack_id=RISK_PACK_ID,
        unit_id="pr-risk",
        trust_tier="trusted",
        questions=questions,
    )
    if result.skipped:
        return [], jev_skip_reasons(result.reason or "disabled")
    response = result.response
    if not isinstance(response, SystemOneResponse):
        return [], jev_skip_reasons("incomplete")
    answers: dict[str, NoulAnswer] = {}
    for name, _text, _lane in _RISK_QUESTIONS:
        raw = response.answers.get(name)
        if isinstance(raw, NoulAnswer):
            answers[name] = raw
    return jev_reasons_from_answers(answers, floor=floor), []


def risk_jev_client(settings: RepoSettings) -> Any:
    from mergecraft.jev.client import AsyncJevClient

    return AsyncJevClient(settings=settings.jev)


__all__ = [
    "RISK_PACK_ID",
    "evaluate_jev_risk",
    "jev_reasons_from_answers",
    "jev_skip_reasons",
    "risk_jev_client",
    "risk_pack_questions",
]
