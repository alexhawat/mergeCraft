"""``--agent`` wires env-based protocol negotiation (Thermos / #379). D12 dual-field pins stay."""

from __future__ import annotations

import json
from typing import Any

import pytest
import typer

from mergecraft.cli.agent_protocol import (
    AGENT_PROTOCOL_VERSION,
    PROTOCOL_BUDGET_FIELDS,
    ProtocolNegotiationError,
    accepted_protocol_versions,
    format_event_line,
    negotiate_protocol,
)
from mergecraft.cli.diff_review_cmd import _start_agent_protocol
from mergecraft.cli.exits import CLI_CONFIGURATION_EXIT_CODE
from mergecraft.cli.global_surface import CLI_JSON_SCHEMA_VERSION, cli_json_dumps
from mergecraft.review.snapshot import REVIEW_PROTOCOL_VERSION


def test_agent_protocol_version_aliases_snapshot_protocol() -> None:
    """Unit: agent wire version is the snapshot protocol version."""
    assert AGENT_PROTOCOL_VERSION == REVIEW_PROTOCOL_VERSION
    assert AGENT_PROTOCOL_VERSION == "1"


def test_accepted_protocol_versions_default_is_agent_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy: with no env, the consumer offer is only ``AGENT_PROTOCOL_VERSION``."""
    monkeypatch.delenv("MERGECRAFT_AGENT_PROTOCOL", raising=False)
    offered = accepted_protocol_versions()
    assert offered == (AGENT_PROTOCOL_VERSION,)
    assert CLI_JSON_SCHEMA_VERSION not in offered


def test_accepted_protocol_versions_reads_comma_separated_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy: ``MERGECRAFT_AGENT_PROTOCOL`` is the consumer offer."""
    monkeypatch.setenv("MERGECRAFT_AGENT_PROTOCOL", "1, 1.0.0")
    assert accepted_protocol_versions() == ("1", "1.0.0")


def test_start_agent_protocol_negotiates_default_offer(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Happy: ``_start_agent_protocol`` negotiates the env/default offer, not every version."""
    offered: list[tuple[str, ...]] = []
    real = negotiate_protocol

    def tracking(*, accepted: Any) -> str:
        offered.append(tuple(str(item) for item in accepted))
        return real(accepted=accepted)

    monkeypatch.setattr("mergecraft.cli.agent_protocol.negotiate_protocol", tracking)
    monkeypatch.delenv("MERGECRAFT_AGENT_PROTOCOL", raising=False)
    stream = _start_agent_protocol()
    assert stream is not None
    assert offered == [(AGENT_PROTOCOL_VERSION,)]
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    started = json.loads(lines[0])
    assert started["event"] == "run_started"
    for field in PROTOCOL_BUDGET_FIELDS:
        assert field in started


def test_start_agent_protocol_unsupported_offer_is_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Error: an unsupported env offer is a CLI configuration error."""
    monkeypatch.setenv("MERGECRAFT_AGENT_PROTOCOL", "0-unsupported")
    with pytest.raises(typer.Exit) as exc_info:
        _start_agent_protocol()
    assert exc_info.value.exit_code == CLI_CONFIGURATION_EXIT_CODE


def test_negotiate_protocol_rejects_unsupported_offer() -> None:
    """Error: ``negotiate_protocol`` raises a retryable ``ProtocolNegotiationError``."""
    with pytest.raises(ProtocolNegotiationError, match=r"unsupported|negotiat") as exc_info:
        negotiate_protocol(accepted=("0-unsupported",))
    assert exc_info.value.retryable is True


def test_agent_jsonl_stamps_protocol_version_not_schema_version() -> None:
    """D12: agent JSONL events stamp ``protocol_version``, not ``schema_version``."""
    event = json.loads(format_event_line("run_started"))
    assert event["protocol_version"] == AGENT_PROTOCOL_VERSION
    assert "schema_version" not in event


def test_cli_json_stamps_schema_version_not_protocol_version() -> None:
    """D12: CLI JSON stamps ``schema_version``, not ``protocol_version``."""
    payload = json.loads(cli_json_dumps({"ok": True}))
    assert payload["schema_version"] == CLI_JSON_SCHEMA_VERSION
    assert "protocol_version" not in payload
