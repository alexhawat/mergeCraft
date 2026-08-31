"""Plan 18 W1.1 — credential broker RED contracts (implementation W2).

Pins loopback bind, bearer gate, upstream allow-list, model-path-only proxying,
redaction, and parent->upstream Authorization forwarding (#553 option 3 / D1-D4).
"""

from __future__ import annotations

import asyncio
import secrets
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from tests.security.support_agent_isolation import (
    EVIL_UPSTREAM_HOST,
    MODEL_PATH,
    NON_MODEL_PATHS,
    REAL_OPENAI_API_KEY_FIXTURE,
    MockModelUpstream,
    assert_credential_absent,
    broker_config_for_upstream,
    capture_loguru_messages,
    load_broker_module,
    require_broker_symbol,
    serialized_evidence_packet_fixture,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


def _start_broker(
    module: Any,
    upstream: MockModelUpstream,
    *,
    bind_host: str | None = None,
) -> Iterator[Any]:
    credential_broker = require_broker_symbol(module, "credential_broker")
    config = broker_config_for_upstream(module, upstream)
    kwargs: dict[str, Any] = {}
    if bind_host is not None:
        kwargs["bind_host"] = bind_host
    return credential_broker(config, **kwargs)


def _broker_client(handle: Any) -> httpx.Client:
    base = getattr(handle, "base_url", None)
    if not isinstance(base, str):
        host = getattr(handle, "host", "127.0.0.1")
        port = handle.port
        base = f"http://{host}:{port}"
    return httpx.Client(base_url=base, timeout=10.0)


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_broker_binds_loopback_only() -> None:
    """D1 — broker listens on 127.0.0.1, never 0.0.0.0."""
    module = load_broker_module()
    bind_host = require_broker_symbol(module, "BROKER_BIND_HOST")
    assert bind_host == "127.0.0.1"

    with MockModelUpstream() as upstream, _start_broker(module, upstream) as handle:
        assert handle.host == "127.0.0.1"
        response = httpx.get(f"http://{handle.host}:{handle.port}/v1/models", timeout=2.0)
        # Unauthenticated probe still proves loopback reachability.
        assert response.status_code in {401, 403, 404, 405}


def test_broker_rejects_non_loopback_bind() -> None:
    """Forcing 0.0.0.0 must fail closed."""
    module = load_broker_module()
    bind_error = None
    for name in ("BrokerBindError", "CredentialBrokerBindError"):
        if hasattr(module, name):
            bind_error = getattr(module, name)
            break
    expected_errors: tuple[type[BaseException], ...] = (ValueError,)
    if bind_error is not None:
        expected_errors = (bind_error, ValueError)

    with (
        MockModelUpstream() as upstream,
        pytest.raises(expected_errors, match=r"127\.0\.0\.1|loopback|bind|0\.0\.0\.0"),
        _start_broker(module, upstream, bind_host="0.0.0.0"),
    ):
        pass


def test_broker_rejects_missing_bearer() -> None:
    """No Authorization header → HTTP 401."""
    module = load_broker_module()
    with MockModelUpstream() as upstream, _start_broker(module, upstream) as handle:
        with _broker_client(handle) as client:
            response = client.post(MODEL_PATH, json={"model": "gpt-stub", "messages": []})
        assert response.status_code == 401


def test_broker_rejects_wrong_bearer() -> None:
    """Wrong bearer → HTTP 401."""
    module = load_broker_module()
    with MockModelUpstream() as upstream, _start_broker(module, upstream) as handle:
        with _broker_client(handle) as client:
            response = client.post(
                MODEL_PATH,
                json={"model": "gpt-stub", "messages": []},
                headers=_auth_headers("definitely-not-the-run-token"),
            )
        assert response.status_code == 401


def test_bearer_validation_uses_constant_time_compare_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bearer comparison must use ``secrets.compare_digest`` (D2)."""
    module = load_broker_module()
    calls: list[tuple[bytes, bytes]] = []
    real_compare = secrets.compare_digest

    def _spy(left: Any, right: Any) -> bool:
        calls.append((bytes(left), bytes(right)))
        return real_compare(left, right)

    monkeypatch.setattr(module.secrets, "compare_digest", _spy)

    with (
        MockModelUpstream() as upstream,
        _start_broker(module, upstream) as handle,
        _broker_client(handle) as client,
    ):
        client.post(
            MODEL_PATH,
            json={"model": "gpt-stub", "messages": []},
            headers=_auth_headers("wrong-token"),
        )
    assert calls, "broker must call secrets.compare_digest for bearer validation"


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": EVIL_UPSTREAM_HOST},
        {"X-Forwarded-Host": EVIL_UPSTREAM_HOST},
    ],
    ids=["host-smuggle", "forwarded-host-smuggle"],
)
def test_broker_rejects_upstream_host_smuggle(headers: dict[str, str]) -> None:
    """Host header outside allow-list + configured origin → 403 (D4)."""
    module = load_broker_module()
    with MockModelUpstream() as upstream, _start_broker(module, upstream) as handle:
        with _broker_client(handle) as client:
            response = client.post(
                MODEL_PATH,
                json={"model": "gpt-stub", "messages": []},
                headers={**_auth_headers(handle.token), **headers},
            )
        assert response.status_code == 403
        assert_credential_absent(response.text)


def test_broker_rejects_absolute_url_rewrite() -> None:
    """Absolute request URL to a non-allowlisted host → 403 (D4)."""
    module = load_broker_module()
    with MockModelUpstream() as upstream, _start_broker(module, upstream) as handle:
        evil_url = f"http://{EVIL_UPSTREAM_HOST}{MODEL_PATH}"
        with _broker_client(handle) as client:
            response = client.post(
                evil_url,
                json={"model": "gpt-stub", "messages": []},
                headers=_auth_headers(handle.token),
            )
        assert response.status_code == 403
        assert_credential_absent(response.text)


def test_broker_refuses_redirect_to_non_allowlisted_host() -> None:
    """Redirect off the run allow-list must not be followed."""
    module = load_broker_module()
    redirect_target = f"http://{EVIL_UPSTREAM_HOST}/v1/chat/completions"
    with (
        MockModelUpstream(redirect_to=redirect_target) as upstream,
        _start_broker(module, upstream) as handle,
    ):
        with _broker_client(handle) as client:
            response = client.post(
                MODEL_PATH,
                json={"model": "gpt-stub", "messages": []},
                headers=_auth_headers(handle.token),
            )
        assert response.status_code in {403, 502, 504}
        assert_credential_absent(response.text)


@pytest.mark.parametrize("path", NON_MODEL_PATHS)
def test_broker_refuses_non_model_paths(path: str) -> None:
    """Non-model paths are refused — model proxy only (D4)."""
    module = load_broker_module()
    with MockModelUpstream() as upstream, _start_broker(module, upstream) as handle:
        with _broker_client(handle) as client:
            response = client.get(path, headers=_auth_headers(handle.token))
        assert response.status_code in {403, 404, 405}
        assert_credential_absent(response.text)


def test_broker_never_leaks_real_credential_in_responses_errors_or_logs() -> None:
    """#553 — real credential in no response body, error body, or log line."""
    module = load_broker_module()
    bodies: list[str] = []
    with (
        capture_loguru_messages() as logs,
        MockModelUpstream() as upstream,
        _start_broker(module, upstream) as handle,
        _broker_client(handle) as client,
    ):
        for call in (
            client.post(MODEL_PATH, json={"model": "gpt-stub", "messages": []}),
            client.post(
                MODEL_PATH,
                json={"model": "gpt-stub", "messages": []},
                headers=_auth_headers("wrong"),
            ),
            client.post(
                MODEL_PATH,
                json={"model": "gpt-stub", "messages": []},
                headers={**_auth_headers(handle.token), "Host": EVIL_UPSTREAM_HOST},
            ),
        ):
            bodies.append(call.text)
    combined = "\n".join([*bodies, *logs])
    assert_credential_absent(combined)


def test_broker_never_leaks_real_credential_in_evidence_packet_fixture() -> None:
    """Serialized evidence-packet fixture must not carry the upstream API key."""
    module = load_broker_module()
    packet_text = serialized_evidence_packet_fixture(
        error_detail="broker upstream refused host evil.example"
    )
    with MockModelUpstream() as upstream, _start_broker(module, upstream) as handle:
        with _broker_client(handle) as client:
            response = client.post(
                MODEL_PATH,
                json={"model": "gpt-stub", "messages": []},
                headers=_auth_headers(handle.token),
            )
        redact = require_broker_symbol(module, "redact_broker_output")
        redacted_response = redact(response.text)
        redacted_packet = redact(packet_text)
    assert_credential_absent(redacted_response)
    assert_credential_absent(redacted_packet)


def test_broker_forwards_real_key_on_parent_upstream_leg() -> None:
    """Parent→upstream leg must present the real credential to the model host."""
    module = load_broker_module()
    with MockModelUpstream() as upstream, _start_broker(module, upstream) as handle:
        with _broker_client(handle) as client:
            response = client.post(
                MODEL_PATH,
                json={"model": "gpt-stub", "messages": [{"role": "user", "content": "ping"}]},
                headers=_auth_headers(handle.token),
            )
        assert response.status_code == 200
    assert upstream.authorization_headers, "upstream must receive Authorization"
    assert any(
        header.startswith("Bearer ") and REAL_OPENAI_API_KEY_FIXTURE in header
        for header in upstream.authorization_headers
    )


@pytest.mark.asyncio
async def test_concurrent_requests_with_same_bearer() -> None:
    """Two concurrent agent requests sharing one per-run bearer must both succeed."""
    module = load_broker_module()
    with MockModelUpstream() as upstream, _start_broker(module, upstream) as handle:
        headers = _auth_headers(handle.token)
        payload = {"model": "gpt-stub", "messages": [{"role": "user", "content": "ping"}]}
        base = getattr(handle, "base_url", f"http://{handle.host}:{handle.port}")

        async with httpx.AsyncClient(base_url=base, timeout=10.0) as client:
            responses = await asyncio.gather(
                client.post(MODEL_PATH, json=payload, headers=headers),
                client.post(MODEL_PATH, json=payload, headers=headers),
            )
        assert all(response.status_code == 200 for response in responses)
