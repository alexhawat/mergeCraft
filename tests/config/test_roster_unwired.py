"""Unit tests for roster ↔ workflow unwired-model scanning."""

from __future__ import annotations

import pytest

from mergecraft.config.agent_roster import Roster, RosterEntry, load_roster
from mergecraft.config.roster_unwired import collect_unwired_roster_models, iter_roster_model_slots


def test_iter_roster_model_slots_yields_dense_slots() -> None:
    roster = Roster(
        entries=(
            RosterEntry(
                name="reviewer",
                model_chain=("anthropic/claude-sonnet", "openai/gpt-5.3-codex"),
            ),
        )
    )
    assert iter_roster_model_slots(roster) == (
        ("reviewer", "p0", "anthropic/claude-sonnet"),
        ("reviewer", "p1", "openai/gpt-5.3-codex"),
    )


def test_collect_unwired_roster_models_flags_missing_provider() -> None:
    roster = load_roster(
        {
            "agents": {
                "reviewer": {
                    "modelChain": ["nous/tencent/hy3"],
                },
            },
        }
    )
    unwired = collect_unwired_roster_models(roster=roster, wired_providers=frozenset({"anthropic"}))
    assert unwired == [("reviewer", "p0", "nous/tencent/hy3", "nous")]


def test_collect_unwired_roster_models_ignores_wired_provider() -> None:
    roster = load_roster(
        {
            "agents": {
                "reviewer": {
                    "modelChain": ["anthropic/claude-sonnet"],
                },
            },
        }
    )
    unwired = collect_unwired_roster_models(roster=roster, wired_providers=frozenset({"anthropic"}))
    assert unwired == []


def test_collect_unwired_roster_models_raises_on_invalid_slug() -> None:
    roster = load_roster(
        {
            "agents": {
                "reviewer": {
                    "modelChain": ["not-a-valid-model-slug"],
                },
            },
        }
    )
    with pytest.raises(ValueError, match=r"not-a-valid-model-slug|invalid|model"):
        collect_unwired_roster_models(roster=roster, wired_providers=frozenset({"anthropic"}))
