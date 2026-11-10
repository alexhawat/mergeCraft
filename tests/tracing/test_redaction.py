"""RED contracts for tracing redaction and bounded payloads."""

from __future__ import annotations

import json
from typing import Any

import pytest
from tests.tracing.test_sinks import RecordingSink

DENY_KEYS = (
    "authorization",
    "cookie",
    "api_key",
    "secret",
    "password",
    "access_token",
    "refresh_token",
    "id_token",
    "bearer_token",
    "auth_token",
)


def test_redaction_happens_once_before_fan_out() -> None:
    from mergecraft.config import RepoSettings
    from mergecraft.tracing import MultiSink, RedactingSink, sink_factory

    config = RepoSettings.model_validate(
        {
            "tracing": {
                "enabled": True,
                "sinks": [
                    {"type": "memory"},
                    {"type": "memory"},
                ],
            }
        }
    ).tracing
    sink = sink_factory(config)
    assert isinstance(sink, RedactingSink)
    assert isinstance(sink.inner, MultiSink)
    assert all(not isinstance(child, RedactingSink) for child in sink.inner.sinks)


@pytest.mark.parametrize("secret_value", ["ghp_abcdefghijklmnopqrstuvwxyz123456", "sk-secretvalue"])
def test_no_secret_value_reaches_any_sink(
    secret_value: str, trace_event_data: dict[str, Any]
) -> None:
    from mergecraft.tracing import MultiSink, RedactingSink, TraceEvent

    first, second = RecordingSink(), RecordingSink()
    sink = RedactingSink(MultiSink([first, second]))
    trace_event_data["attrs"] = {"message": f"token={secret_value}"}
    sink.write(TraceEvent.model_validate(trace_event_data))
    serialized = json.dumps([first.events, second.events], default=str)
    assert secret_value not in serialized


@pytest.mark.parametrize("deny_key", DENY_KEYS)
def test_no_deny_key_value_reaches_any_sink(
    deny_key: str, trace_event_data: dict[str, Any]
) -> None:
    from mergecraft.tracing import RedactingSink, TraceEvent

    recording = RecordingSink()
    sink = RedactingSink(recording)
    trace_event_data["attrs"] = {deny_key: "canary-sensitive-value"}
    sink.write(TraceEvent.model_validate(trace_event_data))
    assert "canary-sensitive-value" not in json.dumps(recording.events, default=str)


@pytest.mark.parametrize(
    ("payload_bytes", "is_truncated"),
    [(64 * 1024, False), (64 * 1024 + 1, True)],
)
def test_attrs_payload_capped_with_truncation_marker(
    payload_bytes: int, is_truncated: bool, trace_event_data: dict[str, Any]
) -> None:
    """The boundary is the JSON byte size of the whole ``attrs`` dict (#1252)."""
    from mergecraft.tracing import TRACE_ATTRS_JSON_MAX_BYTES, cap_event_attrs

    assert TRACE_ATTRS_JSON_MAX_BYTES == 64 * 1024
    overhead = len(json.dumps({"payload": ""}).encode())
    trace_event_data["attrs"] = {"payload": "x" * (payload_bytes - overhead)}
    assert len(json.dumps(trace_event_data["attrs"]).encode()) == payload_bytes
    capped = cap_event_attrs(trace_event_data)
    encoded = json.dumps(capped["attrs"], separators=(",", ":")).encode()
    if is_truncated:
        assert capped["attrs"]["truncated"] is True
        assert len(encoded) <= TRACE_ATTRS_JSON_MAX_BYTES
        assert capped["span_id"] == trace_event_data["span_id"]
    else:
        assert capped["attrs"] == trace_event_data["attrs"]


def test_attrs_cap_counts_utf8_bytes_not_characters(trace_event_data: dict[str, Any]) -> None:
    from mergecraft.tracing import cap_event_attrs

    # 20,000 four-byte emoji: 20k characters, 80k UTF-8 bytes.
    trace_event_data["attrs"] = {"payload": "\U0001f600" * 20_000}
    assert cap_event_attrs(trace_event_data)["attrs"] == {"truncated": True}


def test_attrs_cap_counts_nested_values(trace_event_data: dict[str, Any]) -> None:
    from mergecraft.tracing import cap_event_attrs

    trace_event_data["attrs"] = {"outer": {"inner": ["x" * 100_000]}}
    assert cap_event_attrs(trace_event_data)["attrs"] == {"truncated": True}


def test_attrs_cap_counts_many_small_values(trace_event_data: dict[str, Any]) -> None:
    from mergecraft.tracing import cap_event_attrs

    # Each value is far below the cap; together they exceed it.
    trace_event_data["attrs"] = {f"k{i}": "y" * 1000 for i in range(100)}
    assert cap_event_attrs(trace_event_data)["attrs"] == {"truncated": True}


def test_attrs_cap_keeps_small_attrs_and_survives_unencodable(
    trace_event_data: dict[str, Any],
) -> None:
    from mergecraft.tracing import cap_event_attrs

    trace_event_data["attrs"] = {"a": 1, "b": "ok"}
    assert cap_event_attrs(trace_event_data) is trace_event_data
    trace_event_data["attrs"] = {"c": object()}
    assert cap_event_attrs(trace_event_data)["attrs"] == {"truncated": True}
    circular: dict[str, Any] = {}
    circular["self"] = circular
    trace_event_data["attrs"] = circular
    assert cap_event_attrs(trace_event_data)["attrs"] == {"truncated": True}


def test_identifier_attrs_skip_the_entropy_heuristic() -> None:
    """Model slugs and hex run ids are identifiers, not secrets; known secret shapes still go."""
    from mergecraft.tracing.redaction import redact_attrs

    run_id = "749419e680604bc58d270676b0287855"
    out = redact_attrs(
        {
            "model.id": "opencode-go/deepseek-v4.1-flash",
            "gen_ai.request.model": "deepseek-v4.1-flash",
            "review.id": run_id,
            "gen_ai.response.model": "sk-abcdefghijklmnop1234",
            "note": run_id,
        }
    )

    assert out["model.id"] == "opencode-go/deepseek-v4.1-flash"
    assert out["gen_ai.request.model"] == "deepseek-v4.1-flash"
    assert out["review.id"] == run_id
    assert "sk-abcdefghijklmnop1234" not in out["gen_ai.response.model"]
    assert out["note"] != run_id
