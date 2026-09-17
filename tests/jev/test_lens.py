"""J1.8 — lens pack tracks the live catalog; fallback when disabled (G13)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.jev.support import (
    TRANSPORT_DIR,
    assert_honest_skip,
    import_jev,
    loguru_lines,
    skipping_jev_client,
)


def _questions() -> Any:
    return import_jev("questions")


def test_lens_pack_is_derived_from_live_catalog_not_a_copy() -> None:
    from mergecraft.agents.lenses._definitions import LENS_DEFINITIONS

    pack = _questions().lens_pack()
    assert pack.pack_id == "lens/v1"
    assert frozenset(pack.lens_ids) == frozenset(LENS_DEFINITIONS)
    assert pack.source_catalog is LENS_DEFINITIONS or pack.reads_live_catalog is True


def test_adding_a_catalog_lens_is_visible_without_a_hand_copy() -> None:
    from mergecraft.agents.lenses._definitions import LENS_DEFINITIONS

    pack = _questions().lens_pack()
    assert "privilege-drop-ordering" in pack.lens_ids
    assert "copy-vs-code" in pack.lens_ids
    assert "data-integrity" in pack.lens_ids
    assert len(pack.lens_ids) == len(LENS_DEFINITIONS)


async def test_lens_selection_uses_recorded_transport() -> None:
    from mergecraft.agents.lenses._definitions import LENS_DEFINITIONS

    client_mod = import_jev("client")
    transport = client_mod.RecordedTransport.from_fixture(
        TRANSPORT_DIR / "lens_privilege_drop.json"
    )
    selected = await import_jev("questions").select_lenses(
        state={"diff": "setpriv --reuid without HOME"},
        client=client_mod.AsyncJevClient(api_key="mc-test-jev-key", transport=transport),
    )
    assert "privilege-drop-ordering" in selected.lens_ids
    assert set(selected.lens_ids) <= set(LENS_DEFINITIONS)
    assert selected.pack_id == "lens/v1"


def test_disabled_or_low_confidence_falls_back_to_trigger_matching() -> None:
    questions = _questions()
    fallback = questions.select_lenses_or_fallback(
        enabled=False,
        trigger_ids=("security",),
    )
    assert fallback.source == "triggers"
    assert fallback.lens_ids == ("security",)
    low = questions.select_lenses_or_fallback(
        enabled=True,
        confidence=0.4,
        trigger_ids=("security",),
    )
    assert low.source == "triggers"
    assert low.lens_ids == ("security",)


async def test_select_lenses_skip_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    """F-SKIP-RAISES: ``select_lenses`` must not raise ``JevError`` when the client skips."""
    types = import_jev("types")
    client, transport = skipping_jev_client(monkeypatch, "lens_privilege_drop.json")
    with loguru_lines() as logs:
        try:
            selected = await _questions().select_lenses(
                state={"diff": "setpriv --reuid without HOME"},
                client=client,
            )
        except types.JevError as exc:
            pytest.fail(f"select_lenses must not raise JevError on skip (D4); code={exc.code}")
    assert transport.calls == 0
    skipped = getattr(selected, "skipped", False)
    if skipped:
        assert_honest_skip(selected, logs, reason="credential_absent")
        return
    assert selected.source == "triggers" or selected.lens_ids == ()
    assert any("credential_absent" in line for line in logs) or skipped
