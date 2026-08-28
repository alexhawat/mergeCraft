"""RED contracts for Batch BD / #375 — gen_ai usage + identity on ``llm.call`` (W7).

Issue #375: exported ``llm.call`` rows must carry ``gen_ai.usage.*``,
``gen_ai.system``, and ``gen_ai.response.model`` (when known) on the span
itself — not only on a parent ``provider.call``. When a provider reports no
usage, close sites must stamp an explicit unavailable marker instead of
silently omitting usage keys so Logfire NULLs are distinguishable from
"not instrumented".

W8 audits claude / codex / gemini / opencode for driver parity via
``usage_attrs`` / ``response_attrs``.
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx
import pytest
from tests.tracing.conftest import as_sink_value
from tests.tracing.instrumentation.conftest import make_agent_usage
from tests.tracing.streaming.conftest import CLAUDE_TOOL_CALL_STREAM, serialize_stream

from mergecraft.tracing.genai import USAGE_UNAVAILABLE_ATTR

_INPUT_TOKENS = 100
_OUTPUT_TOKENS = 7


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


def _llm_call_events(sink: Any) -> list[Any]:
    return [event for event in sink.events if getattr(event, "kind", None) == "llm.call"]


def _single_llm_call_attrs(sink: Any) -> dict[str, Any]:
    events = _llm_call_events(sink)
    assert len(events) == 1, f"expected one llm.call span, got {len(events)}"
    return events[0].attrs


def _assert_usage_reported_bundle(
    attrs: dict[str, Any],
    *,
    system: str,
    input_tokens: int,
    output_tokens: int,
    response_model: str | None = None,
) -> None:
    """Pin the #375 bundle when the provider reports token usage."""
    assert attrs.get("gen_ai.usage.input_tokens") == input_tokens, attrs
    assert attrs.get("gen_ai.usage.output_tokens") == output_tokens, attrs
    assert attrs.get("gen_ai.system") == system, (
        f"llm.call must stamp gen_ai.system explicitly; expected {system!r}, "
        f"got {attrs.get('gen_ai.system')!r}; keys={sorted(attrs)}"
    )
    if response_model is not None:
        assert attrs.get("gen_ai.response.model") == as_sink_value(response_model), (
            f"llm.call must stamp gen_ai.response.model when known; "
            f"expected {response_model!r}, got {attrs.get('gen_ai.response.model')!r}"
        )
    assert USAGE_UNAVAILABLE_ATTR not in attrs, (
        f"{USAGE_UNAVAILABLE_ATTR} must not be set when usage is reported"
    )


def _assert_usage_unavailable_marker(attrs: dict[str, Any]) -> None:
    """Pin explicit unavailable marking instead of silent omit (#375)."""
    assert attrs.get(USAGE_UNAVAILABLE_ATTR) is True, (
        f"expected {USAGE_UNAVAILABLE_ATTR}=True when provider reports no usage; "
        f"got {attrs.get(USAGE_UNAVAILABLE_ATTR)!r}; keys={sorted(attrs)}"
    )


@pytest.fixture(autouse=True)
def _no_opencode_http_instrumentation(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    opencode_mod = importlib.import_module("mergecraft.agents.opencode")
    monkeypatch.setattr(
        opencode_mod,
        "instrument_httpx",
        lambda client, tracer=None: None,
    )


@pytest.fixture
def opencode_session_response(monkeypatch: pytest.MonkeyPatch) -> Any:
    def _set(body: dict[str, Any]) -> None:
        client = type("_Client", (_StubClient,), {"body": body})
        monkeypatch.setattr(httpx, "AsyncClient", client)

    return _set


@pytest.fixture
def opencode_tracer(monkeypatch: pytest.MonkeyPatch) -> Any:
    from mergecraft.tracing import MemorySink, Tracer

    sink = MemorySink()
    tracer = Tracer(sink=sink, session_id="bd-375", run_id="bd-375-run")
    monkeypatch.setattr("mergecraft.agents.opencode.current_tracer", lambda: tracer)
    return {"sink": sink, "tracer": tracer}


async def test_opencode_llm_call_stamps_gen_ai_identity_when_usage_reported(
    opencode_tracer: Any,
    opencode_session_response: Any,
) -> None:
    """OpenCode HTTP path: usage + ``gen_ai.system`` on the ``llm.call`` span."""
    from mergecraft.agents.opencode import _prompt_session
    from mergecraft.tracing.content import ContentCapture

    opencode_session_response(
        {
            "result": "reviewed",
            "info": {"input_tokens": _INPUT_TOKENS, "output_tokens": _OUTPUT_TOKENS},
        }
    )

    await _prompt_session(
        base_url="http://127.0.0.1:9999",
        session_id="sess-bd-375",
        text="review this",
        model={"providerID": "nous", "modelID": "deepseek-v4-flash"},
        resolved_model="nous/deepseek-v4-flash",
        capture_policy=ContentCapture.METADATA,
    )

    attrs = _single_llm_call_attrs(opencode_tracer["sink"])
    _assert_usage_reported_bundle(
        attrs,
        system="nous",
        input_tokens=_INPUT_TOKENS,
        output_tokens=_OUTPUT_TOKENS,
    )


async def test_opencode_llm_call_marks_usage_unavailable_when_provider_reports_none(
    opencode_tracer: Any,
    opencode_session_response: Any,
) -> None:
    """OpenCode HTTP path: no usage → explicit unavailable marker, not silent omit."""
    from mergecraft.agents.opencode import _prompt_session
    from mergecraft.tracing.content import ContentCapture

    opencode_session_response({"result": "reviewed"})

    await _prompt_session(
        base_url="http://127.0.0.1:9999",
        session_id="sess-bd-375-none",
        text="review this",
        model={"providerID": "nous", "modelID": "x"},
        resolved_model="nous/x",
        capture_policy=ContentCapture.METADATA,
    )

    attrs = _single_llm_call_attrs(opencode_tracer["sink"])
    _assert_usage_unavailable_marker(attrs)
    assert "gen_ai.usage.input_tokens" not in attrs
    assert "gen_ai.usage.output_tokens" not in attrs


def test_claude_streaming_llm_call_stamps_gen_ai_system_on_llm_span(
    patch_driver_subprocess: Any,
    make_agent_run_context: Any,
    captured_streaming_sink: Any,
) -> None:
    """Claude ``stream-json``: ``gen_ai.system`` must live on ``llm.call``, not only parent."""
    from mergecraft.agents.claude import _run_claude_once

    patch_driver_subprocess(
        "mergecraft.agents.claude",
        stdout=serialize_stream(CLAUDE_TOOL_CALL_STREAM),
        stderr="",
        returncode=0,
    )

    ctx = make_agent_run_context(resolved_model="anthropic/claude-sonnet-5")
    result = _run_claude_once(
        cli="/usr/bin/claude",
        prompt="review this diff",
        ctx=ctx,
        mcp_config=str(ctx.tmpdir) + "/mcp.json",
    )
    assert result.success, result.error

    captured_streaming_sink.record()
    llm_spans = captured_streaming_sink.by_kind.get("llm.call", [])
    assert llm_spans, "expected llm.call spans from claude stream"

    for llm_span in llm_spans:
        attrs = llm_span.attrs
        _assert_usage_reported_bundle(
            attrs,
            system="anthropic",
            input_tokens=int(attrs.get("gen_ai.usage.input_tokens") or 0),
            output_tokens=int(attrs.get("gen_ai.usage.output_tokens") or 0),
            response_model="anthropic/claude-sonnet-5",
        )


def _build_tracing_settings() -> Any:
    from mergecraft.config import RepoSettings

    return RepoSettings.model_validate(
        {
            "tracing": {"enabled": True, "sinks": [{"type": "memory"}]},
            "models": ["anthropic/claude-sonnet"],
        }
    )


def _drive_chain(settings: Any, results: list[Any]) -> None:
    import asyncio

    from mergecraft.utils.agent_resolve import run_with_model_chain

    iterator = iter(results)

    async def run_once(_slug: str) -> Any:
        return next(iterator)

    asyncio.run(run_with_model_chain(settings=settings, run_once=run_once))


def test_model_chain_llm_call_stamps_gen_ai_system_when_usage_reported(
    captured_sink: Any,
) -> None:
    """``run_with_model_chain`` chain-level ``llm.call`` carries ``gen_ai.system``."""
    from mergecraft.agents.shared import AgentResult

    settings = _build_tracing_settings()
    usage = make_agent_usage(input_tokens=120, output_tokens=48, cost_usd=0.002)
    _drive_chain(settings, [AgentResult(success=True, usage=usage)])

    captured_sink.record()
    llm_calls = captured_sink.by_kind.get("llm.call", [])
    assert llm_calls, "chain must emit llm.call"

    attrs = llm_calls[0].attrs
    _assert_usage_reported_bundle(
        attrs,
        system="anthropic",
        input_tokens=120,
        output_tokens=48,
        response_model="anthropic/claude-sonnet",
    )


def test_model_chain_llm_call_marks_usage_unavailable_when_no_usage(
    captured_sink: Any,
) -> None:
    """Chain-level ``llm.call`` with ``usage=None`` must mark usage unavailable."""
    from mergecraft.agents.shared import AgentResult

    settings = _build_tracing_settings()
    _drive_chain(settings, [AgentResult(success=True, usage=None, output="done")])

    captured_sink.record()
    llm_calls = captured_sink.by_kind.get("llm.call", [])
    assert llm_calls, "chain must emit llm.call"

    attrs = llm_calls[0].attrs
    _assert_usage_unavailable_marker(attrs)
    assert attrs.get("gen_ai.system") == "anthropic", (
        "provider identity must still be stamped when usage is unavailable"
    )


__all__ = [
    "USAGE_UNAVAILABLE_ATTR",
    "test_claude_streaming_llm_call_stamps_gen_ai_system_on_llm_span",
    "test_model_chain_llm_call_marks_usage_unavailable_when_no_usage",
    "test_model_chain_llm_call_stamps_gen_ai_system_when_usage_reported",
    "test_opencode_llm_call_marks_usage_unavailable_when_provider_reports_none",
    "test_opencode_llm_call_stamps_gen_ai_identity_when_usage_reported",
]
