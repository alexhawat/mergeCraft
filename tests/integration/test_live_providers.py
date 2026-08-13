"""W4 live provider completions — structured results, not HTTP 200 (D18).

Credentials missing: these tests **fail** (D9), they do not skip. They are
excluded from ``make test`` via ``integration`` + ``live`` markers. Do not
record live responses into fixtures (convention 7).
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
import pytest

from mergecraft.agents._stream_consumer import StreamSpanAccumulator, consume_stream
from mergecraft.integrations.live_providers import (
    PROVIDER_SECRET_ENV,
    missing_live_credentials,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.live,
]

_MAX_OUTPUT_TOKENS = 16
_TOKEN_BOUND = 64
_TIMEOUT = 45.0


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.fail(f"{name} is required for live provider tests (D9 — fail, do not skip)")
    return value


def _accumulate(agent_name: str, payload: dict[str, Any], output: str) -> StreamSpanAccumulator:
    """Fold a live JSON body into the stream-consumer accumulator (D18)."""
    acc = StreamSpanAccumulator(agent_name=agent_name)
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    event = {"type": "result", "result": output, "usage": usage}

    def handler(accumulator: StreamSpanAccumulator, parsed: dict[str, Any]) -> None:
        if isinstance(parsed.get("usage"), dict):
            accumulator.replace_usage(parsed["usage"])
        accumulator.set_output(str(parsed.get("result") or ""))

    consume_stream(raw_stream=[json.dumps(event)], accumulator=acc, handler=handler)
    assert acc.parsed_event_count >= 1
    assert acc.final_output, "stream consumer produced no final_output (not a structured result)"
    return acc


def _usage_out(acc: StreamSpanAccumulator) -> int:
    usage = acc.to_usage()
    if usage is None:
        return acc.tokens_out
    return usage.output_tokens


def test_anthropic_minimal_completion() -> None:
    key = _require("ANTHROPIC_API_KEY")
    response = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": _MAX_OUTPUT_TOKENS,
            "messages": [{"role": "user", "content": "Reply with the single word ping."}],
        },
        timeout=_TIMEOUT,
    )
    payload = response.json()
    assert "content" in payload, f"Anthropic body is not a structured message: {payload!r}"
    blocks = payload["content"]
    assert isinstance(blocks, list)
    assert blocks, "Anthropic content missing"
    text = "".join(str(block.get("text", "")) for block in blocks if isinstance(block, dict))
    acc = _accumulate("claude", payload, text)
    assert acc.final_output.strip()
    assert _usage_out(acc) <= _TOKEN_BOUND


def test_openai_codex_minimal_completion() -> None:
    key = _require("OPENAI_API_KEY")
    response = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"authorization": f"Bearer {key}"},
        json={
            "model": "gpt-4.1-mini",
            "max_tokens": _MAX_OUTPUT_TOKENS,
            "messages": [{"role": "user", "content": "Reply with the single word ping."}],
        },
        timeout=_TIMEOUT,
    )
    payload = response.json()
    choices = payload.get("choices")
    assert isinstance(choices, list)
    assert choices, f"OpenAI body is not a completion: {payload!r}"
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    assert isinstance(message, dict), "OpenAI choice has no message"
    text = str(message.get("content") or "")
    acc = _accumulate("codex", payload, text)
    assert acc.final_output.strip()
    assert _usage_out(acc) <= _TOKEN_BOUND


def test_gemini_minimal_completion() -> None:
    key = _require("GEMINI_API_KEY")
    response = httpx.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
        params={"key": key},
        json={
            "contents": [{"parts": [{"text": "Reply with the single word ping."}]}],
            "generationConfig": {"maxOutputTokens": _MAX_OUTPUT_TOKENS},
        },
        timeout=_TIMEOUT,
    )
    payload = response.json()
    candidates = payload.get("candidates")
    assert isinstance(candidates, list)
    assert candidates, f"Gemini body is not a generation: {payload!r}"
    content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    assert isinstance(parts, list)
    assert parts, "Gemini candidate has no parts"
    text = "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict))
    usage_meta = payload.get("usageMetadata")
    if isinstance(usage_meta, dict):
        payload = {
            **payload,
            "usage": {
                "input_tokens": usage_meta.get("promptTokenCount") or 0,
                "output_tokens": usage_meta.get("candidatesTokenCount") or 0,
            },
        }
    acc = _accumulate("gemini", payload, text)
    assert acc.final_output.strip()
    assert _usage_out(acc) <= _TOKEN_BOUND


def test_nous_minimal_completion() -> None:
    key = _require("NOUS_API_KEY")
    base = os.environ.get("NOUS_BASE_URL", "https://inference-api.nousresearch.com/v1").rstrip("/")
    response = httpx.post(
        f"{base}/chat/completions",
        headers={"authorization": f"Bearer {key}"},
        json={
            "model": os.environ.get("NOUS_MODEL", "Hermes-4-70B"),
            "max_tokens": _MAX_OUTPUT_TOKENS,
            "messages": [{"role": "user", "content": "Reply with the single word ping."}],
        },
        timeout=_TIMEOUT,
    )
    payload = response.json()
    choices = payload.get("choices")
    assert isinstance(choices, list)
    assert choices, f"Nous body is not a completion: {payload!r}"
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    assert isinstance(message, dict)
    text = str(message.get("content") or "")
    acc = _accumulate("nous", payload, text)
    assert acc.final_output.strip()
    assert _usage_out(acc) <= _TOKEN_BOUND


def test_missing_credential_fails_on_schedule() -> None:
    """D9 — absent keys are a failure on the schedule path, not a skip.

    Guard-deletion: dropping ``github`` from ``PROVIDER_SECRET_ENV`` must fail
    this test. Credential lookup goes through ``missing_live_credentials``.
    """
    event = os.environ.get("GITHUB_EVENT_NAME", "schedule")
    if event == "pull_request":
        pytest.fail("live suite must not be collected on pull_request (convention 6)")
    assert PROVIDER_SECRET_ENV["github"] == "GITHUB_TOKEN"
    provider = os.environ.get("MERGECRAFT_LIVE_PROVIDER", "").strip().lower() or None
    missing = missing_live_credentials(provider)
    assert not missing, f"missing live credentials on {event}: {missing} (D9)"


def test_suite_is_inert_on_pull_request() -> None:
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    assert event != "pull_request", "live provider tests ran on pull_request (convention 6)"


def test_response_shape_matches_stream_consumer_contract() -> None:
    """D18 — a live body must fold into ``StreamSpanAccumulator`` fields."""
    acc = StreamSpanAccumulator(agent_name="contract")
    event = {
        "type": "result",
        "result": "ping",
        "usage": {"input_tokens": 4, "output_tokens": 1},
    }

    def handler(accumulator: StreamSpanAccumulator, parsed: dict[str, Any]) -> None:
        accumulator.replace_usage(
            parsed.get("usage") if isinstance(parsed.get("usage"), dict) else {}
        )
        accumulator.set_output(str(parsed.get("result") or ""))

    consume_stream(raw_stream=[json.dumps(event)], accumulator=acc, handler=handler)
    usage = acc.to_usage()
    assert usage is not None
    assert usage.output_tokens == 1
    assert acc.final_output == "ping"
    assert acc.parsed_event_count == 1
    assert acc.malformed_event_count == 0


def test_live_request_is_token_bounded() -> None:
    """Convention 6 — live requests stay a handful of tokens."""
    assert _MAX_OUTPUT_TOKENS <= _TOKEN_BOUND
    assert _MAX_OUTPUT_TOKENS <= 32
