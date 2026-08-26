"""BR1.3 / BR4 — webhook header validation and route hardening (MCB-11, D8/D16)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from mergecraft.mcp.server import create_mcp_app
from mergecraft.scm.httpx_compat import install_httpx_latin1_header_values
from mergecraft.scm.webhooks import sign_webhook_payload


@pytest.fixture(autouse=True)
def _install_httpx_latin1_header_values() -> None:
    """Match HTTP latin-1 header bytes when httpx builds TestClient requests."""
    install_httpx_latin1_header_values()


_WEBHOOK_SECRET = "br1-webhook-header-test-secret"
_NON_ASCII_BYTE = bytes([0x80]).decode("latin-1")


def _signed_github_headers(body: bytes) -> dict[str, str]:
    headers = sign_webhook_payload("github", body=body, secret=_WEBHOOK_SECRET)
    headers["X-GitHub-Delivery"] = "br1-delivery-0001"
    headers["X-GitHub-Event"] = "pull_request"
    return headers


@pytest.mark.parametrize("provider", ["github", "gitlab"])
def test_non_ascii_header_raises_permission_error(provider: str) -> None:
    """MCB-11: non-ASCII header bytes raise ``PermissionError``, not ``TypeError``."""
    from mergecraft.scm.webhooks import verify_webhook_signature

    body = b'{"action":"opened"}'
    if provider == "github":
        headers = _signed_github_headers(body)
        headers["X-Hub-Signature-256"] = f"sha256={_NON_ASCII_BYTE}"
    else:
        headers = {
            "X-Gitlab-Token": _NON_ASCII_BYTE,
            "X-Gitlab-Event-UUID": "br1-gitlab-delivery-0001",
            "X-Gitlab-Event": "Merge Request Hook",
        }
    with pytest.raises(PermissionError):
        verify_webhook_signature(provider, headers=headers, body=body, secret=_WEBHOOK_SECRET)


def test_empty_and_oversized_headers_are_rejected() -> None:
    """MCB-11: blank secrets and oversized header values fail closed."""
    from mergecraft.scm.webhooks import verify_webhook_signature

    body = b"{}"
    with pytest.raises(PermissionError, match=r"missing webhook secret"):
        verify_webhook_signature("github", headers={}, body=body, secret="   ")
    huge = "x" * 16_384
    headers = _signed_github_headers(body)
    headers["X-Hub-Signature-256"] = huge
    with pytest.raises(PermissionError):
        verify_webhook_signature("github", headers=headers, body=body, secret=_WEBHOOK_SECRET)


def test_route_never_returns_500_on_an_unauthenticated_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D8: ingress route maps unexpected failures to 4xx, never 500."""
    monkeypatch.setenv("MERGECRAFT_WEBHOOK_SECRET", _WEBHOOK_SECRET)
    client = TestClient(create_mcp_app([]))
    body = b'{"action":"opened"}'
    headers = _signed_github_headers(body)
    headers["X-Hub-Signature-256"] = f"sha256={_NON_ASCII_BYTE}"
    response = client.post("/webhooks/github", content=body, headers=headers)
    assert response.status_code != 500
    assert response.status_code in {400, 401}
    payload = response.json()
    assert isinstance(payload, dict)
    assert "error" in payload
