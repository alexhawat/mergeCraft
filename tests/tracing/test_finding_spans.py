"""Finding lifecycle spans — OB4.1 RED suite (part 3 of 5).

Wave plan: ``.ignorelocal/waves/04-observability-eval-wave-plan.md`` (PR OB4,
sub-wave OB4.1, finding O9). Test-plan doc: ``docs/test-plans/04-observability-eval.md``.

Pins the OB4.2 point-span emitter ``emit_finding`` in
``mergecraft.tracing.signals`` (new), following the
``_tool_attrs.emit_verb_subevent`` open-decorate-close discipline: each
lifecycle event is a ``mergecraft.finding`` span keyed by
``mergecraft.finding.fingerprint`` with ``mergecraft.finding.stage``
(``proposed`` → ``verified`` → ``published`` / ``withdrawn``). The finding
body rides under the OB2 content policy via ``capture_text`` at the
``mergecraft.finding.body`` prefix (convention 4 — no second policy
mechanism): at ``metadata`` no body ships, only the D8 hash + counts; at
``redacted`` the body goes through the secret matcher.

The ``signals`` import is lazy (shared fixture in ``tests/tracing/conftest.py``)
so collection stays clean; both tests carry non-strict ``xfail`` markers
(``green after OB4.2``) and are expected RED until OB4.2 lands.
"""

from __future__ import annotations

import hashlib
from typing import Any

import pytest

from mergecraft.tracing.content import ContentCapture


@pytest.fixture
def tracer_and_sink() -> dict[str, Any]:
    """A real ``MemorySink`` wired to a ``Tracer`` with explicit correlation ids."""
    from mergecraft.tracing import MemorySink, Tracer

    sink = MemorySink()
    tracer = Tracer(
        sink=sink,
        session_id="session-ob4",
        run_id="run-ob4",
        trace_id="trace-ob4",
    )
    return {"sink": sink, "tracer": tracer}


@pytest.mark.xfail(reason="green after OB4.2: emit_finding lifecycle", strict=False)
def test_finding_lifecycle_is_recorded(
    tracer_and_sink: dict[str, Any], signals_module: Any
) -> None:
    """O9 — proposed → verified → published/withdrawn, keyed by fingerprint."""
    signals = signals_module
    tracer = tracer_and_sink["tracer"]
    sink = tracer_and_sink["sink"]

    for stage in ("proposed", "verified", "published"):
        signals.emit_finding(
            tracer,
            fingerprint="fp-blocker-1",
            stage=stage,
            severity="critical",
            category="security",
            message="hardcoded credential",
            policy=ContentCapture.METADATA,
        )
    signals.emit_finding(
        tracer,
        fingerprint="fp-noise-2",
        stage="proposed",
        severity="minor",
        category="style",
        message="nits",
        policy=ContentCapture.METADATA,
    )
    signals.emit_finding(
        tracer,
        fingerprint="fp-noise-2",
        stage="withdrawn",
        severity="minor",
        category="style",
        message="nits",
        policy=ContentCapture.METADATA,
    )

    events = sink.events
    assert len(events) == 5
    for event in events:
        assert event.kind == "mergecraft.finding"
    by_fingerprint: dict[str, list[str]] = {}
    for event in events:
        by_fingerprint.setdefault(event.attrs["mergecraft.finding.fingerprint"], []).append(
            event.attrs["mergecraft.finding.stage"]
        )
    assert by_fingerprint["fp-blocker-1"] == ["proposed", "verified", "published"]
    assert by_fingerprint["fp-noise-2"] == ["proposed", "withdrawn"]
    blocker = events[0]
    assert blocker.attrs["mergecraft.finding.severity"] == "critical"
    assert blocker.attrs["mergecraft.finding.category"] == "security"


@pytest.mark.xfail(reason="green after OB4.2: finding bodies via capture_text", strict=False)
def test_finding_bodies_respect_the_content_policy(
    tracer_and_sink: dict[str, Any], signals_module: Any
) -> None:
    """Finding bodies route through OB2's ``capture_text`` — the D6 gate applies."""
    signals = signals_module
    tracer = tracer_and_sink["tracer"]
    sink = tracer_and_sink["sink"]
    message = "hardcoded token ghp_abcdefghijklmnop1234567890ABCDEFGHIJ in config.yaml"

    signals.emit_finding(
        tracer,
        fingerprint="fp-redacted",
        stage="proposed",
        message=message,
        policy=ContentCapture.REDACTED,
    )
    signals.emit_finding(
        tracer,
        fingerprint="fp-metadata",
        stage="proposed",
        message=message,
        policy=ContentCapture.METADATA,
    )

    redacted_attrs, metadata_attrs = (event.attrs for event in sink.events)
    assert "mergecraft.finding.body" in redacted_attrs
    assert "ghp_abcdefghijklmnop" not in redacted_attrs["mergecraft.finding.body"], (
        "the finding body goes through the secret matcher at redacted"
    )
    assert "mergecraft.finding.body" not in metadata_attrs, "no body ships at metadata"
    expected_hash = hashlib.sha256(message.encode()).hexdigest()
    assert redacted_attrs["mergecraft.finding.body.sha256"] == expected_hash
    assert metadata_attrs["mergecraft.finding.body.sha256"] == expected_hash
