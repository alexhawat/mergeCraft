"""``--agent`` wires protocol negotiation (Thermos / #379). D12 dual-field pins stay."""

from __future__ import annotations

import inspect
from io import StringIO
from typing import Any

import pytest

from mergecraft.cli.agent_protocol import (
    AGENT_PROTOCOL_VERSION,
    ProtocolNegotiationError,
    format_event_line,
    negotiate_protocol,
)
from mergecraft.cli.diff_review_cmd import _start_agent_protocol
from mergecraft.cli.global_surface import CLI_JSON_SCHEMA_VERSION, cli_json_dumps


def test_start_agent_protocol_calls_negotiate_protocol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy: ``_start_agent_protocol`` negotiates before emitting JSONL."""
    calls: list[tuple[str, ...]] = []

    def fake_negotiate(*, accepted: Any) -> str:
        calls.append(tuple(str(item) for item in accepted))
        return AGENT_PROTOCOL_VERSION

    monkeypatch.setattr(
        "mergecraft.cli.agent_protocol.negotiate_protocol",
        fake_negotiate,
    )

    class QuietStream:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self._buf = StringIO()

        def run_started(self, **payload: Any) -> None:
            return None

        def phase(self, name: str, **payload: Any) -> None:
            return None

    monkeypatch.setattr("mergecraft.cli.diff_review_cmd.AgentProtocolStream", QuietStream)
    source = inspect.getsource(_start_agent_protocol)
    assert "negotiate_protocol" in source
    stream = _start_agent_protocol()
    assert stream is not None
    assert calls
    offered = set(calls[0])
    assert AGENT_PROTOCOL_VERSION in offered or "protocol_version" in offered


def test_agent_jsonl_stamps_protocol_version_not_schema_version() -> None:
    """D12: agent JSONL events stamp ``protocol_version``, not ``schema_version``."""
    event = __import__("json").loads(format_event_line("run_started"))
    assert event["protocol_version"] == AGENT_PROTOCOL_VERSION
    assert "schema_version" not in event


def test_cli_json_stamps_schema_version_not_protocol_version() -> None:
    """D12: CLI JSON stamps ``schema_version``, not ``protocol_version``."""
    payload = __import__("json").loads(cli_json_dumps({"ok": True}))
    assert payload["schema_version"] == CLI_JSON_SCHEMA_VERSION
    assert "protocol_version" not in payload


def test_negotiate_protocol_is_the_wired_selector() -> None:
    """Unit: the same ``negotiate_protocol`` CLI ``--agent`` imports is selectable."""
    selected = negotiate_protocol(accepted=(AGENT_PROTOCOL_VERSION, CLI_JSON_SCHEMA_VERSION))
    assert selected == AGENT_PROTOCOL_VERSION
    with pytest.raises(ProtocolNegotiationError):
        negotiate_protocol(accepted=("0-unsupported",))
