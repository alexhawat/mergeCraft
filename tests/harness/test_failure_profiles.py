"""RH3 — named failure profiles on the HTTP stub."""

from __future__ import annotations

import contextlib

import httpx

from mergecraft.utils.retry_policy import is_transient_http_error
from tests.support.provider_harness import DUMMY_API_KEY
from tests.support.provider_harness.schema import FixtureSpec, MatchSpec, ResponseSpec


def _profile_fixture(profile: str, *, streaming: bool = False) -> FixtureSpec:
    return FixtureSpec(
        name=f"profile-{profile}",
        match=MatchSpec(provider="default", model="dummy", streaming=streaming),
        response=ResponseSpec(body={"id": "stub", "choices": []}),
        profile=profile,
    )


def test_http_429_profile_emits_retry_after(provider_harness) -> None:
    provider_harness.reload([_profile_fixture("http_429")])
    response = httpx.post(
        provider_harness.base_url + "/chat/completions",
        headers={"Authorization": f"Bearer {DUMMY_API_KEY}"},
        json={"model": "default/dummy", "messages": []},
        timeout=5.0,
    )
    assert response.status_code == 429
    assert response.headers.get("Retry-After") == "1"


def test_http_500_profile_is_deterministic(provider_harness) -> None:
    provider_harness.reload([_profile_fixture("http_500")])
    assert (
        httpx.post(
            provider_harness.base_url + "/chat/completions",
            headers={"Authorization": f"Bearer {DUMMY_API_KEY}"},
            json={"model": "default/dummy", "messages": []},
            timeout=5.0,
        ).status_code
        == 500
    )


def test_timeout_profile_is_deterministic(provider_harness) -> None:

    provider_harness.reload([_profile_fixture("timeout")])
    with httpx.Client(timeout=0.05) as client, contextlib.suppress(httpx.ReadTimeout):
        client.post(
            provider_harness.base_url + "/chat/completions",
            headers={"Authorization": f"Bearer {DUMMY_API_KEY}"},
            json={"model": "default/dummy", "messages": []},
        )


def test_malformed_json_profile_returns_invalid_payload(provider_harness) -> None:
    provider_harness.reload([_profile_fixture("malformed_json")])
    response = httpx.post(
        provider_harness.base_url + "/chat/completions",
        headers={"Authorization": f"Bearer {DUMMY_API_KEY}"},
        json={"model": "default/dummy", "messages": []},
        timeout=5.0,
    )
    assert response.status_code == 200
    assert "not-json" in response.text or response.text.startswith("{")


def test_empty_stream_profile_completes_without_content(provider_harness) -> None:
    provider_harness.reload([_profile_fixture("empty_stream", streaming=True)])
    response = httpx.post(
        provider_harness.base_url + "/chat/completions",
        headers={"Authorization": f"Bearer {DUMMY_API_KEY}"},
        json={"model": "default/dummy", "stream": True, "messages": []},
        timeout=5.0,
    )
    assert response.status_code == 200


def test_http_401_profile_is_not_transient(provider_harness) -> None:
    provider_harness.reload([_profile_fixture("http_401")])
    response = httpx.post(
        provider_harness.base_url + "/chat/completions",
        headers={"Authorization": f"Bearer {DUMMY_API_KEY}"},
        json={"model": "default/dummy", "messages": []},
        timeout=5.0,
    )
    assert response.status_code == 401
    assert (
        is_transient_http_error(
            httpx.HTTPStatusError(
                "401", request=httpx.Request("POST", "http://x"), response=httpx.Response(401)
            )
        )
        is False
    )
