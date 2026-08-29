"""W1.1 — agent roster slot primitives (wave plan 11, green after W2)."""

from __future__ import annotations

import pytest

from tests.cli.support_agent_roster import MALFORMED_SLOTS, import_agent_roster


def test_assign_slot_on_empty_chain_at_p0_creates_one_long_chain() -> None:
    mod = import_agent_roster()
    chain, _msg = mod.assign_slot([], 0, "nous/tencent/hy3")
    assert chain == ["nous/tencent/hy3"]


def test_assign_slot_at_existing_index_replaces_preserves_other_slots() -> None:
    mod = import_agent_roster()
    chain = ["anthropic/claude-sonnet", "openai/gpt-5.3-codex"]
    updated, _msg = mod.assign_slot(chain, 1, "google/gemini-3.1-pro-preview")
    assert updated == ["anthropic/claude-sonnet", "google/gemini-3.1-pro-preview"]
    assert len(updated) == len(chain)


def test_assign_slot_beyond_end_names_next_assignable_slot() -> None:
    mod = import_agent_roster()
    chain = ["anthropic/claude-sonnet", "openai/gpt-5.3-codex"]
    with pytest.raises(Exception, match=r"p2|next assignable|slot"):
        mod.assign_slot(chain, 3, "nous/tencent/hy3")


def test_add_model_appends_to_tail() -> None:
    mod = import_agent_roster()
    chain = ["anthropic/claude-sonnet"]
    updated, already_present = mod.add_model(chain, "openai/gpt-5.3-codex")
    assert already_present is False
    assert updated == ["anthropic/claude-sonnet", "openai/gpt-5.3-codex"]


def test_add_model_duplicate_is_noop_with_message() -> None:
    mod = import_agent_roster()
    chain = ["anthropic/claude-sonnet", "openai/gpt-5.3-codex"]
    updated, already_present = mod.add_model(chain, "openai/gpt-5.3-codex")
    assert already_present is True
    assert updated == chain


@pytest.mark.parametrize("token", list(MALFORMED_SLOTS))
def test_parse_slot_rejects_malformed_tokens(token: str) -> None:
    mod = import_agent_roster()
    with pytest.raises(Exception, match=r"p\d|slot|invalid|malformed"):
        mod.parse_slot(token)


def test_parse_slot_accepts_p0() -> None:
    mod = import_agent_roster()
    assert mod.parse_slot("p0") == 0


def test_remove_slot_compacts_chain() -> None:
    mod = import_agent_roster()
    chain = ["anthropic/claude-sonnet", "openai/gpt-5.3-codex", "google/gemini-3.1-pro-preview"]
    assert mod.remove_slot(chain, 1) == [
        "anthropic/claude-sonnet",
        "google/gemini-3.1-pro-preview",
    ]


def test_remove_slot_refuses_empty_chain() -> None:
    mod = import_agent_roster()
    with pytest.raises(Exception, match=r"empty"):
        mod.remove_slot(["anthropic/claude-sonnet"], 0)


def test_write_roster_omits_after_when_unset() -> None:
    mod = import_agent_roster()
    raw: dict[str, object] = {
        "agents": {
            "reviewer": {
                "role": "reviewer",
                "after": "verifier",
                "modelChain": ["anthropic/claude-sonnet"],
            },
            "verifier": {
                "modelChain": ["openai/gpt-5.3-codex"],
            },
        },
    }
    roster = mod.load_roster(raw)
    reviewer = roster.entry_by_name()["reviewer"]
    cleared = mod.RosterEntry(
        name=reviewer.name,
        model_chain=reviewer.model_chain,
        role=reviewer.role,
        after=None,
    )
    mod.write_roster(raw, mod.Roster(entries=(cleared,)))
    reviewer_entry = raw["agents"]["reviewer"]
    assert isinstance(reviewer_entry, dict)
    assert "after" not in reviewer_entry
