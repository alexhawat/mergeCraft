"""Jev ``risk/v1`` pack and diff-scoped risk questions (#1489)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.classify.blast_radius import LaneReason, lane_rank
from mergecraft.classify.risk import jev_skip_reasons
from mergecraft.jev.architecture import build_system_one_questions
from mergecraft.jev.questions import get_pack
from mergecraft.jev.types import RISK_PACK_ID, NoulAnswer, SystemOneResponse

if TYPE_CHECKING:
    from collections.abc import Mapping

    from mergecraft.classify.blast_radius import Lane
    from mergecraft.config.settings import TrustTier
    from mergecraft.jev.client import AsyncJevClient


def jev_reasons_from_answers(answers: Mapping[str, object], *, floor: Lane) -> list[LaneReason]:
    """Map affirmative noul answers to ``jev.*`` lane reasons (raise-only versus floor)."""
    raised_lane: Lane = "high"
    if lane_rank(floor) >= lane_rank(raised_lane):
        return []
    reasons: list[LaneReason] = []
    for name in get_pack(RISK_PACK_ID).question_names:
        answer = answers.get(name)
        if not isinstance(answer, NoulAnswer) or answer.noul < 0.6:
            continue
        reasons.append(
            LaneReason(
                code=f"jev.{name}",
                lane=raised_lane,
                message=f"Jev risk/v1: {name.replace('_', ' ')} (noul={answer.noul:.2f})",
            )
        )
    return reasons


async def evaluate_jev_risk(
    client: AsyncJevClient,
    *,
    diff_excerpt: str,
    floor: Lane,
    trust_tier: TrustTier = "untrusted",
) -> tuple[list[LaneReason], list[LaneReason]]:
    """One ``risk/v1`` battery over a bounded diff excerpt."""
    skip = client.availability_skip(pack_id=RISK_PACK_ID)
    if skip is not None:
        return [], jev_skip_reasons(skip.reason or "disabled")
    questions = build_system_one_questions(get_pack(RISK_PACK_ID))
    result = await client.call(
        state={"diff": diff_excerpt[:120_000]},
        pack_id=RISK_PACK_ID,
        unit_id="pr-risk",
        trust_tier=trust_tier,
        questions=questions,
    )
    if result.skipped:
        return [], jev_skip_reasons(result.reason or "disabled")
    response = result.response
    if not isinstance(response, SystemOneResponse):
        return [], jev_skip_reasons("incomplete")
    return jev_reasons_from_answers(response.answers, floor=floor), []


__all__ = [
    "RISK_PACK_ID",
    "evaluate_jev_risk",
    "jev_reasons_from_answers",
]
