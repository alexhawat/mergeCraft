"""LLM input/output message capture — OB3.1 RED suite (part 2 of 4).

Wave plan: ``.ignorelocal/waves/04-observability-eval-wave-plan.md`` (PR OB3,
sub-wave OB3.1, finding O5). Test-plan doc: ``docs/test-plans/04-observability-eval.md``.

Pins the OB3.2 builders ``input_messages_attrs`` / ``output_messages_attrs`` in
``mergecraft.tracing.genai`` (new): messages serialize to the OTel GenAI attrs
``gen_ai.input.messages`` / ``gen_ai.output.messages``, with ALL body text
routed through OB2's ``capture_text`` (convention 4 — no second policy
mechanism) so the D6 level governs bodies and the D8 hash + counts always
ship above ``off``. Message count rides alongside as
``gen_ai.input.messages.count`` / ``gen_ai.output.messages.count``.

Harness coverage is genuinely partial (plan §OB3.1 note): mergeCraft sees
message payloads only on the OpenCode HTTP path and in
``agents/_stream_consumer.py`` — never for the CLI harnesses. These tests pin
the pure builders only; which harnesses can populate them is OB3.2 File 2 and
is intentionally not asserted here.

The ``genai`` import is lazy (shared fixture in ``tests/tracing/conftest.py``),
which kept collection clean at RED-suite time; all four tests carried
non-strict ``xfail`` markers (``green after OB3.2``) until the post-OB3.2
reconciliation removed them (commit ``d4c1c54`` made them XPASS), so all four
are now clean real passes.
"""

from __future__ import annotations

from typing import Any

from mergecraft.tracing.content import ContentCapture

_INPUT = "gen_ai.input.messages"
_OUTPUT = "gen_ai.output.messages"


def test_input_messages_captured_under_policy(genai_module: Any) -> None:
    """O5 — input messages ship under the content policy, bodies through the secret matcher."""
    genai = genai_module
    messages = [
        {"role": "system", "content": "You review code."},
        {
            "role": "user",
            "content": "Review this diff; token ghp_abcdefghijklmnop1234567890ABCDEFGHIJ",
        },
    ]

    attrs = genai.input_messages_attrs(messages, policy=ContentCapture.REDACTED)

    assert _INPUT in attrs, "redacted level ships the serialized body"
    assert "ghp_abcdefghijklmnop" not in attrs[_INPUT], (
        "message bodies route through OB2 capture_text — the secret matcher applies"
    )
    assert attrs[f"{_INPUT}.sha256"], "D8 hash of the original payload"
    assert attrs[f"{_INPUT}.chars"] > 0
    assert attrs[f"{_INPUT}.bytes"] > 0


def test_output_messages_captured_under_policy(genai_module: Any) -> None:
    """O5 — output (completion) messages ship under the content policy too."""
    genai = genai_module
    messages = [
        {"role": "assistant", "content": "I found two blockers in src/main.py."},
    ]

    attrs = genai.output_messages_attrs(messages, policy=ContentCapture.REDACTED)

    assert _OUTPUT in attrs
    assert "two blockers" in attrs[_OUTPUT]
    assert attrs[f"{_OUTPUT}.sha256"]
    assert attrs[f"{_OUTPUT}.chars"] > 0


def test_message_count_recorded(genai_module: Any) -> None:
    """The message count rides alongside the body/hash on both directions."""
    genai = genai_module
    three = [
        {"role": "system", "content": "a"},
        {"role": "user", "content": "b"},
        {"role": "user", "content": "c"},
    ]

    inbound = genai.input_messages_attrs(three, policy=ContentCapture.REDACTED)
    outbound = genai.output_messages_attrs(three[-1:], policy=ContentCapture.REDACTED)

    assert inbound[f"{_INPUT}.count"] == 3
    assert outbound[f"{_OUTPUT}.count"] == 1


def test_bodies_absent_at_metadata_level(genai_module: Any) -> None:
    """At ``metadata`` the bodies stay home — counts, sizes and the D8 hash remain."""
    genai = genai_module
    messages = [{"role": "user", "content": "a body that must not ship at metadata"}]

    for builder, prefix in (
        (genai.input_messages_attrs, _INPUT),
        (genai.output_messages_attrs, _OUTPUT),
    ):
        attrs = builder(messages, policy=ContentCapture.METADATA)
        assert prefix not in attrs, f"{prefix} body must be absent at metadata"
        assert f"{prefix}.truncated" not in attrs, "no body means no truncation marker"
        assert attrs[f"{prefix}.sha256"]
        assert attrs[f"{prefix}.chars"] > 0
        assert attrs[f"{prefix}.bytes"] > 0
        assert attrs[f"{prefix}.count"] == 1
