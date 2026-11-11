"""Shared offline GitHub doubles for unit tests (audit TST-F1).

* :class:`StrictGitHubClient` is a real :class:`~mergecraft.utils.github.GitHubClient`
  whose HTTP transport is an in-process ``httpx.MockTransport``. Methods a test
  overrides behave as the test says; any request nothing scripted raises
  :class:`UnscriptedGitHubCall` naming the method and path, instead of falling
  through to ``api.github.com``. Subclass it where a test used to subclass
  ``GitHubClient`` and override only the calls it cares about, or pass
  ``routes=`` for REST calls answered by JSON.
* ``offline_token_revoke`` is a pytest fixture (registered as a plugin from
  ``tests/conftest.py``) that replaces the installation-token revoke call with
  a recorder.
"""

from __future__ import annotations

import json as _json
from collections.abc import Mapping
from typing import Any

import httpx
import pytest

from mergecraft.utils.github import GitHubClient

# A route answers one ``(METHOD, path)`` with a JSON body, an ``httpx.Response``
# or a callable taking the request and returning either.
RouteAnswer = Any
RouteKey = tuple[str, str]

_OFFLINE_BASE_URL = "https://github.test"


class UnscriptedGitHubCall(AssertionError):
    """A test double received a GitHub call that no route or override handles."""


class StrictGitHubClient(GitHubClient):
    """``GitHubClient`` whose unknown calls raise instead of reaching the network."""

    def __init__(
        self,
        token: str = "test-token",
        *,
        routes: Mapping[RouteKey, RouteAnswer] | None = None,
        **kwargs: Any,
    ) -> None:
        self.routes: dict[RouteKey, RouteAnswer] = {
            (method.upper(), path.rstrip("/") or "/"): answer
            for (method, path), answer in (routes or {}).items()
        }
        self.unscripted_requests: list[tuple[str, str]] = []
        kwargs["client"] = httpx.AsyncClient(
            base_url=_OFFLINE_BASE_URL,
            transport=httpx.MockTransport(self._answer),
        )
        super().__init__(token, **kwargs)

    def _answer(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.rstrip("/") or "/"
        key = (request.method.upper(), path)
        if key not in self.routes:
            self.unscripted_requests.append(key)
            msg = (
                f"{type(self).__name__} received unscripted GitHub call {key[0]} {key[1]}. "
                "Override the matching client method on the fake or add "
                f"routes={{({key[0]!r}, {key[1]!r}): <json or httpx.Response>}}."
            )
            raise UnscriptedGitHubCall(msg)
        answer = self.routes[key]
        if callable(answer):
            answer = answer(request)
        if isinstance(answer, httpx.Response):
            return answer
        return httpx.Response(
            200,
            content=_json.dumps(answer).encode(),
            headers={"content-type": "application/json"},
        )


@pytest.fixture
def offline_token_revoke(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace installation-token revocation with an offline recorder.

    Returns the list of tokens the code under test asked to revoke. Tests of
    ``revoke_installation_token`` itself drive it through their own fake client
    and do not use this fixture.
    """
    import mergecraft.utils.token as token_mod

    revoked: list[str] = []

    async def _record(token: str) -> None:
        revoked.append(token)

    monkeypatch.setattr(token_mod, "revoke_installation_token", _record)
    monkeypatch.setattr(token_mod, "revoke_github_installation_token", _record)
    return revoked


__all__ = [
    "StrictGitHubClient",
    "UnscriptedGitHubCall",
    "offline_token_revoke",
]
