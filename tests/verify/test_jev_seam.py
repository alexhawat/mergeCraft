"""The verify → Jev seam: criteria and repro claims are judged, never counted.

This module pins the seam's public surface because the plan names the seam but
not its symbol: ``mergecraft.verify.jev_seam`` exposes ``judge_criteria`` and
``judge_repro_claim``. Every test here is RED until the driver/seam wave builds
that module — see ``docs/test-plans/30-verification-evals-receipts.md``.

The property under test in the last section is the "Jev scores, Python counts"
decision: the seam asks Jev one qualitative question per criterion and maps the
answer in Python. No rate, count, or aggregate may be requested from or returned
by Jev.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path
from typing import Any, get_origin

import pytest

from mergecraft.jev.client import AsyncJevClient, RecordedTransport
from mergecraft.jev.types import JevCallResult, parse_system_one_response
from tests.jev.support import FORBIDDEN_COUNT_NAMES
from tests.verify.support import import_verify, require_symbol

pytestmark = pytest.mark.xfail(
    reason="green after R3: the verify → Jev criterion/repro seam is not built yet",
    strict=False,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "transport"
_TEST_API_KEY = "mc-test-verify-seam"
_COUNTING_SYMBOL = re.compile(r"rate|count|aggregate|percent|average|mean|total|sum", re.IGNORECASE)


def _seam() -> Any:
    """Import ``mergecraft.verify.jev_seam`` or fail with a named deliverable."""
    return import_verify("jev_seam")


def _client(fixture: str) -> tuple[AsyncJevClient, RecordedTransport]:
    transport = RecordedTransport.from_fixture(_FIXTURES / fixture)
    return AsyncJevClient(api_key=_TEST_API_KEY, transport=transport), transport


def _satisfied_result() -> JevCallResult:
    response = parse_system_one_response(
        {
            "model": "jev-1.13.0",
            "answers": {
                "satisfied": {"noul": 0.9},
                "reproduced": {"noul": 0.9},
            },
        }
    )
    return JevCallResult(skipped=False, available=True, model=response.model, response=response)


class _RecordingClient:
    """Duck-typed Jev client: records each call, replays one canned result."""

    def __init__(self, result: JevCallResult) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def availability_skip(self, *, pack_id: str | None = None) -> JevCallResult | None:
        del pack_id
        return None

    async def call(self, **kwargs: Any) -> JevCallResult:
        self.calls.append(kwargs)
        return self.result


def _collect_names(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            found.add(str(key).lower())
            found |= _collect_names(item)
    elif isinstance(value, list | tuple):
        for item in value:
            found |= _collect_names(item)
    return found


def test_seam_module_exposes_async_criterion_and_repro_judges() -> None:
    seam = _seam()
    assert inspect.iscoroutinefunction(require_symbol(seam, "judge_criteria"))
    assert inspect.iscoroutinefunction(require_symbol(seam, "judge_repro_claim"))


async def test_judge_criteria_returns_one_judgment_per_criterion() -> None:
    seam = _seam()
    client, transport = _client("criterion_satisfied.json")
    judgments = await seam.judge_criteria(
        ["Clear removes the image", "Undo restores it"],
        page_text="image removed",
        client=client,
    )
    assert [judgment.criterion for judgment in judgments] == [
        "Clear removes the image",
        "Undo restores it",
    ]
    assert [judgment.verdict for judgment in judgments] == ["pass", "pass"]
    assert transport.calls == 2


async def test_judge_criteria_asks_jev_once_per_criterion() -> None:
    """One qualitative call per criterion — never one call asked to aggregate."""
    seam = _seam()
    client, transport = _client("criterion_satisfied.json")
    judgments = await seam.judge_criteria(["a", "b", "c"], page_text="page", client=client)
    assert len(judgments) == 3
    assert transport.calls == 3


async def test_judge_criteria_below_floor_is_fail() -> None:
    seam = _seam()
    client, _ = _client("criterion_unsatisfied.json")
    judgments = await seam.judge_criteria(["criterion"], page_text="page", client=client)
    assert [judgment.verdict for judgment in judgments] == ["fail"]


async def test_judge_criteria_empty_page_is_unverified_without_dispatching() -> None:
    """Python decides "no page ⇒ unverified"; Jev is not asked at all."""
    seam = _seam()
    recording = _RecordingClient(_satisfied_result())
    judgments = await seam.judge_criteria(["criterion"], page_text="   ", client=recording)
    assert [judgment.verdict for judgment in judgments] == ["unverified"]
    assert recording.calls == []


async def test_judge_criteria_skip_is_unverified_with_named_reason() -> None:
    """An honest Jev skip is surfaced, never rendered as a judgment."""
    seam = _seam()
    skip = JevCallResult(skipped=True, available=False, reason="credential_absent")
    recording = _RecordingClient(skip)
    judgments = await seam.judge_criteria(["criterion"], page_text="page", client=recording)
    assert [judgment.verdict for judgment in judgments] == ["unverified"]
    assert "credential_absent" in judgments[0].reason


async def test_judge_repro_claim_returns_reproduced_verdict() -> None:
    seam = _seam()
    client, transport = _client("repro_reproduced.json")
    judgment = await seam.judge_repro_claim(
        "clicking Clear leaves the image",
        page_text="image removed",
        client=client,
    )
    assert judgment.claim == "clicking Clear leaves the image"
    assert judgment.verdict == "reproduced"
    assert transport.calls == 1


async def test_judge_repro_claim_empty_page_is_unverified() -> None:
    seam = _seam()
    recording = _RecordingClient(_satisfied_result())
    judgment = await seam.judge_repro_claim("claim", page_text="", client=recording)
    assert judgment.verdict == "unverified"
    assert recording.calls == []


def test_judgment_models_carry_no_numeric_rate_or_count() -> None:
    """A judgment is categorical: no float/int field may appear on it."""
    seam = _seam()
    for model_name in ("CriterionJudgment", "ReproJudgment"):
        model = require_symbol(seam, model_name)
        for field_name, field in model.model_fields.items():
            annotation = field.annotation
            assert annotation not in (int, float), field_name
            assert get_origin(annotation) not in (int, float), field_name


def test_seam_module_exposes_no_counting_symbol() -> None:
    """No helper may compute a rate, count, or aggregate in the seam."""
    seam = _seam()
    offending = sorted(
        name
        for name in dir(seam)
        if not name.startswith("_") and _COUNTING_SYMBOL.search(name) is not None
    )
    assert offending == []


async def test_seam_never_asks_jev_to_count_or_aggregate() -> None:
    """The state and questions sent to Jev name no count or rate."""
    seam = _seam()
    recording = _RecordingClient(_satisfied_result())
    await seam.judge_criteria(["criterion"], page_text="page", client=recording)
    assert recording.calls
    sent = _collect_names(recording.calls)
    assert not (sent & FORBIDDEN_COUNT_NAMES)
