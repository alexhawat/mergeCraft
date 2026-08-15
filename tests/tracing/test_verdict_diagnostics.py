"""VP3 diagnostics suite — ``VerdictDiagnostic`` on the span, through redaction.

Wave plan: ``.ignorelocal/01-review-integrity-wave-plan.md`` (VP3.1 File 4,
VP3.2 impl; xfail markers cleared after VP3.2).

The eight closed values (snake_case ``StrEnum`` members) must each appear
as a span attribute and/or check-run summary **through**
``tracing/redaction.py``. A submission summary that looks like a token
must not survive onto the span — deleting the redaction call must fail
``test_diagnostics_are_redacted``.
"""

from __future__ import annotations

import json
from typing import Any

# Plan VP3.1: provider failure · provider success w/o submission ·
# schema-invalid · semantic-invalid · policy rejection ·
# agent-approved-but-blocked · approved · fallback-triggered.
_CLOSED_DIAGNOSTICS: tuple[str, ...] = (
    "provider_failure",
    "provider_success_without_submission",
    "schema_invalid",
    "semantic_invalid",
    "policy_rejection",
    "agent_approved_but_blocked",
    "approved",
    "fallback_triggered",
)

_TOKEN = "sk-abcdefghijklmnopqrstuvwxyz"
_TOKEN_SUMMARY = f"Looks good. token={_TOKEN}"
_SPAN_ATTR_KEYS: tuple[str, ...] = (
    "verdict.diagnostic",
    "mergecraft.verdict.diagnostic",
    "diagnostic",
)


def _diagnostic_on_attrs(attrs: dict[str, Any], expected: str) -> bool:
    values = {str(value) for value in attrs.values()}
    if expected in values:
        return True
    for key in _SPAN_ATTR_KEYS:
        if str(attrs.get(key, "")) == expected:
            return True
    return expected in json.dumps(attrs, default=str)


def _attrs_from_helper(diagnostic: Any, *, summary: str) -> dict[str, Any]:
    """Drive the product emission helper VP3.2 must add.

    The helper is required to run the payload through
    ``tracing/redaction.py`` (``redact_attrs`` / ``redact_event``) before
    returning. This test inspects the helper's return value directly —
    the test itself does **not** call ``redact_attrs``, so skipping
    redaction in the helper leaves the token on the attrs.
    """
    from mergecraft.mcp.verdict import span_attrs_for_verdict_diagnostic

    raw = span_attrs_for_verdict_diagnostic(diagnostic, summary=summary)
    attrs = raw[0] if isinstance(raw, tuple) else raw
    if not isinstance(attrs, dict):
        msg = (
            f"span_attrs_for_verdict_diagnostic must return attrs dict, got {type(attrs).__name__}"
        )
        raise TypeError(msg)
    return attrs


def test_each_diagnostic_reaches_the_span() -> None:
    """Each of the eight closed ``VerdictDiagnostic`` values reaches the span.

    Iterated in one collected test so VP3.1 acceptance stays 9 collected.
    """
    from mergecraft.mcp.verdict import VerdictDiagnostic
    from mergecraft.tracing.event import TraceEvent
    from mergecraft.tracing.redaction import redact_attrs

    members = tuple(member.value for member in VerdictDiagnostic)
    assert members == _CLOSED_DIAGNOSTICS, (
        f"VerdictDiagnostic must be the eight closed values, got {members!r}"
    )
    assert {member.name for member in VerdictDiagnostic} == set(_CLOSED_DIAGNOSTICS)

    for member in VerdictDiagnostic:
        attrs = _attrs_from_helper(member, summary=f"diagnostic={member.value}")
        assert _diagnostic_on_attrs(attrs, member.value), (
            f"{member.value!r} missing from span attrs {attrs!r}"
        )
        # The emission path is defined to go through redaction.py; applying
        # it again must not drop the diagnostic code itself.
        redacted = redact_attrs(attrs)
        assert _diagnostic_on_attrs(redacted, member.value), (
            f"redaction dropped diagnostic {member.value!r}"
        )
        event = TraceEvent.model_validate(
            {
                "kind": "mergecraft.publish",
                "span_id": "span-verdict",
                "parent_span_id": None,
                "session_id": "run-1",
                "turn_id": "turn-1",
                "tier": "trusted",
                "ts_start_ns": 1_000,
                "ts_end_ns": 2_000,
                "status": "ok",
                "attrs": attrs,
                "trace_id": "trace-verdict-0001",
            }
        )
        assert _diagnostic_on_attrs(event.attrs, member.value)


def test_diagnostics_are_redacted() -> None:
    """A submission summary that looks like a token must not appear on the span.

    Guard-deletion: if ``span_attrs_for_verdict_diagnostic`` skips
    ``tracing/redaction.py``, ``_TOKEN`` survives on the returned attrs
    and this test fails. The test does not re-apply ``redact_attrs`` to
    the helper output before the leak assertion.
    """
    from mergecraft.mcp.verdict import VerdictDiagnostic
    from mergecraft.tracing.redaction import redact_attrs

    # Prove the canary is actually secret-shaped for this redaction layer.
    leaked = {"summary": _TOKEN_SUMMARY}
    assert _TOKEN in json.dumps(leaked)
    assert _TOKEN not in json.dumps(redact_attrs(leaked)), (
        "fixture token is not redacted by tracing/redaction.py — pick another canary"
    )

    attrs = _attrs_from_helper(VerdictDiagnostic.approved, summary=_TOKEN_SUMMARY)
    serialized = json.dumps(attrs, default=str)
    assert _TOKEN not in serialized, (
        "submission summary token leaked onto the span; redaction was skipped"
    )
    assert _diagnostic_on_attrs(attrs, VerdictDiagnostic.approved.value)
