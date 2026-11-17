"""Jev risk/v1 mapping and client integration (#1489)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from mergecraft.classify.risk_jev import (
    evaluate_jev_risk,
    jev_reasons_from_answers,
    jev_skip_reasons,
    risk_pack_questions,
)
from mergecraft.jev.types import JevCallResult, NoulAnswer, SystemOneResponse


def test_risk_pack_questions_has_four_noul_items() -> None:
    questions = risk_pack_questions()
    assert len(questions) == 4
    assert all(q["type"] == "noul" for q in questions)


def test_jev_reasons_from_answers_respects_floor() -> None:
    answers = {"authz": NoulAnswer(noul=0.9)}
    reasons = jev_reasons_from_answers(answers, floor="low")
    assert len(reasons) == 1
    assert reasons[0].code == "jev.authz"
    assert reasons[0].lane == "high"


def test_jev_reasons_ignores_low_noul() -> None:
    answers = {"secrets": NoulAnswer(noul=0.2)}
    assert jev_reasons_from_answers(answers, floor="low") == []


def test_jev_skip_reasons_are_baseline_clean() -> None:
    reasons = jev_skip_reasons("credential_absent")
    assert reasons[0].code == "jev.credential.absent"
    assert reasons[0].lane == "low"


@dataclass
class _FakeJevClient:
    skip_reason: str | None = None
    response: SystemOneResponse | None = None
    skipped_call: bool = False
    call_reason: str | None = None

    def availability_skip(self, *, pack_id: str | None = None) -> JevCallResult | None:
        del pack_id
        if self.skip_reason is None:
            return None
        return JevCallResult(skipped=True, available=False, reason=self.skip_reason)

    async def call(self, **kwargs: Any) -> JevCallResult:
        del kwargs
        if self.skipped_call:
            return JevCallResult(
                skipped=True, available=False, reason=self.call_reason or "disabled"
            )
        return JevCallResult(
            skipped=False,
            available=True,
            response=self.response,
        )


@pytest.mark.asyncio
async def test_evaluate_jev_risk_when_availability_skips() -> None:
    client = _FakeJevClient(skip_reason="disabled")
    raised, record = await evaluate_jev_risk(client, diff_excerpt="+x", floor="low")
    assert raised == []
    assert record[0].code == "jev.disabled"


@pytest.mark.asyncio
async def test_evaluate_jev_risk_raises_lane_from_answers() -> None:
    client = _FakeJevClient(
        response=SystemOneResponse(
            model="test",
            answers={"flag_enabled": NoulAnswer(noul=0.95)},
        )
    )
    raised, record = await evaluate_jev_risk(client, diff_excerpt="+enabled: true", floor="low")
    assert record == []
    assert raised
    assert raised[0].code == "jev.flag_enabled"


@pytest.mark.asyncio
async def test_evaluate_jev_risk_call_skipped_records_reason() -> None:
    client = _FakeJevClient(skipped_call=True, call_reason="kill_switch")
    raised, record = await evaluate_jev_risk(client, diff_excerpt="+x", floor="medium")
    assert raised == []
    assert "kill_switch" in record[0].message


@pytest.mark.asyncio
async def test_evaluate_jev_risk_incomplete_response() -> None:
    client = _FakeJevClient(response=None, skipped_call=False)
    raised, record = await evaluate_jev_risk(client, diff_excerpt="+x", floor="low")
    assert raised == []
    assert record[0].code == "jev.incomplete"
