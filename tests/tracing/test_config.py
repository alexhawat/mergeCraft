"""RED contracts for tracing configuration and event shape."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path


def test_tracing_block_parses_and_defaults_unset(tmp_path: Path) -> None:
    """Unset ``tracing.enabled`` is ``None`` (defer); YAML ``enabled: true`` still loads."""
    from mergecraft.config import RepoSettings, load_repo_settings

    default_settings = RepoSettings.model_validate({})
    assert default_settings.tracing.enabled is None

    config = tmp_path / "config.yaml"
    config.write_text(
        "tracing:\n  enabled: true\n  retentionDays: 14\n  sinks:\n"
        "    - type: jsonl_file\n      path: custom/traces\n",
        encoding="utf-8",
    )
    loaded = load_repo_settings(config, root=tmp_path, load_learnings_files=False)
    dumped = loaded.model_dump(by_alias=True)
    assert dumped["tracing"] == {
        "enabled": True,
        "retentionDays": 14,
        "sinks": [{"type": "jsonl_file", "path": "custom/traces"}],
        "redaction": True,
    }


def test_shorthand_normalises_to_sink_list() -> None:
    from mergecraft.config import RepoSettings

    settings = RepoSettings.model_validate({"tracing": {"enabled": True, "to": "local_files"}})
    assert settings.tracing.model_dump(by_alias=True)["sinks"] == [
        {"type": "jsonl_file", "path": ".mergecraft/traces/"}
    ]
    assert not hasattr(settings.tracing, "to")


def test_trace_event_shape(trace_event_data: dict[str, Any]) -> None:
    from mergecraft.tracing import TraceEvent

    event = TraceEvent.model_validate(trace_event_data)
    assert event.model_dump() == trace_event_data


def test_trace_event_accepts_missing_parent_span(trace_event_data: dict[str, Any]) -> None:
    from mergecraft.tracing import TraceEvent

    trace_event_data.pop("parent_span_id")
    event = TraceEvent.model_validate(trace_event_data)
    assert event.parent_span_id is None
    assert event.attrs


def test_trace_event_accepts_empty_attrs(trace_event_data: dict[str, Any]) -> None:
    from mergecraft.tracing import TraceEvent

    trace_event_data["attrs"] = {}
    assert TraceEvent.model_validate(trace_event_data).attrs == {}
