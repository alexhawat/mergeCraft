"""Batch V — OpenCode ``llm.call`` ModelParams (#295) and HTTP usage (#297).

Wave plan: ``open-issues-sweep-2026-08-19d-wave-plan.md`` (W11-W13).
Pins ``request_attrs(..., params=)`` from gateway ``extra_options`` and
``usage_attrs_from_agent_usage`` omitting zero/unset counters on the HTTP path.
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx
import pytest

from mergecraft.agents.opencode import _prompt_session
from mergecraft.tracing.content import ContentCapture

_INPUT = 100
_OUTPUT = 7


class _StubResponse:
    def __init__(self, body: dict[str, Any]) -> None:
        self._body = body
        self.status_code = 200
        self.content = b"{}"
        self.text = "{}"

    def json(self) -> dict[str, Any]:
        return self._body


class _StubClient:
    body: ClassVar[dict[str, Any]] = {}

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    async def __aenter__(self) -> _StubClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def post(self, *args: object, **kwargs: object) -> _StubResponse:
        return _StubResponse(type(self).body)


@pytest.fixture(autouse=True)
def _no_http_instrumentation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "mergecraft.agents.opencode.instrument_httpx",
        lambda client, tracer=None: None,
    )


@pytest.fixture
def session_response(monkeypatch: pytest.MonkeyPatch) -> Any:
    def _set(body: dict[str, Any]) -> None:
        client = type("_Client", (_StubClient,), {"body": body})
        monkeypatch.setattr(httpx, "AsyncClient", client)

    return _set


@pytest.fixture
def opencode_tracer(monkeypatch: pytest.MonkeyPatch) -> Any:
    from mergecraft.tracing import MemorySink, Tracer

    sink = MemorySink()
    tracer = Tracer(sink=sink, session_id="oc-trace", run_id="oc-run")
    monkeypatch.setattr("mergecraft.agents.opencode.current_tracer", lambda: tracer)
    return {"sink": sink, "tracer": tracer}


def _llm_call_attrs(opencode_tracer: Any) -> dict[str, Any]:
    events = [
        event
        for event in opencode_tracer["sink"].events
        if getattr(event, "kind", None) == "llm.call"
    ]
    assert len(events) == 1, f"expected one llm.call span, got {len(events)}"
    return events[0].attrs


async def test_opencode_llm_call_stamps_max_tokens_at_metadata_capture(
    opencode_tracer: Any,
    session_response: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#295 — request knobs ship even when content capture is capped at metadata."""
    session_response({"result": "reviewed"})
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_BASE_URL", "https://inference.example/v1")
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY", "test-key")
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_EXTRA_OPTIONS", '{"max_tokens": 4096}')

    await _prompt_session(
        base_url="http://127.0.0.1:9999",
        session_id="sess-1",
        text="review this",
        model={"providerID": "nous", "modelID": "deepseek-v4-flash"},
        resolved_model="nous/deepseek-v4-flash",
        capture_policy=ContentCapture.METADATA,
    )

    attrs = _llm_call_attrs(opencode_tracer)
    assert attrs.get("gen_ai.request.model") == "nous/deepseek-v4-flash"
    assert attrs.get("gen_ai.request.max_tokens") == 4096


def test_resolve_model_params_from_singleton_extra_options_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#295 — un-mocked resolver reads singleton ``extra_options`` env."""
    monkeypatch.delenv("MERGECRAFT_CUSTOM_PROVIDER_BASE_URL", raising=False)
    monkeypatch.delenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY", raising=False)
    monkeypatch.delenv("MERGECRAFT_CUSTOM_PROVIDER_EXTRA_OPTIONS", raising=False)
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_BASE_URL", "https://inference.example/v1")
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY", "test-key")
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_EXTRA_OPTIONS", '{"max_tokens": 4096}')

    from mergecraft.agents.openai_compatible_gateways import resolve_model_params_for_model

    params = resolve_model_params_for_model("nous/deepseek-v4-flash")
    assert params is not None
    assert params.max_tokens == 4096


def test_resolve_model_params_from_nous_preset_provider_map(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#295 — named preset path resolves ``MERGECRAFT_PROVIDER_EXTRA_OPTIONS``."""
    for key in (
        "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL",
        "MERGECRAFT_CUSTOM_PROVIDER_API_KEY",
        "MERGECRAFT_CUSTOM_PROVIDER_EXTRA_OPTIONS",
        "MERGECRAFT_PROVIDER_EXTRA_OPTIONS",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("NOUS_API_KEY", "test-nous-key")
    monkeypatch.setenv(
        "MERGECRAFT_PROVIDER_EXTRA_OPTIONS",
        '{"nous": {"max_tokens": 8192, "temperature": 0.2}}',
    )

    from mergecraft.agents.openai_compatible_gateways import resolve_model_params_for_model

    params = resolve_model_params_for_model("nous/deepseek-v4-flash")
    assert params is not None
    assert params.max_tokens == 8192
    assert params.temperature == 0.2


async def test_opencode_llm_call_stamps_usage_from_http_response(
    opencode_tracer: Any,
    session_response: Any,
) -> None:
    """#297 — token counters from the session HTTP response reach the span."""
    session_response(
        {
            "result": "reviewed",
            "info": {"input_tokens": _INPUT, "output_tokens": _OUTPUT},
        }
    )

    await _prompt_session(
        base_url="http://127.0.0.1:9999",
        session_id="sess-1",
        text="review this",
        model={"providerID": "nous", "modelID": "x"},
        resolved_model="nous/x",
        capture_policy=ContentCapture.METADATA,
    )

    attrs = _llm_call_attrs(opencode_tracer)
    assert attrs.get("gen_ai.usage.input_tokens") == _INPUT
    assert attrs.get("gen_ai.usage.output_tokens") == _OUTPUT


async def test_opencode_llm_call_omits_zero_input_tokens_when_only_output_reported(
    opencode_tracer: Any,
    session_response: Any,
) -> None:
    """O4 — output-only usage must not zero-fill ``gen_ai.usage.input_tokens``."""
    session_response({"result": "reviewed", "info": {"output_tokens": _OUTPUT}})

    await _prompt_session(
        base_url="http://127.0.0.1:9999",
        session_id="sess-1",
        text="review this",
        model=None,
        resolved_model=None,
        capture_policy=ContentCapture.METADATA,
    )

    attrs = _llm_call_attrs(opencode_tracer)
    assert attrs.get("gen_ai.usage.output_tokens") == _OUTPUT
    assert "gen_ai.usage.input_tokens" not in attrs


async def test_opencode_llm_call_omits_usage_attrs_when_response_has_no_usage(
    opencode_tracer: Any,
    session_response: Any,
) -> None:
    """O4 — absent usage must omit attrs; never zero-fill."""
    session_response({"result": "reviewed"})

    await _prompt_session(
        base_url="http://127.0.0.1:9999",
        session_id="sess-1",
        text="review this",
        model=None,
        resolved_model=None,
        capture_policy=ContentCapture.METADATA,
    )

    attrs = _llm_call_attrs(opencode_tracer)
    assert "gen_ai.usage.input_tokens" not in attrs
    assert "gen_ai.usage.output_tokens" not in attrs
