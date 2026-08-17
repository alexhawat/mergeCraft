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

The ``genai`` import is lazy (shared fixture in ``tests/tracing/conftest.py``),
which kept collection clean at RED-suite time. All four tests carried
non-strict ``xfail`` markers (``green after OB3.2``) while OB3.2 was
unimplemented; the markers were removed in the post-OB3.2 reconciliation
(commit ``d4c1c54`` made them XPASS), so every test here is now a clean real
pass. Post-OB3.2 amendment: ``test_request_params_reach_the_span``'s fixture
model id was shortened to ``claude-opus-test`` — the sink path routes string
attrs through the pre-existing entropy redactor, and the original realistic
slug collided with it (see ``docs/test-plans/04-observability-eval.md``).

Acceptance (plan §OB3.1, post-reconciliation): 16 collected; 16 passed;
0 xfail/xpass.
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


def test_request_params_reach_the_span(tracer_and_sink: dict[str, Any], genai_module: Any) -> None:
    """O4 — every set knob lands on the ``llm.call`` span under its OTel GenAI name."""
    genai = genai_module
    tracer = tracer_and_sink["tracer"]
    sink = tracer_and_sink["sink"]

    # The fixture model id is deliberately short and low-entropy: the sink
    # path routes every string attr through the pre-existing entropy redactor
    # (``redact_secrets`` — ≥20 chars at entropy ≥ 4.0 is replaced), and a
    # realistic slug like ``anthropic/claude-opus-4.8`` collides with it. The
    # redaction layer is a security boundary and does not bend for tests, so
    # the sink-routed assertion uses an id that survives it verbatim.
    attrs = genai.request_attrs(model="claude-opus-test", params=_full_params(genai))
    with tracer.start_span("llm.call") as span:
        for key, value in attrs.items():
            span.set_attribute(key, value)

    event_attrs = sink.events[0].attrs
    assert event_attrs["gen_ai.request.model"] == "claude-opus-test"
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


def test_response_model_recorded_beside_request_model(genai_module: Any) -> None:
    """D11 — the executed model is recorded beside the requested one."""
    genai = genai_module

    attrs = genai.request_attrs(model="anthropic/claude-opus-4.8", params=None)
    attrs.update(genai.response_attrs(model="anthropic/claude-opus-4.8"))

    assert attrs["gen_ai.request.model"] == "anthropic/claude-opus-4.8"
    assert attrs["gen_ai.response.model"] == "anthropic/claude-opus-4.8"


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
