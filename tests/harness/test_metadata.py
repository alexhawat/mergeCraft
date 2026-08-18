"""RH3 — response metadata overrides."""

from __future__ import annotations

import httpx

from tests.support.provider_harness import DUMMY_API_KEY
from tests.support.provider_harness.schema import FixtureSpec, MatchSpec, ResponseSpec


def test_fixture_controls_response_usage_and_request_id(provider_harness) -> None:
    fixture = FixtureSpec(
        name="metadata",
        match=MatchSpec(provider="default", model="dummy"),
        response=ResponseSpec(
            body={
                "id": "meta-id",
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            },
            usage={"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
            request_id="req-123",
            finish_reason="stop",
        ),
    )
    provider_harness.reload([fixture])
    body = httpx.post(
        provider_harness.base_url + "/chat/completions",
        headers={"Authorization": f"Bearer {DUMMY_API_KEY}"},
        json={"model": "default/dummy", "messages": []},
        timeout=5.0,
    ).json()
    assert body["id"] == "req-123"
    assert body.get("usage", {}).get("total_tokens") == 7


def test_rate_limit_headers_are_preserved_on_429(provider_harness) -> None:
    fixture = FixtureSpec(
        name="rate-limit",
        match=MatchSpec(provider="default", model="dummy"),
        response=ResponseSpec(body={"error": "rate_limit"}),
        profile="http_429",
    )
    provider_harness.reload([fixture])
    response = httpx.post(
        provider_harness.base_url + "/chat/completions",
        headers={"Authorization": f"Bearer {DUMMY_API_KEY}"},
        json={"model": "default/dummy", "messages": []},
        timeout=5.0,
    )
    assert response.status_code == 429
    assert "Retry-After" in response.headers
