"""The OpenCode prompt fallback must retry only a missing endpoint.

``/message`` may be absent on an older or newer API shape, so a 404/405 there
legitimately falls back to ``/prompt``. Every other status — including 429 and
5xx — may mean the prompt was accepted and is still executing; reposting it
starts a second agent turn on the same session and reports the wrong status.

The contract is: fall back on 404/405 only; every other ``>=400`` returns the
first response unchanged, names the first status, and keeps the 429/5xx
retryable marking.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import pytest

import mergecraft.agents.opencode as oc

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503})
_REPORT_ONLY_STATUSES = (400, 422, 429, 500, 502, 503)
_FALLBACK_STATUSES = (404, 405)


class _StubResponse:
    def __init__(self, *, status_code: int, body: Any = None, text: str = "") -> None:
        self.status_code = status_code
        self._body = body
        self.text = text
        self.content = b"{}" if body is not None else b""

    def json(self) -> Any:
        return self._body


class _RecordingClient:
    """AsyncClient stub answering by URL suffix and recording every call."""

    def __init__(self, routes: dict[str, _StubResponse], calls: list[str]) -> None:
        self._routes = routes
        self._calls = calls

    async def __aenter__(self) -> _RecordingClient:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        del exc
        return False

    async def post(self, url: str, **kwargs: object) -> _StubResponse:
        del kwargs
        self._calls.append(url)
        for suffix, response in self._routes.items():
            if url.endswith(suffix):
                return response
        msg = f"unrouted url: {url}"
        raise AssertionError(msg)


def _route(monkeypatch: MonkeyPatch, routes: dict[str, _StubResponse]) -> list[str]:
    calls: list[str] = []

    def _client(*_args: object, **_kwargs: object) -> _RecordingClient:
        return _RecordingClient(routes, calls)

    monkeypatch.setattr(httpx, "AsyncClient", _client)
    monkeypatch.setattr(oc, "instrument_httpx", lambda _client, tracer=None: None)
    return calls


def _endpoints(calls: list[str]) -> list[str]:
    return [url.rsplit("/", 1)[-1] for url in calls]


@pytest.mark.parametrize("status", _FALLBACK_STATUSES)
async def test_missing_endpoint_falls_back_to_prompt(status: int, monkeypatch: MonkeyPatch) -> None:
    """404/405 mean "no such endpoint / method" — the legacy retry is correct."""
    calls = _route(
        monkeypatch,
        {
            "/message": _StubResponse(status_code=status, text="no such endpoint"),
            "/prompt": _StubResponse(status_code=200, body={"text": "fallback answer"}),
        },
    )

    result = await oc._prompt_session_http(
        base_url="http://127.0.0.1:1", session_id="s1", text="hi", model=None
    )

    assert result.success is True
    assert result.output == "fallback answer"
    assert _endpoints(calls) == ["message", "prompt"]


@pytest.mark.parametrize("status", _REPORT_ONLY_STATUSES)
async def test_live_request_is_not_reposted(status: int, monkeypatch: MonkeyPatch) -> None:
    """Every other >=400 reports the first response once, naming its status."""
    calls = _route(
        monkeypatch,
        {
            "/message": _StubResponse(status_code=status, text="upstream said no"),
            # A 200 here is the trap: the unfixed code reposts and reports success.
            "/prompt": _StubResponse(status_code=200, body={"text": "a second turn"}),
        },
    )

    result = await oc._prompt_session_http(
        base_url="http://127.0.0.1:1", session_id="s1", text="hi", model=None
    )

    assert len(calls) == 1, "a live request must not be reposted"
    assert calls[0].endswith("/message")
    assert result.success is False
    assert result.output is None, "the second endpoint's 200 must never be returned"
    assert result.error is not None
    assert result.error.startswith(f"opencode prompt failed ({status}): "), result.error

    expected_retryable = status in _RETRYABLE_STATUSES
    assert bool(result.metadata.get("retryable")) is expected_retryable, result.metadata


async def test_first_status_is_named_not_the_second(monkeypatch: MonkeyPatch) -> None:
    """The error must carry the status the server actually answered with."""
    _route(
        monkeypatch,
        {
            "/message": _StubResponse(status_code=503, text="gateway busy"),
            "/prompt": _StubResponse(status_code=404, text="legacy endpoint absent"),
        },
    )

    result = await oc._prompt_session_http(
        base_url="http://127.0.0.1:1", session_id="s1", text="hi", model=None
    )

    assert result.success is False
    assert result.error is not None
    assert "(503)" in result.error
    assert "(404)" not in result.error
