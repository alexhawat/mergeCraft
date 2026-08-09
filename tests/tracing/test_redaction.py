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


@pytest.mark.xfail(reason="green after W2: redaction before fan-out", strict=False)
def test_redaction_happens_once_before_fan_out() -> None:
    from mergecraft.tracing import MultiSink, RedactingSink, sink_factory

    from mergecraft.config import RepoSettings

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
@pytest.mark.xfail(reason="green after W2: secret value redaction", strict=False)
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
@pytest.mark.xfail(reason="green after W2: deny-key redaction", strict=False)
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
@pytest.mark.xfail(reason="green after W2: attrs payload cap", strict=False)
def test_attrs_payload_capped_with_truncation_marker(
    payload_bytes: int, is_truncated: bool, trace_event_data: dict[str, Any]
) -> None:
    from mergecraft.tracing import TRACE_ATTRS_JSON_MAX_BYTES, cap_event_attrs

    assert TRACE_ATTRS_JSON_MAX_BYTES == 64 * 1024
    trace_event_data["attrs"] = {"payload": "x" * payload_bytes}
    capped = cap_event_attrs(trace_event_data)
    encoded = json.dumps(capped["attrs"], separators=(",", ":")).encode()
    if is_truncated:
        assert capped["attrs"]["truncated"] is True
        assert len(encoded) <= TRACE_ATTRS_JSON_MAX_BYTES
        assert capped["span_id"] == trace_event_data["span_id"]
    else:
        assert capped["attrs"] == trace_event_data["attrs"]
