"""RH1.1 RED — mismatch diagnostics contract (``tests.support.provider_harness.diagnostics``)."""

from __future__ import annotations

import pytest

from mergecraft.analyzers.redact import redact_secrets
from tests.harness._helpers import snapshot

_MIN_CHAT_BODY = {
    "id": "stub",
    "choices": [{"message": {"role": "assistant", "content": "{}"}}],
}


def _fixture(name: str, *, model: str = "dummy") -> object:
    from tests.support.provider_harness.schema import FixtureSpec, MatchSpec, ResponseSpec

    return FixtureSpec(
        name=name,
        match=MatchSpec(provider="default", model=model, mode="review"),
        response=ResponseSpec(body=_MIN_CHAT_BODY),
    )


@pytest.mark.xfail(reason="green after RH1.2", strict=False)
def test_mismatch_includes_redacted_request_and_candidate_reasons() -> None:
    from tests.support.provider_harness.diagnostics import format_mismatch
    from tests.support.provider_harness.matcher import NoFixtureMatch, match_fixture

    api_key = "sk-mergecraft-test"
    req = snapshot(
        body={
            "model": "dummy",
            "messages": [{"role": "user", "content": "review"}],
            "Authorization": f"Bearer {api_key}",
        },
    )
    fixtures = [_fixture("candidate-a", model="other-a"), _fixture("candidate-b", model="other-b")]

    try:
        match_fixture(req, fixtures, strict=True)
    except NoFixtureMatch as err:
        diagnostic = format_mismatch(err)
    else:
        pytest.fail("expected NoFixtureMatch")

    assert "candidate-a" in diagnostic
    assert "candidate-b" in diagnostic
    assert api_key not in diagnostic
    assert "[REDACTED]" in diagnostic
    assert "provider" in diagnostic.lower() or "default" in diagnostic
    assert "model" in diagnostic.lower() or "dummy" in diagnostic


def test_diagnostics_do_not_include_provider_keys_or_github_tokens() -> None:
    """Pin — ``redact_secrets`` contract harness diagnostics must reuse (D14)."""
    raw = "sk-abc12345ghi and ghp_" + "x" * 36
    redacted = redact_secrets(raw)

    assert "sk-abc12345ghi" not in redacted
    assert "ghp_" + "x" * 36 not in redacted
    assert "[REDACTED]" in redacted
