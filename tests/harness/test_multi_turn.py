"""RH4 — multi-turn fixture matching."""

from __future__ import annotations

import pytest

from tests.harness._helpers import snapshot
from tests.support.provider_harness.matcher import NoFixtureMatch, match_fixture
from tests.support.provider_harness.pytest_plugin import load_harness_fixtures
from tests.support.provider_harness.schema import FixtureSpec, MatchSpec, ResponseSpec


def test_turn_index_and_tool_result_select_next_fixture() -> None:
    fixtures = load_harness_fixtures("no-findings", "multi-turn-tool-result")
    matched = match_fixture(
        snapshot(turn_index=1, has_tool_results=True, tool_result_content="analyzer output"),
        fixtures,
        strict=True,
    )
    assert matched.name == "multi-turn-tool-result"


def test_tool_call_id_disambiguates_repeated_turns() -> None:
    fixtures = [
        FixtureSpec(
            name="turn-a",
            match=MatchSpec(provider="default", model="dummy", turn_index=1, tool_call_id="call-a"),
            response=ResponseSpec(body={"id": "a", "choices": []}),
        ),
        FixtureSpec(
            name="turn-b",
            match=MatchSpec(provider="default", model="dummy", turn_index=1, tool_call_id="call-b"),
            response=ResponseSpec(body={"id": "b", "choices": []}),
        ),
    ]
    assert match_fixture(snapshot(turn_index=1, tool_call_id="call-b"), fixtures).name == "turn-b"


def test_tool_result_content_can_be_a_match_guard() -> None:
    fixtures = load_harness_fixtures("multi-turn-tool-result")
    matched = match_fixture(
        snapshot(turn_index=1, has_tool_results=True, tool_result_content="analyzer output"),
        fixtures,
        strict=True,
    )
    assert matched.name == "multi-turn-tool-result"


def test_turn_mismatch_reports_expected_and_observed_state() -> None:
    fixtures = load_harness_fixtures("multi-turn-tool-result")
    with pytest.raises(NoFixtureMatch) as exc:
        match_fixture(snapshot(turn_index=0, has_tool_results=False), fixtures, strict=True)
    reason = str(exc.value.candidate_reasons.get("multi-turn-tool-result", ""))
    assert "turn_index" in reason or "has_tool_results" in reason or "tool_result_content" in reason
