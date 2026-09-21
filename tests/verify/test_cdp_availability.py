"""CDP availability probe: ``/json/version`` HTTP 200 is the only green."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from mergecraft.browser.availability import browser_stack_available, cdp_base_url

_DEFAULT_URL = "http://127.0.0.1:9222"


class _FakeResponse:
    """Minimal httpx.Response stand-in carrying only ``status_code``."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


def _client_factory(status_code: int, seen: list[str], *, error: bool = False) -> type[Any]:
    """Return an ``httpx.Client`` substitute that records probed URLs."""

    class _Client:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

        def get(self, url: str) -> _FakeResponse:
            seen.append(url)
            if error:
                raise httpx.ConnectError("connection refused")
            return _FakeResponse(status_code)

    return _Client


def test_cdp_base_url_defaults_to_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MERGECRAFT_CDP_URL", raising=False)
    assert cdp_base_url() == _DEFAULT_URL


def test_cdp_base_url_reads_env_without_trailing_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MERGECRAFT_CDP_URL", "http://127.0.0.1:9333/")
    assert cdp_base_url() == "http://127.0.0.1:9333"


def test_browser_stack_available_true_on_json_version_200(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []
    monkeypatch.setenv("MERGECRAFT_CDP_URL", _DEFAULT_URL)
    monkeypatch.setattr(
        "mergecraft.browser.availability.httpx.Client",
        _client_factory(200, seen),
    )
    assert browser_stack_available() is True
    assert seen == [f"{_DEFAULT_URL}/json/version"]


@pytest.mark.parametrize("status_code", [204, 401, 404, 500])
def test_browser_stack_available_false_on_non_200(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    seen: list[str] = []
    monkeypatch.setattr(
        "mergecraft.browser.availability.httpx.Client",
        _client_factory(status_code, seen),
    )
    assert browser_stack_available() is False
    assert seen == [f"{_DEFAULT_URL}/json/version"]


def test_browser_stack_available_false_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(
        "mergecraft.browser.availability.httpx.Client",
        _client_factory(200, seen, error=True),
    )
    assert browser_stack_available() is False
    assert seen == [f"{_DEFAULT_URL}/json/version"]


def test_browser_stack_available_false_for_closed_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """A refused connection is ``False``, never an exception to the caller."""
    monkeypatch.setenv("MERGECRAFT_CDP_URL", "http://127.0.0.1:1")
    assert browser_stack_available(timeout_s=0.25) is False
