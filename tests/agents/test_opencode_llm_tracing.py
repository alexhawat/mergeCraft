"""Batch V — OpenCode ``llm.call`` ModelParams (#295) and HTTP usage (#297).

Wave plan: ``open-issues-sweep-2026-08-19d-wave-plan.md`` (W11-W13).
Pins ``request_attrs(..., params=)`` from gateway ``extra_options`` and
``usage_attrs_from_agent_usage`` omitting zero/unset counters on the HTTP path.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, ClassVar

import httpx
import pytest
from tests.agents.conftest import make_agent_run_context

from mergecraft.agents.opencode import (
    _prompt_session,
    build_security_config,
    opencode_applied_model_params,
)
from mergecraft.tracing.content import ContentCapture

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PINNED_OPENCODE = _REPO_ROOT / "docker" / "agent-clis" / "node_modules" / ".bin" / "opencode"


def _pinned_opencode_cli() -> Path | None:
    return _PINNED_OPENCODE if _PINNED_OPENCODE.is_file() else None


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
    last_payload: ClassVar[dict[str, Any] | None] = None

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    async def __aenter__(self) -> _StubClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def post(self, *args: object, **kwargs: object) -> _StubResponse:
        payload = kwargs.get("json")
        if isinstance(payload, dict):
            type(self).last_payload = payload
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
    """#295 — traced request knobs match the OpenCode config path."""
    session_response({"result": "reviewed"})
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_BASE_URL", "https://inference.example/v1")
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY", "test-key")
    monkeypatch.setenv(
        "MERGECRAFT_CUSTOM_PROVIDER_EXTRA_OPTIONS",
        '{"max_tokens": 4096, "context_limit": 128000}',
    )

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


async def test_opencode_llm_call_omits_unapplied_max_tokens_without_context_limit(
    opencode_tracer: Any,
    session_response: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O4 — max_tokens is not traced when OpenCode limit.output cannot be emitted."""
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
    assert "gen_ai.request.max_tokens" not in attrs


def test_opencode_provider_config_applies_generation_options_on_model_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#295 — gateway generation knobs land on model/agent config, not provider.options."""
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_BASE_URL", "https://inference.example/v1")
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY", "test-key")
    monkeypatch.setenv(
        "MERGECRAFT_CUSTOM_PROVIDER_EXTRA_OPTIONS",
        '{"max_tokens": 4096, "temperature": 0.2, "top_p": 0.9, "context_limit": 128000}',
    )

    ctx = make_agent_run_context(tmp_path, resolved_model="nous/deepseek-v4-flash")
    config = json.loads(build_security_config(ctx, "nous/deepseek-v4-flash"))
    provider = config["provider"]["nous"]
    model_entry = provider["models"]["deepseek-v4-flash"]
    assert provider["options"] == {
        "baseURL": "https://inference.example/v1",
        "apiKey": "test-key",
    }
    assert model_entry["limit"] == {"context": 128_000, "output": 4096}
    assert model_entry["options"] == {"temperature": 0.2, "top_p": 0.9}
    assert config["agent"]["build"]["temperature"] == 0.2
    assert config["agent"]["build"]["top_p"] == 0.9


def test_opencode_provider_config_forwards_extra_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#295 — max_tokens alone stays out of provider.options until limit is known."""
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_BASE_URL", "https://inference.example/v1")
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY", "test-key")
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_EXTRA_OPTIONS", '{"max_tokens": 4096}')

    ctx = make_agent_run_context(tmp_path, resolved_model="nous/deepseek-v4-flash")
    config = json.loads(build_security_config(ctx, "nous/deepseek-v4-flash"))
    provider = config["provider"]["nous"]
    assert provider["options"] == {
        "baseURL": "https://inference.example/v1",
        "apiKey": "test-key",
    }
    assert "limit" not in provider["models"]["deepseek-v4-flash"]
    assert "options" not in provider["models"]["deepseek-v4-flash"]


def test_opencode_model_limit_requires_context_and_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OpenCode 1.18.x rejects partial ``limit`` objects — emit both or omit."""
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_BASE_URL", "https://inference.example/v1")
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY", "test-key")
    monkeypatch.setenv(
        "MERGECRAFT_CUSTOM_PROVIDER_EXTRA_OPTIONS",
        '{"max_tokens": 4096, "context_limit": 128000}',
    )

    ctx = make_agent_run_context(tmp_path, resolved_model="nous/deepseek-v4-flash")
    config = json.loads(build_security_config(ctx, "nous/deepseek-v4-flash"))
    model_entry = config["provider"]["nous"]["models"]["deepseek-v4-flash"]
    assert model_entry["limit"] == {"context": 128_000, "output": 4096}


@pytest.mark.skipif(_pinned_opencode_cli() is None, reason="pinned opencode CLI not installed")
def test_opencode_security_config_validates_against_pinned_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Generated harness config must load under the pinned OpenCode CLI schema."""
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_BASE_URL", "https://inference.example/v1")
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY", "test-key")
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_EXTRA_OPTIONS", '{"max_tokens": 4096}')

    ctx = make_agent_run_context(tmp_path, resolved_model="nous/deepseek-v4-flash")
    config_path = tmp_path / "opencode.json"
    config_path.write_text(build_security_config(ctx, "nous/deepseek-v4-flash"))

    cli = _pinned_opencode_cli()
    assert cli is not None
    env = {**os.environ, "OPENCODE_CONFIG": str(config_path)}
    result = subprocess.run(
        [str(cli), "debug", "config"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_resolve_model_params_from_singleton_extra_options_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#295 — applied-params helper reads singleton extra_options env."""
    monkeypatch.delenv("MERGECRAFT_CUSTOM_PROVIDER_BASE_URL", raising=False)
    monkeypatch.delenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY", raising=False)
    monkeypatch.delenv("MERGECRAFT_CUSTOM_PROVIDER_EXTRA_OPTIONS", raising=False)
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_BASE_URL", "https://inference.example/v1")
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY", "test-key")
    monkeypatch.setenv(
        "MERGECRAFT_CUSTOM_PROVIDER_EXTRA_OPTIONS",
        '{"max_tokens": 4096, "context_limit": 128000}',
    )

    params = opencode_applied_model_params("nous/deepseek-v4-flash")
    assert params is not None
    assert params.max_tokens == 4096


def test_resolve_model_params_from_nous_preset_provider_map(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#295 — registered nous path resolves applied ModelParams."""
    from tests.cli.support_provider_registry import bootstrap_nous_registry

    for key in (
        "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL",
        "MERGECRAFT_CUSTOM_PROVIDER_API_KEY",
        "MERGECRAFT_CUSTOM_PROVIDER_EXTRA_OPTIONS",
        "MERGECRAFT_PROVIDER_EXTRA_OPTIONS",
    ):
        monkeypatch.delenv(key, raising=False)
    bootstrap_nous_registry(tmp_path, monkeypatch, model_id="deepseek/deepseek-v4-flash")
    monkeypatch.setenv(
        "MERGECRAFT_PROVIDER_EXTRA_OPTIONS",
        '{"nous": {"max_tokens": 8192, "temperature": 0.2, "context_limit": 64000}}',
    )

    params = opencode_applied_model_params("nous/deepseek-v4-flash")
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
