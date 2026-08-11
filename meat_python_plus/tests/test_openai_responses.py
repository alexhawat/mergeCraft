"""W6 contract: OpenAI Responses API + streaming + defaults (Go openai.go)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from meat_python_plus.abridge import Request, abridge
from meat_python_plus.model import Block, Message, Response, Role, text_block
from _parity_helpers import import_or_fail, require_attr
from fixtures.go_parity import (
    GO_DEFAULT_OPENAI_MODEL,
    GO_DEFAULT_REASONING_EFFORT,
    GO_MAX_OPENAI_OUTPUT_TOKENS,
)


def _write_sse_event(payload: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(payload)}\n\n".encode()


def _completed(response_id: str, input_tokens: int, output_tokens: int) -> dict[str, Any]:
    return {
        "type": "response.completed",
        "response": {
            "id": response_id,
            "status": "completed",
            "output": [],
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            },
        },
    }


def test_openai_responses_url() -> None:
    mod = import_or_fail("meat_python_plus.providers.openai_responses")
    url_fn = require_attr(mod, "openai_responses_url")
    assert url_fn("https://api.openai.com") == "https://api.openai.com/v1/responses"
    assert url_fn("https://proxy.example/v1/") == "https://proxy.example/v1/responses"


def test_openai_defaults_match_go_pin() -> None:
    mod = import_or_fail("meat_python_plus.providers.openai_responses")
    assert require_attr(mod, "DEFAULT_OPENAI_MODEL") == GO_DEFAULT_OPENAI_MODEL
    assert require_attr(mod, "DEFAULT_REASONING_EFFORT") == GO_DEFAULT_REASONING_EFFORT
    assert require_attr(mod, "MAX_OPENAI_OUTPUT_TOKENS") == GO_MAX_OPENAI_OUTPUT_TOKENS


def test_openai_responses_streaming_text() -> None:
    events = [
        {
            "type": "response.output_item.done",
            "output_index": 0,
            "item": {
                "id": "msg_1",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "hello"}],
            },
        },
        _completed("resp_text", 7, 3),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/responses")
        body = b"".join(_write_sse_event(ev) for ev in events)
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    mod = import_or_fail("meat_python_plus.providers.openai_responses")
    model_cls = require_attr(mod, "OpenAIResponsesModel")
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    model = model_cls(api_key="test-key", base_url="https://example.com", http_client=client)
    resp = model.generate(
        "sys",
        [Message(role=Role.USER, content=[text_block("hi")])],
        [],
    )
    assert len(resp.content) == 1
    assert resp.content[0].type == "text"
    assert resp.content[0].text == "hello"
    assert resp.content[0].provider == "openai"
    assert '"id":"msg_1"' in json.dumps(resp.content[0].provider_data)


def test_openai_responses_incomplete_is_error() -> None:
    events = [
        {
            "type": "response.incomplete",
            "response": {
                "id": "resp_cut",
                "status": "incomplete",
                "output": [],
                "incomplete_details": {"reason": "max_output_tokens"},
            },
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        body = b"".join(_write_sse_event(ev) for ev in events)
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    mod = import_or_fail("meat_python_plus.providers.openai_responses")
    model_cls = require_attr(mod, "OpenAIResponsesModel")
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    model = model_cls(api_key="k", base_url="https://example.com", http_client=client)
    with pytest.raises(Exception, match="max_output_tokens"):
        model.generate("sys", [Message(role=Role.USER, content=[text_block("hi")])], [])


def test_openai_responses_provider_state_replay_round_trip() -> None:
    diff = "diff --git a/a.go b/a.go\n@@ -1 +1 @@\n-old\n+new\n"
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        payload = json.loads(request.content.decode())
        if calls["count"] == 1:
            assert len(payload["input"]) == 1
            events = [
                {
                    "type": "response.output_item.done",
                    "output_index": 0,
                    "item": {
                        "id": "rs_1",
                        "type": "reasoning",
                        "encrypted_content": "encrypted-turn-1",
                        "summary": [],
                    },
                },
                {
                    "type": "response.output_item.done",
                    "output_index": 1,
                    "item": {
                        "id": "fc_1",
                        "type": "function_call",
                        "status": "completed",
                        "call_id": "call_1",
                        "name": "submit",
                        "arguments": json.dumps(
                            {
                                "remove": [],
                                "replace": [{"line": 99, "old": "new", "new": "..."}],
                                "fold": [],
                                "summary": "Changes the value.",
                            }
                        ),
                    },
                },
                _completed("resp_1", 10, 5),
            ]
        else:
            assert len(payload["input"]) == 4
            reasoning = json.loads(payload["input"][1])
            function_call = json.loads(payload["input"][2])
            function_output = json.loads(payload["input"][3])
            assert reasoning["type"] == "reasoning"
            assert reasoning["encrypted_content"] == "encrypted-turn-1"
            assert function_call["call_id"] == "call_1"
            assert function_output["type"] == "function_call_output"
            events = [
                {
                    "type": "response.output_item.done",
                    "output_index": 0,
                    "item": {
                        "id": "fc_2",
                        "type": "function_call",
                        "status": "completed",
                        "call_id": "call_2",
                        "name": "submit",
                        "arguments": json.dumps(
                            {
                                "remove": [{"start_line": 3, "end_line": 3}],
                                "replace": [{"line": 4, "old": "new", "new": "n..."}],
                                "fold": [],
                                "summary": "Changes the value.",
                            }
                        ),
                    },
                },
                _completed("resp_2", 10, 5),
            ]
        body = b"".join(_write_sse_event(ev) for ev in events)
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    mod = import_or_fail("meat_python_plus.providers.openai_responses")
    model_cls = require_attr(mod, "OpenAIResponsesModel")
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    model = model_cls(api_key="test-key", base_url="https://example.com", http_client=client)
    res = abridge(model, Request(unified_diff=diff, repo_root=""))
    assert calls["count"] == 2
    assert "-old" not in res.smart_diff
    assert "+n..." in res.smart_diff
    assert res.input_tokens == 20
    assert res.output_tokens == 10
