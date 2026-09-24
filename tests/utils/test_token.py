"""Behavioural tests for ``mergecraft.utils.token`` (#797).

`utils/token.py` sits on the auth critical path (``resolve_tokens``,
``get_job_token``, ``acquire_installation_token``, ``_app_jwt``,
``revoke_installation_token``) but its critical-path floor is
``(51.9, 39.2)`` — the untested paths are the App-JWT mint, installation-id
resolution, the revoke branches, and the xrepo read-token plumbing. These tests
pin the current public behaviour so a measured floor can replace the weak one
(plan 31); they are green today and must stay green.

No floor number changes here (Q-D6).
"""

from __future__ import annotations

import asyncio
import builtins
import sys
import types
from typing import Any

import httpx
import pytest

import mergecraft.utils.token as token_mod
from mergecraft.types import XrepoConfig
from mergecraft.utils.token import (
    acquire_installation_token,
    get_job_token,
    resolve_tokens,
    revoke_installation_token,
)

_API = "https://api.github.com"


@pytest.fixture(autouse=True)
def _reset_token_module_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset module globals and token env between tests (mirrors G4.1)."""
    monkeypatch.setattr(token_mod, "_mcp_token_value", None)
    monkeypatch.setattr(token_mod, "_mcp_token_refresh", None)
    for key in (
        "INPUT_TOKEN",
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "GITHUB_APP_ID",
        "GITHUB_APP_PRIVATE_KEY",
        "GITHUB_APP_INSTALLATION_ID",
        "GITHUB_REPOSITORY",
        "GITHUB_API_URL",
    ):
        monkeypatch.delenv(key, raising=False)


class _FakeResponse:
    def __init__(self, *, json_data: dict[str, Any] | None = None, status_code: int = 200) -> None:
        self._json = json_data or {}
        self.status_code = status_code
        self.request = httpx.Request("GET", f"{_API}/fake")
        self.headers: dict[str, str] = {}

    def json(self) -> dict[str, Any]:
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=self.request,
                response=httpx.Response(self.status_code, request=self.request),
            )


class _FakeClient:
    """Minimal ``httpx.AsyncClient`` stand-in that records calls."""

    def __init__(
        self,
        *,
        get_response: _FakeResponse | None = None,
        post_response: _FakeResponse | None = None,
        delete_response: _FakeResponse | None = None,
        delete_error: Exception | None = None,
    ) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self._get_response = get_response
        self._post_response = post_response or _FakeResponse(json_data={"token": "ghs_test"})
        self._delete_response = delete_response or _FakeResponse(status_code=204)
        self._delete_error = delete_error

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append(("GET", url, kwargs))
        assert self._get_response is not None, "unexpected GET"
        return self._get_response

    async def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append(("POST", url, kwargs))
        return self._post_response

    async def delete(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append(("DELETE", url, kwargs))
        if self._delete_error is not None:
            raise self._delete_error
        return self._delete_response


def _install_client(monkeypatch: pytest.MonkeyPatch, client: _FakeClient) -> _FakeClient:
    monkeypatch.setattr(token_mod.httpx, "AsyncClient", lambda *_a, **_k: client)
    return client


# ── acquire_installation_token ───────────────────────────────────────────────


async def test_acquire_installation_token_mints_with_explicit_installation_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """App JWT → POST /app/installations/{id}/access_tokens with a built body."""
    monkeypatch.setattr(token_mod, "_app_jwt", lambda: "app-jwt")
    client = _install_client(monkeypatch, _FakeClient())

    token = await acquire_installation_token(
        installation_id=42,
        permissions={"contents": "write"},
        repos=["acme/other", "acme/thing"],
    )

    assert token == "ghs_test"
    assert len(client.calls) == 1
    method, url, kwargs = client.calls[0]
    assert method == "POST"
    assert url == f"{_API}/app/installations/42/access_tokens"
    headers = kwargs["headers"]
    assert headers["Authorization"] == "Bearer app-jwt"
    assert headers["Accept"] == "application/vnd.github+json"
    assert headers["X-GitHub-Api-Version"] == "2022-11-28"
    # GitHub expects bare repo names in the `repositories` list.
    assert kwargs["json"] == {
        "permissions": {"contents": "write"},
        "repositories": ["other", "thing"],
    }


async def test_acquire_installation_token_resolves_id_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`GITHUB_APP_INSTALLATION_ID` skips the repo-installation lookup."""
    monkeypatch.setattr(token_mod, "_app_jwt", lambda: "app-jwt")
    monkeypatch.setenv("GITHUB_APP_INSTALLATION_ID", "7")
    client = _install_client(monkeypatch, _FakeClient())

    token = await acquire_installation_token()

    assert token == "ghs_test"
    assert len(client.calls) == 1
    assert client.calls[0][0] == "POST"
    assert client.calls[0][1] == f"{_API}/app/installations/7/access_tokens"


async def test_acquire_installation_token_resolves_id_from_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`GITHUB_REPOSITORY` resolves the installation via the repos endpoint."""
    monkeypatch.setattr(token_mod, "_app_jwt", lambda: "app-jwt")
    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/demo")
    client = _install_client(
        monkeypatch,
        _FakeClient(get_response=_FakeResponse(json_data={"id": 99})),
    )

    token = await acquire_installation_token()

    assert token == "ghs_test"
    assert [(method, url) for method, url, _ in client.calls] == [
        ("GET", f"{_API}/repos/acme/demo/installation"),
        ("POST", f"{_API}/app/installations/99/access_tokens"),
    ]


async def test_acquire_installation_token_requires_an_installation_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Neither id env var nor `GITHUB_REPOSITORY` is a configuration error."""
    monkeypatch.setattr(token_mod, "_app_jwt", lambda: "app-jwt")
    _install_client(monkeypatch, _FakeClient())

    with pytest.raises(ValueError, match="GITHUB_REPOSITORY or GITHUB_APP_INSTALLATION_ID"):
        await acquire_installation_token()


async def test_acquire_installation_token_without_app_credentials_raises() -> None:
    """No App credentials is a hard error, not a silent empty token."""
    with pytest.raises(ValueError, match="GITHUB_APP_ID and GITHUB_APP_PRIVATE_KEY"):
        await acquire_installation_token(installation_id=1)


async def test_acquire_installation_token_propagates_non_2xx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rejected mint surfaces the HTTP status, it does not return a token."""
    monkeypatch.setattr(token_mod, "_app_jwt", lambda: "app-jwt")
    _install_client(
        monkeypatch,
        _FakeClient(post_response=_FakeResponse(status_code=403)),
    )

    with pytest.raises(httpx.HTTPStatusError):
        await acquire_installation_token(installation_id=1)


async def test_acquire_installation_token_omits_an_empty_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No permissions and no repos means no JSON body is sent."""
    monkeypatch.setattr(token_mod, "_app_jwt", lambda: "app-jwt")
    client = _install_client(monkeypatch, _FakeClient())

    await acquire_installation_token(installation_id=1)

    assert client.calls[0][2]["json"] is None


# ── _app_jwt ──────────────────────────────────────────────────────────────────


def test_app_jwt_without_credentials_is_none() -> None:
    assert token_mod._app_jwt() is None


def test_app_jwt_without_pyjwt_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing optional dependency degrades to no JWT, it does not raise."""
    monkeypatch.setenv("GITHUB_APP_ID", "12345")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "key")
    real_import = builtins.__import__

    def _fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "jwt":
            raise ImportError("no pyjwt")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    assert token_mod._app_jwt() is None


class _FakeJwtModule(types.ModuleType):
    def __init__(self) -> None:
        super().__init__("jwt")
        self.calls: list[dict[str, Any]] = []

    def encode(self, payload: dict[str, Any], key: str, *, algorithm: str) -> str:
        self.calls.append({"payload": payload, "key": key, "algorithm": algorithm})
        return "jwt-token"


def test_app_jwt_payload_shape_and_newline_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """The JWT claims are `iat`/`exp`/`iss`, and `\\n` becomes a real newline."""
    fake_jwt = _FakeJwtModule()
    monkeypatch.setitem(sys.modules, "jwt", fake_jwt)
    monkeypatch.setattr(token_mod.time, "time", lambda: 1_000_000)
    monkeypatch.setenv("GITHUB_APP_ID", "12345")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "line1\\nline2")

    assert token_mod._app_jwt() == "jwt-token"

    call = fake_jwt.calls[0]
    assert call["payload"] == {"iat": 999_940, "exp": 1_000_540, "iss": "12345"}
    assert call["key"] == "line1\nline2"
    assert call["algorithm"] == "RS256"


# ── revoke_installation_token ────────────────────────────────────────────────


async def test_revoke_installation_token_deletes_the_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _install_client(monkeypatch, _FakeClient())

    await revoke_installation_token("ghs_x")

    method, url, kwargs = client.calls[0]
    assert method == "DELETE"
    assert url == f"{_API}/installation/token"
    assert kwargs["headers"]["Authorization"] == "Bearer ghs_x"


async def test_revoke_installation_token_never_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Revocation is best-effort; a network fault must not fail the run."""
    _install_client(
        monkeypatch,
        _FakeClient(delete_error=RuntimeError("network down")),
    )

    assert await revoke_installation_token("ghs_x") is None


@pytest.mark.parametrize("status_code", [401, 403, 500])
@pytest.mark.xfail(reason="green after the logged-cleanup-failure wave lands", strict=False)
async def test_revoke_installation_token_logs_http_failures_at_warning(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    """A rejected revocation is reported at warning, without the token value."""
    _install_client(
        monkeypatch,
        _FakeClient(delete_response=_FakeResponse(status_code=status_code)),
    )
    messages: list[str] = []

    def _record_warning(message: str, *args: object) -> None:
        messages.append(message.format(*args))

    monkeypatch.setattr(token_mod.logger, "warning", _record_warning)

    assert await revoke_installation_token("ghs_secret_value") is None
    assert messages == [f"Failed to revoke installation token: HTTP {status_code}"]
    assert "ghs_secret_value" not in messages[0]


# ── resolve_tokens ───────────────────────────────────────────────────────────


async def test_resolve_tokens_gh_token_shortcut_is_external(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`GH_TOKEN` is used verbatim and never treated as a minted token."""
    monkeypatch.setenv("GH_TOKEN", "gh-tok")
    ref = await resolve_tokens()
    try:
        assert ref.git_token == "gh-tok"
        assert ref.mcp_token == "gh-tok"
        assert ref.read_token is None
        assert token_mod._mcp_token_value == "gh-tok"
    finally:
        await ref.aclose()
    assert token_mod._mcp_token_value is None


async def test_resolve_tokens_gh_token_shortcut_sets_read_token_with_xrepo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GH_TOKEN", "gh-tok")
    ref = await resolve_tokens(xrepo={"write": ["acme/other"]})
    try:
        assert ref.read_token == "gh-tok"
    finally:
        await ref.aclose()


async def test_resolve_tokens_double_resolve_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolving twice without closing is a programming error."""
    token_mod._mcp_token_value = "existing"
    monkeypatch.setenv("GH_TOKEN", "gh-tok")
    with pytest.raises(RuntimeError, match="already resolved"):
        await resolve_tokens()


async def test_resolve_tokens_app_mint_wins_and_revokes_on_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A minted installation token wins, and `aclose` revokes it."""
    monkeypatch.setenv("GITHUB_APP_ID", "12345")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "key")
    monkeypatch.setenv("GITHUB_TOKEN", "workflow-tok")
    minted: list[dict[str, Any]] = []
    revoked: list[str] = []

    async def _mint(**kwargs: Any) -> str:
        minted.append(kwargs)
        return f"minted-token-{len(minted)}"

    async def _revoke(token: str) -> None:
        revoked.append(token)

    monkeypatch.setattr(token_mod, "acquire_installation_token", _mint)
    monkeypatch.setattr(token_mod, "revoke_installation_token", _revoke)

    ref = await resolve_tokens(push="restricted", primary_repo="acme/demo")
    try:
        assert ref.git_token == "minted-token-2"
        assert ref.mcp_token == "minted-token-1"
        assert ref.read_token is None
        assert minted == [
            {
                "repos": ["acme/demo"],
                "permissions": {
                    "contents": "read",
                    "pull_requests": "write",
                    "issues": "write",
                    "checks": "read",
                    "actions": "read",
                },
            },
            {
                "repos": ["acme/demo"],
                "permissions": {"contents": "write", "workflows": "write"},
            },
        ]
    finally:
        await ref.aclose()
        await ref.aclose()

    assert revoked == ["minted-token-1", "minted-token-2"]
    assert token_mod._mcp_token_value is None


async def test_resolve_tokens_disabled_push_requests_read_only_contents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_APP_ID", "12345")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "key")
    monkeypatch.setenv("GITHUB_TOKEN", "workflow-tok")
    minted: list[dict[str, Any]] = []

    async def _mint(**kwargs: Any) -> str:
        minted.append(kwargs)
        return "minted-token"

    monkeypatch.setattr(token_mod, "acquire_installation_token", _mint)

    ref = await resolve_tokens(push="disabled", primary_repo="acme/demo")
    try:
        assert minted[1] == {
            "repos": ["acme/demo"],
            "permissions": {"contents": "read"},
        }
    finally:
        await ref.aclose()


async def test_resolve_tokens_app_mint_failure_falls_back_to_job_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed mint degrades to the job token rather than aborting the run."""
    monkeypatch.setenv("GITHUB_APP_ID", "12345")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "key")
    monkeypatch.setenv("GITHUB_TOKEN", "workflow-tok")

    async def _boom(**_kwargs: Any) -> str:
        msg = "mint failed"
        raise RuntimeError(msg)

    monkeypatch.setattr(token_mod, "acquire_installation_token", _boom)

    ref = await resolve_tokens()
    try:
        assert ref.git_token == "workflow-tok"
        assert ref.read_token is None
    finally:
        await ref.aclose()


async def test_resolve_tokens_job_token_with_xrepo_sets_read_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "workflow-tok")
    ref = await resolve_tokens(xrepo={"write": ["acme/other"]})
    try:
        assert ref.git_token == "workflow-tok"
        assert ref.read_token == "workflow-tok"
    finally:
        await ref.aclose()


async def test_resolve_tokens_xrepo_object_uses_its_write_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_APP_ID", "12345")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "key")
    monkeypatch.setenv("GITHUB_TOKEN", "workflow-tok")
    minted: list[dict[str, Any]] = []

    async def _mint(**kwargs: Any) -> str:
        minted.append(kwargs)
        return "minted-token"

    monkeypatch.setattr(token_mod, "acquire_installation_token", _mint)
    xrepo = XrepoConfig(mode="explicit", read=["acme/read"], write=["acme/other"])

    ref = await resolve_tokens(
        xrepo=xrepo,
        primary_repo="acme/demo",
        status_checks=True,
        sarif_upload=True,
    )
    try:
        assert minted == [
            {
                "repos": ["acme/demo"],
                "permissions": {
                    "contents": "read",
                    "pull_requests": "write",
                    "issues": "write",
                    "checks": "write",
                    "actions": "read",
                    "security_events": "write",
                },
            },
            {
                "repos": ["acme/demo", "acme/other"],
                "permissions": {"contents": "write", "workflows": "write"},
            },
            {
                "repos": ["acme/read"],
                "permissions": {"contents": "read"},
            },
        ]
        assert ref.read_token == "minted-token"
    finally:
        await ref.aclose()


async def test_resolve_tokens_wire_bodies_keep_api_git_and_read_scopes_separate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """App-token wire requests carry the exact permission and repository matrix."""
    monkeypatch.setenv("GITHUB_APP_ID", "12345")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "key")
    monkeypatch.setenv("GITHUB_APP_INSTALLATION_ID", "7")
    monkeypatch.setenv("GITHUB_TOKEN", "workflow-tok")
    monkeypatch.setattr(token_mod, "_app_jwt", lambda: "app-jwt")
    real_async_client = httpx.AsyncClient
    requests: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(201, json={"token": f"ghs_{len(requests)}"})

    transport = httpx.MockTransport(_handler)
    monkeypatch.setattr(
        token_mod.httpx,
        "AsyncClient",
        lambda *_args, **_kwargs: real_async_client(transport=transport),
    )

    ref = await resolve_tokens(
        push="restricted",
        xrepo=XrepoConfig(
            mode="explicit",
            read=["acme/docs"],
            write=["acme/tools"],
        ),
        primary_repo="acme/demo",
        status_checks=True,
        sarif_upload=True,
    )
    try:
        assert ref.mcp_token == "ghs_1"
        assert ref.git_token == "ghs_2"
        assert ref.read_token == "ghs_3"
        mint_requests = [request for request in requests if request.method == "POST"]
        assert [request.read().decode() for request in mint_requests] == [
            '{"permissions":{"contents":"read","pull_requests":"write","issues":"write",'
            '"checks":"write","actions":"read","security_events":"write"},'
            '"repositories":["demo"]}',
            '{"permissions":{"contents":"write","workflows":"write"},'
            '"repositories":["demo","tools"]}',
            '{"permissions":{"contents":"read"},"repositories":["docs"]}',
        ]
    finally:
        await ref.aclose()

    revoked = [
        request.headers["Authorization"] for request in requests if request.method == "DELETE"
    ]
    assert revoked == ["Bearer ghs_1", "Bearer ghs_2", "Bearer ghs_3"]


async def test_resolve_tokens_disabled_push_wire_body_keeps_git_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_APP_ID", "12345")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "key")
    monkeypatch.setenv("GITHUB_APP_INSTALLATION_ID", "7")
    monkeypatch.setenv("GITHUB_TOKEN", "workflow-tok")
    monkeypatch.setattr(token_mod, "_app_jwt", lambda: "app-jwt")
    real_async_client = httpx.AsyncClient
    requests: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(201, json={"token": f"ghs_{len(requests)}"})

    transport = httpx.MockTransport(_handler)
    monkeypatch.setattr(
        token_mod.httpx,
        "AsyncClient",
        lambda *_args, **_kwargs: real_async_client(transport=transport),
    )

    ref = await resolve_tokens(push="disabled", primary_repo="acme/demo")
    try:
        mint_requests = [request for request in requests if request.method == "POST"]
        assert [request.read().decode() for request in mint_requests] == [
            '{"permissions":{"contents":"read","pull_requests":"write","issues":"write",'
            '"checks":"read","actions":"read"},"repositories":["demo"]}',
            '{"permissions":{"contents":"read"},"repositories":["demo"]}',
        ]
    finally:
        await ref.aclose()


async def test_resolve_tokens_revokes_shared_token_alias_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_APP_ID", "12345")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "key")
    monkeypatch.setenv("GITHUB_TOKEN", "workflow-tok")
    revoked: list[str] = []

    async def _mint(**_kwargs: Any) -> str:
        return "shared-installation-token"

    async def _revoke(token: str) -> None:
        revoked.append(token)

    monkeypatch.setattr(token_mod, "acquire_installation_token", _mint)
    monkeypatch.setattr(token_mod, "revoke_installation_token", _revoke)

    ref = await resolve_tokens(primary_repo="acme/demo")
    await ref.aclose()
    await ref.aclose()

    assert revoked == ["shared-installation-token"]


async def test_resolve_tokens_partial_mint_failure_revokes_before_job_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_APP_ID", "12345")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "key")
    monkeypatch.setenv("GITHUB_TOKEN", "workflow-tok")
    minted: list[dict[str, Any]] = []
    revoked: list[str] = []
    warnings: list[str] = []

    async def _mint(**kwargs: Any) -> str:
        minted.append(kwargs)
        if len(minted) == 2:
            request = httpx.Request("POST", f"{_API}/app/installations/7/access_tokens")
            response = httpx.Response(403, request=request)
            raise httpx.HTTPStatusError("forbidden", request=request, response=response)
        return "partial-api-token"

    async def _revoke(token: str) -> None:
        revoked.append(token)

    monkeypatch.setattr(token_mod, "acquire_installation_token", _mint)
    monkeypatch.setattr(token_mod, "revoke_installation_token", _revoke)
    monkeypatch.setattr(
        token_mod.logger,
        "warning",
        lambda message, *args: warnings.append(message.format(*args)),
    )

    ref = await resolve_tokens(primary_repo="acme/demo")
    try:
        assert ref.mcp_token == "workflow-tok"
        assert ref.git_token == "workflow-tok"
        assert revoked == ["partial-api-token"]
        assert len(warnings) == 1
        assert "Git" in warnings[0]
        assert "HTTP 403" in warnings[0]
        assert "contents:write" in warnings[0]
        assert "workflows:write" in warnings[0]
        assert "partial-api-token" not in warnings[0]
    finally:
        await ref.aclose()
    assert revoked == ["partial-api-token"]


async def test_resolve_tokens_cancellation_revokes_partial_mints_and_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_APP_ID", "12345")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "key")
    monkeypatch.setenv("GITHUB_TOKEN", "workflow-tok")
    minted = 0
    revoked: list[str] = []

    async def _mint(**_kwargs: Any) -> str:
        nonlocal minted
        minted += 1
        if minted == 2:
            raise asyncio.CancelledError
        return "partial-api-token"

    async def _revoke(token: str) -> None:
        revoked.append(token)

    monkeypatch.setattr(token_mod, "acquire_installation_token", _mint)
    monkeypatch.setattr(token_mod, "revoke_installation_token", _revoke)

    with pytest.raises(asyncio.CancelledError):
        await resolve_tokens(primary_repo="acme/demo")

    assert revoked == ["partial-api-token"]
    assert token_mod._mcp_token_value is None


async def test_resolve_tokens_without_any_token_fails_closed() -> None:
    with pytest.raises(ValueError, match="token input is required"):
        await resolve_tokens()


def test_get_job_token_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    """`INPUT_TOKEN` wins, then `GH_TOKEN`, then `GITHUB_TOKEN`."""
    monkeypatch.setenv("INPUT_TOKEN", "input-tok")
    monkeypatch.setenv("GH_TOKEN", "gh-tok")
    monkeypatch.setenv("GITHUB_TOKEN", "workflow-tok")
    assert get_job_token() == "input-tok"
    monkeypatch.delenv("INPUT_TOKEN")
    assert get_job_token() == "gh-tok"
    monkeypatch.delenv("GH_TOKEN")
    assert get_job_token() == "workflow-tok"
    monkeypatch.delenv("GITHUB_TOKEN")
    with pytest.raises(ValueError, match="token input is required"):
        get_job_token()
