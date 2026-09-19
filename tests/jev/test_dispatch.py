"""J6 — ``unit_battery`` / ``dispatch_residual_units`` (F-UNBACKED-DISPATCH, F-SKIP-RAISES, F-DISPATCH-NO-SHADOW)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.jev.support import (
    TEST_API_KEY,
    TRANSPORT_DIR,
    assert_honest_skip,
    import_jev,
    loguru_lines,
    make_hunk_unit,
    skipping_jev_client,
)


def _policy() -> Any:
    return import_jev("policy")


def _client_mod() -> Any:
    return import_jev("client")


def _recorded_client(fixture_name: str = "unit_happy.json") -> Any:
    module = _client_mod()
    transport = module.RecordedTransport.from_fixture(TRANSPORT_DIR / fixture_name)
    return module.AsyncJevClient(api_key=TEST_API_KEY, transport=transport), transport


class _StateRecordingTransport:
    """Wrap a recorded transport so residual dispatch can show which hunk was asked."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.states: list[dict[str, Any]] = []

    async def system_one(
        self,
        *,
        state: dict[str, Any],
        questions: dict[str, Any],
        model: str,
    ) -> Any:
        self.states.append(state)
        return await self._inner.system_one(state=state, questions=questions, model=model)

    @property
    def calls(self) -> int:
        return int(self._inner.calls)

    @property
    def last_model(self) -> str | None:
        return self._inner.last_model


async def test_unit_battery_parses_recorded_unit_pack() -> None:
    """F-UNBACKED-DISPATCH: direct ``unit_battery`` behaviour on a residual hunk."""
    client, transport = _recorded_client()
    unit = make_hunk_unit(unit_id="hunk:residual", path="src/mergecraft/residual.py")
    assessment = await _policy().unit_battery(unit, client=client, trust_tier="trusted")
    assert assessment.unit_id == unit.unit_id
    assert assessment.choice == "defective"
    assert assessment.confidence == 0.92
    assert assessment.pack_id == "unit/v1"
    assert transport.calls == 1


async def test_unit_battery_skip_does_not_raise_jev_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """F-SKIP-RAISES / D4: a client skip stays a skip. Fails if raise-on-skip returns."""
    policy = _policy()
    types = import_jev("types")
    client, transport = skipping_jev_client(monkeypatch)
    unit = make_hunk_unit()
    with loguru_lines() as logs:
        try:
            result = await policy.unit_battery(unit, client=client, trust_tier="trusted")
        except types.JevError as exc:
            pytest.fail(f"unit_battery must not raise JevError on skip (D4); code={exc.code}")
    assert transport.calls == 0
    assert_honest_skip(result, logs, reason="credential_absent")


async def test_dispatch_residual_units_asks_residual_not_analyzer_flagged() -> None:
    """F-UNBACKED-DISPATCH: analyzer-flagged hunks are not re-asked; residual hunks are."""
    module = _client_mod()
    inner = module.RecordedTransport.from_fixture(TRANSPORT_DIR / "unit_happy.json")
    transport = _StateRecordingTransport(inner)
    client = module.AsyncJevClient(api_key=TEST_API_KEY, transport=transport)
    flagged = make_hunk_unit(
        path="src/mergecraft/flagged.py",
        unit_id="hunk:flagged",
        start_line=10,
    )
    residual = make_hunk_unit(
        path="src/mergecraft/residual.py",
        unit_id="hunk:residual",
        start_line=20,
    )
    findings = [{"path": flagged.path, "start_line": flagged.start_line}]
    predictions = await _policy().dispatch_residual_units(
        [flagged, residual],
        findings,
        client=client,
        trust_tier="trusted",
    )
    assert transport.calls == 1
    asked_ids = [str(state.get("unit_id")) for state in transport.states]
    assert residual.unit_id in asked_ids
    assert flagged.unit_id not in asked_ids
    assert [item.unit_id for item in predictions] == [residual.unit_id]


async def test_dispatch_residual_units_calls_record_jev_prediction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F-DISPATCH-NO-SHADOW: dispatch must call ``record_jev_prediction``. Guard-deletion."""
    policy = _policy()
    recorded: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def _spy(*args: Any, **kwargs: Any) -> Any:
        recorded.append((args, kwargs))
        return None

    monkeypatch.setattr(policy, "record_jev_prediction", _spy)
    client, _transport = _recorded_client()
    residual = make_hunk_unit(unit_id="hunk:shadow", path="src/mergecraft/residual.py")
    await policy.dispatch_residual_units(
        [residual],
        [],
        client=client,
        trust_tier="trusted",
    )
    assert recorded, "dispatch_residual_units must call record_jev_prediction"


async def test_dispatch_residual_units_skip_does_not_fail_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F-UNBACKED-DISPATCH / F-SKIP-RAISES: skip does not fail residual dispatch."""
    policy = _policy()
    types = import_jev("types")
    client, transport = skipping_jev_client(monkeypatch)
    residual = make_hunk_unit(unit_id="hunk:skip", path="src/mergecraft/residual.py")
    with loguru_lines() as logs:
        try:
            predictions = await policy.dispatch_residual_units(
                [residual],
                [],
                client=client,
                trust_tier="trusted",
            )
        except types.JevError as exc:
            pytest.fail(
                f"dispatch_residual_units must not raise JevError on skip (D4); code={exc.code}"
            )
    assert isinstance(predictions, list)
    assert transport.calls == 0
    if predictions:
        assert_honest_skip(predictions[0], logs, reason="credential_absent")
    else:
        assert any("credential_absent" in line for line in logs)
