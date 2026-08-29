"""RH1.1 RED — mismatch diagnostics contract (``tests.support.provider_harness.diagnostics``)."""

from __future__ import annotations

import pytest

from mergecraft.analyzers.redact import redact_secrets
from mergecraft.redaction_sentinel import REDACTION_SENTINEL
from tests.harness._helpers import snapshot

_MIN_CHAT_BODY = {
    "id": "stub",
    "choices": [{"message": {"role": "assistant", "content": "{}"}}],
}


def _fixture(
    name: str, *, model: str = "dummy", body_fields: dict[str, object] | None = None
) -> object:
    from tests.support.provider_harness.schema import FixtureSpec, MatchSpec, ResponseSpec

    return FixtureSpec(
        name=name,
        match=MatchSpec(
            provider="default", model=model, mode="review", body_fields=body_fields or {}
        ),
        response=ResponseSpec(body=_MIN_CHAT_BODY),
    )


def test_mismatch_includes_redacted_request_and_candidate_reasons() -> None:
    from tests.support.provider_harness.diagnostics import format_mismatch
    from tests.support.provider_harness.matcher import NoFixtureMatch, match_fixture

    api_key = "sk-mergecraft-test"
    req = snapshot(
        body={
            "model": "dummy",
            "messages": [{"role": "user", "content": "review"}],
            "Authorization": f"Bearer {api_key}",
            "api_key": api_key,
        },
    )
    fixtures = [
        _fixture("candidate-a", body_fields={"api_key": "expected-a"}),
        _fixture("candidate-b", body_fields={"api_key": "expected-b"}),
    ]

    try:
        match_fixture(req, fixtures, strict=True)
    except NoFixtureMatch as err:
        diagnostic = format_mismatch(err)
    else:
        pytest.fail("expected NoFixtureMatch")

    assert "candidate-a" in diagnostic
    assert "candidate-b" in diagnostic
    assert "body_fields" in diagnostic
    assert api_key not in diagnostic
    assert "[REDACTED]" in diagnostic or "<redacted>" in diagnostic
    assert "provider" in diagnostic.lower() or "default" in diagnostic
    assert "model" in diagnostic.lower() or "dummy" in diagnostic


def test_diagnostics_do_not_include_provider_keys_or_github_tokens() -> None:
    """Pin — ``redact_secrets`` contract harness diagnostics must reuse (D14)."""
    raw = "sk-abc12345ghi and ghp_" + "x" * 36
    redacted = redact_secrets(raw)

    assert "sk-abc12345ghi" not in redacted
    assert "ghp_" + "x" * 36 not in redacted
    assert REDACTION_SENTINEL in redacted


def test_failure_diagnostic_contains_fixture_usage_and_latency() -> None:
    from tests.support.provider_harness.diagnostics import format_mismatch
    from tests.support.provider_harness.matcher import NoFixtureMatch
    from tests.support.provider_harness.metrics import HarnessMetrics

    metrics = HarnessMetrics()
    metrics.fixture_usage["candidate"] = 2
    err = NoFixtureMatch(
        request=snapshot(), fixtures=[], candidate_reasons={"candidate": "model mismatch"}
    )
    text = format_mismatch(err, metrics=metrics, latency_ms=12.5)
    assert "fixture_usage" in text
    assert "latency_ms" in text


def test_diagnostics_never_dump_unbounded_payloads() -> None:
    from tests.support.provider_harness.diagnostics import format_mismatch
    from tests.support.provider_harness.matcher import NoFixtureMatch

    huge = "x" * 5000
    err = NoFixtureMatch(
        request=snapshot(body={"blob": huge}),
        fixtures=[],
        candidate_reasons={"x": f"body_fields['blob']: expected 'y', got {huge!r}"},
    )
    text = format_mismatch(err)
    assert len(text) < 5000
