"""J6 F-PACKS-DEAD — ``JevSettings.packs`` has an apply site; a disabled pack is not dispatched."""

from __future__ import annotations

from typing import Any

import pytest

from tests.jev.support import (
    PINNED_MODEL,
    TEST_API_KEY,
    TRANSPORT_DIR,
    import_jev,
    loguru_lines,
    make_agent_finding,
    make_hunk_unit,
)


def _client_mod() -> Any:
    return import_jev("client")


def _settings_with_pack(pack_id: str, *, enabled_pack: bool) -> Any:
    from mergecraft.config.settings import JevSettings, default_settings

    packs = {key: True for key in default_settings().jev.packs}
    packs[pack_id] = enabled_pack
    return JevSettings(enabled=True, model=PINNED_MODEL, packs=packs)


def _client_for(settings: Any, fixture_name: str) -> tuple[Any, Any]:
    module = _client_mod()
    transport = module.RecordedTransport.from_fixture(TRANSPORT_DIR / fixture_name)
    client = module.AsyncJevClient(api_key=TEST_API_KEY, transport=transport, settings=settings)
    return client, transport


def _patch_default_jev(monkeypatch: pytest.MonkeyPatch, settings: Any) -> None:
    from mergecraft.config.settings import default_settings

    base = default_settings()
    repo = base.model_copy(update={"jev": settings})
    monkeypatch.setattr("mergecraft.config.settings.default_settings", lambda: repo)


async def test_client_does_not_dispatch_a_disabled_pack(monkeypatch: pytest.MonkeyPatch) -> None:
    """F-PACKS-DEAD apply site: toggling ``unit/v1`` off skips that pack's call."""
    settings = _settings_with_pack("unit/v1", enabled_pack=False)
    _patch_default_jev(monkeypatch, settings)
    client, transport = _client_for(settings, "unit_happy.json")
    result = await client.call(state={"hunk": "x"}, pack_id="unit/v1", unit_id="u")
    assert result.skipped is True
    assert result.available is False
    assert transport.calls == 0


async def test_unit_battery_skips_disabled_unit_pack(monkeypatch: pytest.MonkeyPatch) -> None:
    """F-PACKS-DEAD: ``unit_battery`` does not ask a disabled ``unit/v1`` pack."""
    settings = _settings_with_pack("unit/v1", enabled_pack=False)
    _patch_default_jev(monkeypatch, settings)
    client, transport = _client_for(settings, "unit_happy.json")
    types = import_jev("types")
    with loguru_lines() as _logs:
        try:
            await import_jev("policy").unit_battery(
                make_hunk_unit(),
                client=client,
                trust_tier="trusted",
            )
        except types.JevError as exc:
            pytest.fail(f"disabled pack must skip, not raise; code={exc.code}")
    assert transport.calls == 0


async def test_judge_skips_disabled_evidence_pack(monkeypatch: pytest.MonkeyPatch) -> None:
    """F-PACKS-DEAD: evidence battery is not dispatched when ``evidence/v1`` is off."""
    settings = _settings_with_pack("evidence/v1", enabled_pack=False)
    _patch_default_jev(monkeypatch, settings)
    client, transport = _client_for(settings, "evidence_says_nothing.json")
    types = import_jev("types")
    finding = make_agent_finding(
        message="Untrusted input is executed via shell=True",
        evidence=["def add(left, right): return left + right"],
    )
    try:
        await import_jev("judge").judge_finding_evidence(
            finding,
            cited_section=finding.evidence[0],
            client=client,
        )
    except types.JevError as exc:
        pytest.fail(f"disabled pack must skip, not raise; code={exc.code}")
    assert transport.calls == 0


async def test_select_lenses_skips_disabled_lens_pack(monkeypatch: pytest.MonkeyPatch) -> None:
    """F-PACKS-DEAD: ``lens/v1`` off means ``select_lenses`` does not dispatch."""
    settings = _settings_with_pack("lens/v1", enabled_pack=False)
    _patch_default_jev(monkeypatch, settings)
    client, transport = _client_for(settings, "lens_privilege_drop.json")
    types = import_jev("types")
    try:
        await import_jev("questions").select_lenses(
            state={"diff": "setpriv --reuid without HOME"},
            client=client,
        )
    except types.JevError as exc:
        pytest.fail(f"disabled pack must skip, not raise; code={exc.code}")
    assert transport.calls == 0
