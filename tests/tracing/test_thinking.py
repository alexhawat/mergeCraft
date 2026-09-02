"""Reasoning / thinking capture — OB3.1 RED suite (part 3 of 4).

Wave plan: ``.ignorelocal/waves/04-observability-eval-wave-plan.md`` (PR OB3,
sub-wave OB3.1, finding O6). Test-plan doc: ``docs/test-plans/04-observability-eval.md``.

Pins the OB3.2 builder ``thinking_attrs`` in ``mergecraft.tracing.genai``
(new). **D9 is the load-bearing decision: reasoning inherits the prompt gate,
never a looser one** — reasoning text routinely quotes the reviewed diff
verbatim and reasons about it, so it is the most sensitive body mergeCraft
handles. All reasoning text routes through OB2's ``capture_text`` under the
prefix ``mergecraft.thinking`` (no stable OTel GenAI reasoning convention
exists, and convention 6 keeps mergeCraft-specific additions out of
``gen_ai.*``); reasoning tokens ride as ``mergecraft.usage.reasoning_tokens``
for the same reason.

``test_provider_redacted_thinking_is_distinguishable_from_empty`` pins the
``provider_redacted`` flag: a provider-side redacted-thinking block must read
differently from a run that simply produced no reasoning.

Harness coverage is genuinely partial (plan §OB3.1 note): only harnesses that
expose reasoning (the OpenCode HTTP path / the stream consumer) can populate
this — these tests pin the pure builder, not harness wiring (OB3.2 File 2).

The ``genai`` import is lazy (shared fixture in ``tests/tracing/conftest.py``),
which kept collection clean at RED-suite time; all four tests carried
non-strict ``xfail`` markers (``green after OB3.2``) until the post-OB3.2
reconciliation removed them (commit ``d4c1c54`` made them XPASS), so all four
are now clean real passes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.tracing.content import ContentCapture, resolve_content_capture

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

_THINKING = "mergecraft.thinking"


def test_reasoning_text_captured_under_policy(genai_module: Any) -> None:
    """D9 — reasoning text ships under the SAME content policy as prompts.

    The body goes through the secret matcher at ``redacted`` and carries the
    D8 hash of the original text — exactly the prompt treatment.
    """
    genai = genai_module
    text = "The diff hardcodes ghp_abcdefghijklmnop1234567890ABCDEFGHIJ — flag it."

    attrs = genai.thinking_attrs(text, policy=ContentCapture.REDACTED)

    assert _THINKING in attrs
    assert "ghp_abcdefghijklmnop" not in attrs[_THINKING], (
        "reasoning inherits the prompt gate — the secret matcher applies"
    )
    assert attrs[f"{_THINKING}.sha256"]
    assert attrs[f"{_THINKING}.chars"] == len(text)


def test_reasoning_tokens_recorded(genai_module: Any) -> None:
    """The provider's reasoning-token count lands beside the body metadata."""
    genai = genai_module

    attrs = genai.thinking_attrs(
        "some reasoning", policy=ContentCapture.REDACTED, reasoning_tokens=512
    )

    assert attrs["mergecraft.usage.reasoning_tokens"] == 512


def test_provider_redacted_thinking_is_distinguishable_from_empty(genai_module: Any) -> None:
    """A provider-redacted thinking block must not read as 'no reasoning happened'."""
    genai = genai_module

    redacted = genai.thinking_attrs(None, policy=ContentCapture.REDACTED, provider_redacted=True)
    empty = genai.thinking_attrs("", policy=ContentCapture.REDACTED)

    assert redacted[f"{_THINKING}.provider_redacted"] is True
    assert empty.get(f"{_THINKING}.provider_redacted") in (None, False), (
        "an empty reasoning body must not carry the provider-redacted flag"
    )
    assert redacted.get(_THINKING) in (None, ""), "provider-redacted thinking has no body to ship"


def test_reasoning_never_bypasses_the_gate(monkeypatch: MonkeyPatch, genai_module: Any) -> None:
    """D9 — no configuration lets reasoning text past a gate prompts cannot pass.

    Drives the full OB2 resolution path: an untrusted run with ``full``
    configured resolves to ``metadata`` (D7), and reasoning captured under
    that resolved policy ships NO body — only the hash + counts. ``off``
    ships nothing at all.
    """
    genai = genai_module
    monkeypatch.setenv("MERGECRAFT_TRACING_CONTENT", "full")
    monkeypatch.delenv("MERGECRAFT_TRACING_EXPORT_UNTRUSTED_CONTENT", raising=False)
    text = "step-by-step reasoning quoting the reviewed diff verbatim"

    untrusted_policy = resolve_content_capture("full", "untrusted")
    assert untrusted_policy is ContentCapture.METADATA  # D7 precondition

    gated = genai.thinking_attrs(text, policy=untrusted_policy)
    assert _THINKING not in gated, "reasoning body must not ship when prompts cannot"
    assert gated[f"{_THINKING}.sha256"], "the D8 hash still ships above off"

    assert genai.thinking_attrs(text, policy=ContentCapture.METADATA).get(_THINKING) is None
    assert genai.thinking_attrs(text, policy=ContentCapture.OFF) == {}
