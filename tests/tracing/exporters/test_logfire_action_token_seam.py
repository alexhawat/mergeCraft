"""W1.4 — Logfire token action seam (wave plan 15, green after W5)."""

from __future__ import annotations

import pytest
from tests.trust_credentials.support import W5_XFAIL, import_action_symbol

_CANARY = "pylf_v2_lane_b_canary_token_do_not_log"


@W5_XFAIL
def test_input_logfire_token_reaches_build_logfire_sink(monkeypatch: pytest.MonkeyPatch) -> None:
    """D11 — INPUT_LOGFIRE_TOKEN + tracing-to logfire resolves at _build_logfire_sink."""
    pytest.importorskip("logfire")
    export = import_action_symbol("export_tracing_env_from_action_inputs")
    monkeypatch.setenv("INPUT_TRACING", "true")
    monkeypatch.setenv("INPUT_TRACING_TO", "logfire")
    monkeypatch.setenv("INPUT_LOGFIRE_TOKEN", _CANARY)
    monkeypatch.delenv("MERGECRAFT_LOGFIRE_TOKEN", raising=False)

    export()

    from mergecraft.config.settings import TraceSinkEntry
    from mergecraft.tracing.exporters import _build_logfire_sink

    entry = TraceSinkEntry.model_validate({"type": "logfire", "project": "demo"})
    sink = _build_logfire_sink(entry, logfire_module=__import__("logfire"))
    assert sink is not None
    assert getattr(sink, "token", None) == _CANARY or _CANARY in repr(sink)


def test_absent_input_keeps_logfire_no_op_warning_path(
    monkeypatch: pytest.MonkeyPatch, trace_event_payload: dict[str, object]
) -> None:
    """Regression — no INPUT_LOGFIRE_TOKEN keeps exporters.py no-op warning behaviour."""
    pytest.importorskip("logfire")
    import loguru

    monkeypatch.delenv("INPUT_LOGFIRE_TOKEN", raising=False)
    monkeypatch.delenv("MERGECRAFT_LOGFIRE_TOKEN", raising=False)
    from mergecraft.config import RepoSettings
    from mergecraft.tracing import TraceEvent, sink_factory

    settings = RepoSettings.model_validate(
        {"tracing": {"enabled": True, "sinks": [{"type": "logfire", "project": "demo"}]}}
    ).tracing
    captured: list[str] = []
    sink_id = loguru.logger.add(
        lambda record: captured.append(record.record["message"]), level="WARNING"
    )
    try:
        sink = sink_factory(settings)
        sink.write(TraceEvent.model_validate(trace_event_payload))
        sink.flush()
    finally:
        loguru.logger.remove(sink_id)
    assert any("no token resolved" in message.lower() for message in captured)


@W5_XFAIL
def test_empty_input_does_not_clobber_existing_mergecraft_logfire_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty action input must not erase MERGECRAFT_LOGFIRE_TOKEN already in env."""
    export = import_action_symbol("export_tracing_env_from_action_inputs")
    monkeypatch.setenv("MERGECRAFT_LOGFIRE_TOKEN", _CANARY)
    monkeypatch.setenv("INPUT_TRACING", "true")
    monkeypatch.setenv("INPUT_TRACING_TO", "logfire")
    monkeypatch.setenv("INPUT_LOGFIRE_TOKEN", "")
    export()
    import os

    assert os.environ.get("MERGECRAFT_LOGFIRE_TOKEN") == _CANARY


@W5_XFAIL
def test_logfire_token_never_in_model_context_or_prompt_dump(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """tracing/resolve.py:60-62 — token stays on the env seam, not in TracingSettings."""
    export = import_action_symbol("export_tracing_env_from_action_inputs")
    monkeypatch.setenv("INPUT_TRACING", "true")
    monkeypatch.setenv("INPUT_TRACING_TO", "logfire")
    monkeypatch.setenv("INPUT_LOGFIRE_TOKEN", _CANARY)
    export()

    from mergecraft.tracing.resolve import resolve_active_tracing

    settings = resolve_active_tracing()
    dumped = settings.model_dump_json()
    assert _CANARY not in dumped
    assert "logfire_token" not in dumped.lower()


@W5_XFAIL
def test_logfire_token_redacted_in_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    """tracing/redaction.py — LOGFIRE_TOKEN-shaped values are redacted in log output."""
    from mergecraft.tracing.redaction import redact_cli_argv

    argv = ["mergecraft", "review", "--logfire-token", _CANARY, _CANARY]
    redacted = redact_cli_argv(argv)
    joined = " ".join(redacted)
    assert _CANARY not in joined
    assert "LOGFIRE" in joined.upper() or "redact" in joined.lower() or "<redacted>" in joined
