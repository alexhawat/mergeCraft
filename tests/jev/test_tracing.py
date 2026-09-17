"""J1.2 — one GenAI span per call; Jev attrs stay under mergecraft.* (D9)."""

from __future__ import annotations

from typing import Any

from tests.jev.support import (
    J2_XFAIL,
    PINNED_MODEL,
    TRANSPORT_DIR,
    import_jev,
)


def _jev_spans(sink: Any) -> list[Any]:
    return [event for event in sink.events if "gen_ai.request.model" in event.attrs]


@J2_XFAIL
async def test_each_call_emits_one_genai_span(memory_tracer: dict[str, Any]) -> None:
    module = import_jev("client")
    transport = module.RecordedTransport.from_fixture(TRANSPORT_DIR / "unit_happy.json")
    client = module.AsyncJevClient(
        api_key="mc-test-jev-key",
        transport=transport,
        tracer=memory_tracer["tracer"],
    )
    await client.call(
        state={"hunk": "x"},
        pack_id="unit/v1",
        unit_id="unit-42",
        trust_tier="untrusted",
        ratchet_applied=True,
    )
    spans = _jev_spans(memory_tracer["sink"])
    assert len(spans) == 1
    attrs = spans[0].attrs
    assert attrs["gen_ai.request.model"] == PINNED_MODEL
    assert attrs["gen_ai.response.model"] == PINNED_MODEL
    assert attrs["gen_ai.usage.input_tokens"] == 120
    assert attrs["gen_ai.usage.output_tokens"] == 8


@J2_XFAIL
async def test_jev_specific_attrs_live_under_mergecraft_not_gen_ai(
    memory_tracer: dict[str, Any],
) -> None:
    module = import_jev("client")
    transport = module.RecordedTransport.from_fixture(TRANSPORT_DIR / "unit_happy.json")
    client = module.AsyncJevClient(
        api_key="mc-test-jev-key",
        transport=transport,
        tracer=memory_tracer["tracer"],
    )
    await client.call(
        state={"hunk": "x"},
        pack_id="unit/v1",
        unit_id="unit-42",
        trust_tier="untrusted",
        ratchet_applied=True,
    )
    attrs = _jev_spans(memory_tracer["sink"])[0].attrs
    assert attrs["mergecraft.jev.unit_id"] == "unit-42"
    assert attrs["mergecraft.jev.pack_id"] == "unit/v1"
    assert attrs["mergecraft.jev.trust_tier"] == "untrusted"
    assert attrs["mergecraft.jev.ratchet_applied"] is True
    for key in attrs:
        if key.startswith("gen_ai."):
            assert "unit_id" not in key
            assert "pack" not in key
            assert "trust" not in key
            assert "ratchet" not in key


@J2_XFAIL
async def test_unreported_usage_does_not_zero_gen_ai_usage_attrs(
    memory_tracer: dict[str, Any],
) -> None:
    module = import_jev("client")
    transport = module.RecordedTransport.from_fixture(TRANSPORT_DIR / "usage_tokens_none.json")
    client = module.AsyncJevClient(
        api_key="mc-test-jev-key",
        transport=transport,
        tracer=memory_tracer["tracer"],
    )
    await client.call(state={"hunk": "x"}, pack_id="unit/v1", unit_id="u")
    attrs = _jev_spans(memory_tracer["sink"])[0].attrs
    assert "gen_ai.usage.input_tokens" not in attrs
    assert "gen_ai.usage.output_tokens" not in attrs
    assert attrs.get("mergecraft.usage.unavailable") is True
