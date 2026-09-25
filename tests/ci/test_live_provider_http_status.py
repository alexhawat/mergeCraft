"""Live provider tests must report the HTTP status, never the key or the URL.

Each provider test currently parses ``response.json()`` before it looks at the
status, so a 401 or a 404 prints a body-shape assertion with no status at all.
Gemini's credential rides in the query string, so a failure that echoes the
request URL leaks it. This module drives each provider test with a stubbed
error response and pins the message contract.
"""

from __future__ import annotations

import importlib
import json
from typing import Any, Final

import httpx
import pytest

_FAKE_KEY: Final = "fake-live-key-do-not-print"
_DOCUMENTED_NOUS_MODEL: Final = "nous/deepseek/deepseek-v4-flash"

_ANTHROPIC_URL: Final = "https://api.anthropic.com/v1/messages"
_OPENAI_URL: Final = "https://api.openai.com/v1/chat/completions"
_GEMINI_URL: Final = (
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
)
_NOUS_URL: Final = "https://inference-api.nousresearch.com/v1/chat/completions"

_ERROR_PAYLOAD: Final = {"error": {"message": "credential rejected"}}


class _StubResponse:
    """A minimal httpx response carrying a status and an error body."""

    def __init__(self, status_code: int, payload: Any, url: str) -> None:
        self.status_code = status_code
        self._payload = payload
        self.url = url
        self.text = json.dumps(payload)
        self.headers: dict[str, str] = {}

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        request = httpx.Request("POST", self.url)
        raise httpx.HTTPStatusError(
            f"Client error '{self.status_code}' for url '{self.url}'",
            request=request,
            response=httpx.Response(self.status_code, request=request, text=self.text),
        )


def _live_module() -> Any:
    return importlib.import_module("tests.integration.test_live_providers")


def _install_error_response(
    monkeypatch: pytest.MonkeyPatch, url: str, status: int, payload: Any
) -> None:
    module = _live_module()
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "NOUS_API_KEY"):
        monkeypatch.setenv(name, _FAKE_KEY)
    monkeypatch.delenv("NOUS_BASE_URL", raising=False)
    monkeypatch.delenv("NOUS_MODEL", raising=False)
    monkeypatch.delenv("MERGECRAFT_LIVE_NOUS_MODEL", raising=False)
    stub = _StubResponse(status, payload, url)
    monkeypatch.setattr(module.httpx, "post", lambda *args, **kwargs: stub)


def _run_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
    function_name: str,
    url: str,
    status: int,
    payload: Any = _ERROR_PAYLOAD,
) -> str:
    _install_error_response(monkeypatch, url, status, payload)
    module = _live_module()
    with pytest.raises((AssertionError, pytest.fail.Exception)) as excinfo:
        getattr(module, function_name)()
    return str(excinfo.value)


@pytest.mark.parametrize(
    ("function_name", "url", "status"),
    [
        ("test_anthropic_minimal_completion", _ANTHROPIC_URL, 401),
        ("test_openai_codex_minimal_completion", _OPENAI_URL, 401),
        ("test_gemini_minimal_completion", _GEMINI_URL, 404),
        ("test_nous_minimal_completion", _NOUS_URL, 404),
    ],
)
def test_provider_failure_names_status_without_key_or_url(
    monkeypatch: pytest.MonkeyPatch, function_name: str, url: str, status: int
) -> None:
    message = _run_provider_failure(monkeypatch, function_name, url, status)
    assert str(status) in message, (
        f"{function_name} must name HTTP {status} before parsing the body: {message!r}"
    )
    assert _FAKE_KEY not in message, (
        f"{function_name} failure message leaked the credential: {message!r}"
    )
    assert url not in message, (
        f"{function_name} failure message leaked the request URL: {message!r}"
    )


def test_provider_failure_bounds_the_body_it_echoes(monkeypatch: pytest.MonkeyPatch) -> None:
    marker = "X" * 600
    message = _run_provider_failure(
        monkeypatch,
        "test_anthropic_minimal_completion",
        _ANTHROPIC_URL,
        401,
        payload={"error": marker},
    )
    assert "401" in message
    assert marker not in message, (
        f"at most 300 characters of the body may be echoed, got the whole body: {message!r}"
    )


def _capture_nous_model(monkeypatch: pytest.MonkeyPatch, *, override: str | None = None) -> str:
    module = _live_module()
    monkeypatch.setenv("NOUS_API_KEY", _FAKE_KEY)
    monkeypatch.delenv("NOUS_BASE_URL", raising=False)
    monkeypatch.delenv("NOUS_MODEL", raising=False)
    if override is None:
        monkeypatch.delenv("MERGECRAFT_LIVE_NOUS_MODEL", raising=False)
    else:
        monkeypatch.setenv("MERGECRAFT_LIVE_NOUS_MODEL", override)

    captured: dict[str, str] = {}
    payload = {
        "choices": [{"message": {"content": "ping"}}],
        "usage": {"input_tokens": 4, "output_tokens": 1},
    }

    def _post(url: str, **kwargs: Any) -> _StubResponse:
        captured["model"] = kwargs["json"]["model"]
        return _StubResponse(200, payload, url)

    monkeypatch.setattr(module.httpx, "post", _post)
    module.test_nous_minimal_completion()
    return captured["model"]


def test_nous_default_model_is_the_shared_documented_constant() -> None:
    module = _live_module()
    assert getattr(module, "NOUS_DEFAULT_MODEL", None) == _DOCUMENTED_NOUS_MODEL, (
        "the live Nous leg must read the product's documented default model from one "
        "shared constant, not a hard-coded legacy model"
    )


def test_nous_leg_posts_the_documented_default_model(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _capture_nous_model(monkeypatch) == _DOCUMENTED_NOUS_MODEL


def test_nous_leg_model_is_env_overridable(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _capture_nous_model(monkeypatch, override="custom/nous-model") == "custom/nous-model"
