"""The verify → Jev seam: Jev scores criteria and repro claims; Python counts.

Behaviour verification produces observations, not verdicts. Two questions need a
judge: does the observed page satisfy an acceptance criterion, and does it
reproduce a claimed defect. Each is asked of Jev as **one** ``system_one`` call
per criterion or claim — never one call asked to aggregate — and the returned
``noul`` probability is mapped to a categorical verdict in Python at the
``NOUL_ACT_FLOOR`` (0.5). No rate, count, or aggregate crosses this seam in
either direction.

An absent observation (a blank page) is ``unverified`` **without dispatching**:
Python decides, so Jev is never asked to reason about a page nobody observed. An
honest Jev skip is ``unverified`` carrying the skip token, so a judgment that
did not happen is never rendered as one that found nothing.

Exports:
    CRITERION_PACK_ID: Versioned criterion question pack id.
    REPRO_PACK_ID: Versioned repro question pack id.
    CriterionJudgment: Categorical criterion verdict plus a named reason.
    ReproJudgment: Categorical repro verdict plus a named reason.
    judge_criteria: One judgment per criterion, one Jev call each.
    judge_repro_claim: One judgment for a reproduce claim.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

from mergecraft.jev.architecture import build_system_one_questions, route_noul
from mergecraft.jev.questions import criterion_pack, repro_pack
from mergecraft.jev.types import (
    CRITERION_ANSWER_NAME,
    CRITERION_PACK_ID,
    NOUL_ACT_FLOOR,
    REPRO_ANSWER_NAME,
    REPRO_PACK_ID,
    JevCallResult,
    NoulAnswer,
    SystemOneResponse,
)

if TYPE_CHECKING:
    from mergecraft.jev.client import AsyncJevClient

_FLOOR: float = NOUL_ACT_FLOOR
_EMPTY_PAGE_REASON = "empty_page"
_MISSING_ANSWER_REASON = "missing_answer"
_UNAVAILABLE_REASON = "unavailable"


class CriterionJudgment(BaseModel):
    """One acceptance criterion's categorical verdict. Carries no rate or score."""

    model_config = ConfigDict(extra="forbid")

    criterion: str
    verdict: Literal["pass", "fail", "unverified"]
    reason: str = ""


class ReproJudgment(BaseModel):
    """One reproduce claim's categorical verdict. Carries no rate or score."""

    model_config = ConfigDict(extra="forbid")

    claim: str
    verdict: Literal["reproduced", "not_reproduced", "unverified"]
    reason: str = ""


async def judge_criteria(
    criteria: list[str],
    *,
    page_text: str,
    client: AsyncJevClient,
    trust_tier: str = "untrusted",
) -> list[CriterionJudgment]:
    """Judge each criterion against the observed page, one Jev call apiece.

    Args:
        criteria: Acceptance criteria, in report order.
        page_text: Text observed after navigation and any actions.
        client: Pinned Jev client (a recorded transport replays in CI).
        trust_tier: Tier of ``page_text``; defaults to ``untrusted`` so a caller
            that omits it keeps the prompt fence rather than silently losing it.

    Returns:
        list[CriterionJudgment]: One judgment per criterion, order preserved.
    """
    if not page_text.strip():
        return [_criterion_unverified(text, _EMPTY_PAGE_REASON) for text in criteria]
    judged: list[CriterionJudgment] = []
    for criterion in criteria:
        result = await client.call(
            state={"criterion": criterion, "page": page_text},
            pack_id=CRITERION_PACK_ID,
            unit_id=_unit_id("criterion", criterion),
            questions=build_system_one_questions(criterion_pack()),
            trust_tier=trust_tier,
        )
        judged.append(_criterion_judgment(criterion, result))
    return judged


async def judge_repro_claim(
    claim: str,
    *,
    page_text: str,
    client: AsyncJevClient,
    trust_tier: str = "untrusted",
) -> ReproJudgment:
    """Judge whether the observed page reproduces ``claim``.

    Args:
        claim: The reproduction claim to check.
        page_text: Text observed after navigation and any actions.
        client: Pinned Jev client (a recorded transport replays in CI).
        trust_tier: Tier of ``page_text``; defaults to ``untrusted``.

    Returns:
        ReproJudgment: ``reproduced``, ``not_reproduced``, or ``unverified``.
    """
    if not page_text.strip():
        return ReproJudgment(claim=claim, verdict="unverified", reason=_EMPTY_PAGE_REASON)
    result = await client.call(
        state={"claim": claim, "page": page_text},
        pack_id=REPRO_PACK_ID,
        unit_id=_unit_id("repro", claim),
        questions=build_system_one_questions(repro_pack()),
        trust_tier=trust_tier,
    )
    if result.skipped or result.response is None:
        return ReproJudgment(
            claim=claim,
            verdict="unverified",
            reason=result.reason or _UNAVAILABLE_REASON,
        )
    noul = _answer_noul(result.response, REPRO_ANSWER_NAME)
    if noul is None:
        return ReproJudgment(claim=claim, verdict="unverified", reason=_MISSING_ANSWER_REASON)
    verdict: Literal["reproduced", "not_reproduced"] = (
        "reproduced" if route_noul(noul=noul, floor=_FLOOR) else "not_reproduced"
    )
    return ReproJudgment(claim=claim, verdict=verdict)


def _criterion_judgment(criterion: str, result: JevCallResult) -> CriterionJudgment:
    if result.skipped or result.response is None:
        return _criterion_unverified(criterion, result.reason or _UNAVAILABLE_REASON)
    noul = _answer_noul(result.response, CRITERION_ANSWER_NAME)
    if noul is None:
        return _criterion_unverified(criterion, _MISSING_ANSWER_REASON)
    verdict: Literal["pass", "fail"] = "pass" if route_noul(noul=noul, floor=_FLOOR) else "fail"
    return CriterionJudgment(criterion=criterion, verdict=verdict)


def _criterion_unverified(criterion: str, reason: str) -> CriterionJudgment:
    return CriterionJudgment(criterion=criterion, verdict="unverified", reason=reason)


def _answer_noul(response: SystemOneResponse, name: str) -> float | None:
    answer = response.answers.get(name)
    if isinstance(answer, NoulAnswer):
        return float(answer.noul)
    return None


def _unit_id(prefix: str, text: str) -> str:
    digest = hashlib.sha256(text.encode()).hexdigest()[:16]
    return f"{prefix}:{digest}"


__all__ = [
    "CRITERION_PACK_ID",
    "REPRO_PACK_ID",
    "CriterionJudgment",
    "ReproJudgment",
    "judge_criteria",
    "judge_repro_claim",
]
