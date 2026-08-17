"""Model parameters on the span — OB3.1 RED suite (part 1 of 4).

Wave plan: ``.ignorelocal/waves/04-observability-eval-wave-plan.md`` (PR OB3,
sub-wave OB3.1, finding O4). Test-plan doc: ``docs/test-plans/04-observability-eval.md``.

Pins the OB3.2 target API in ``mergecraft.tracing.genai`` (new): a frozen
``ModelParams`` value type and the ``request_attrs`` / ``response_attrs``
builders. Standard knobs use the OTel GenAI names (``gen_ai.request.model``,
``gen_ai.request.temperature``, ``gen_ai.request.top_p``,
``gen_ai.request.top_k``, ``gen_ai.request.max_tokens``,
``gen_ai.request.stop_sequences``, ``gen_ai.request.seed``,
``gen_ai.response.model``); knobs with no stable OTel GenAI convention
(``reasoning_effort``, ``thinking_budget``) go under ``mergecraft.*`` —
convention 6 forbids smuggling mergeCraft-specific additions into ``gen_ai.*``.

D11: both the requested and the executed model are recorded; after a fallback
they differ, and the mismatch is the visible signal.

Harness coverage is genuinely partial (plan §OB3.1 note): mergeCraft sees the
model payload only on the OpenCode HTTP path and in
``agents/_stream_consumer.py`` — never for the CLI harnesses. These tests pin
the pure builders only; which harnesses can populate them is OB3.2 File 2 and
is intentionally not asserted here.

The ``genai`` import is lazy (shared fixture in ``tests/tracing/conftest.py``)
so collection stays clean. All four tests carry non-strict ``xfail`` markers
(``green after OB3.2`` — the repo pins ``xfail_strict = true``, so
``strict=False`` is explicit) and are expected RED until OB3.2 lands.

Acceptance (plan §OB3.1, shared with the sibling modules): 16 collected;
1 passes (the ``_tool_attrs`` regression pin); 15 RED (xfail).
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture
def tracer_and_sink() -> dict[str, Any]:
    """A real ``MemorySink`` wired to a ``Tracer`` with explicit correlation ids."""
    from mergecraft.tracing import MemorySink, Tracer

    sink = MemorySink()
    tracer = Tracer(
        sink=sink,
        session_id="session-ob3",
        run_id="run-ob3",
        trace_id="trace-ob3",
    )
    return {"sink": sink, "tracer": tracer}


def _full_params(genai: Any) -> Any:
    return genai.ModelParams(
        temperature=0.2,
        top_p=0.9,
        top_k=40,
        max_tokens=1024,
        stop=["END"],
        seed=42,
        reasoning_effort="high",
        thinking_budget=2048,
    )


@pytest.mark.xfail(reason="green after OB3.2: ModelParams + request_attrs", strict=False)
def test_request_params_reach_the_span(tracer_and_sink: dict[str, Any], genai_module: Any) -> None:
    """O4 — every set knob lands on the ``llm.call`` span under its OTel GenAI name."""
    genai = genai_module
    tracer = tracer_and_sink["tracer"]
    sink = tracer_and_sink["sink"]

    attrs = genai.request_attrs(model="anthropic/claude-opus-4.8", params=_full_params(genai))
    with tracer.start_span("llm.call") as span:
        for key, value in attrs.items():
            span.set_attribute(key, value)

    event_attrs = sink.events[0].attrs
    assert event_attrs["gen_ai.request.model"] == "anthropic/claude-opus-4.8"
    assert event_attrs["gen_ai.request.temperature"] == 0.2
    assert event_attrs["gen_ai.request.top_p"] == 0.9
    assert event_attrs["gen_ai.request.top_k"] == 40
    assert event_attrs["gen_ai.request.max_tokens"] == 1024
    assert event_attrs["gen_ai.request.stop_sequences"] == ["END"]
    assert event_attrs["gen_ai.request.seed"] == 42
    # No stable OTel GenAI name exists for these two — convention 6 puts them
    # under mergecraft.*, never smuggled into gen_ai.*.
    assert event_attrs["mergecraft.reasoning_effort"] == "high"
    assert event_attrs["mergecraft.thinking_budget"] == 2048


@pytest.mark.xfail(reason="green after OB3.2: unset knobs omitted", strict=False)
def test_unset_knob_is_omitted_not_zeroed(genai_module: Any) -> None:
    """An absent parameter must not become a misleading ``0`` on the span."""
    genai = genai_module

    attrs = genai.request_attrs(model="anthropic/claude-opus-4.8", params=genai.ModelParams())

    assert attrs["gen_ai.request.model"] == "anthropic/claude-opus-4.8"
    for key in (
        "gen_ai.request.temperature",
        "gen_ai.request.top_p",
        "gen_ai.request.top_k",
        "gen_ai.request.max_tokens",
        "gen_ai.request.stop_sequences",
        "gen_ai.request.seed",
        "mergecraft.reasoning_effort",
        "mergecraft.thinking_budget",
    ):
        assert key not in attrs, f"unset knob must be omitted, not zeroed: {key}"


@pytest.mark.xfail(reason="green after OB3.2: response_attrs (D11)", strict=False)
def test_response_model_recorded_beside_request_model(genai_module: Any) -> None:
    """D11 — the executed model is recorded beside the requested one."""
    genai = genai_module

    attrs = genai.request_attrs(model="anthropic/claude-opus-4.8", params=None)
    attrs.update(genai.response_attrs(model="anthropic/claude-opus-4.8"))

    assert attrs["gen_ai.request.model"] == "anthropic/claude-opus-4.8"
    assert attrs["gen_ai.response.model"] == "anthropic/claude-opus-4.8"


@pytest.mark.xfail(reason="green after OB3.2: fallback visible (D11)", strict=False)
def test_fallback_is_visible_as_a_model_mismatch(genai_module: Any) -> None:
    """D11 — after a fallback, request.model and response.model differ and BOTH are present.

    Recording only one side would make the fallback invisible (response only)
    or indistinguishable from a config change (request only).
    """
    genai = genai_module

    attrs = genai.request_attrs(model="anthropic/claude-opus-4.8", params=None)
    attrs.update(genai.response_attrs(model="anthropic/claude-sonnet-5"))

    assert attrs["gen_ai.request.model"] == "anthropic/claude-opus-4.8"
    assert attrs["gen_ai.response.model"] == "anthropic/claude-sonnet-5"
    assert attrs["gen_ai.request.model"] != attrs["gen_ai.response.model"], (
        "the fallback must be visible as a request/response model mismatch"
    )
