"""W2 DA — #379 protocol negotiation; D12 dual fields aliased, both survive.

Wave plan: ``.ignorelocal/waves/open-issues-sweep-2026-08-20d-a-engine-wave-plan.md``
Authoring wave: **W2**. Implementation: **W5** (landed — markers removed).

``tests/cli/test_agent_protocol.py`` already greens flat ``protocol_version`` on
events — do not duplicate those. This module pins (1) the dual-field wire
reality (CLI JSON ``schema_version`` vs agent JSONL ``protocol_version``) and
(2) negotiation / retryability / protocol budgets via ``agent_protocol``.

D12 is reconciled via explicit ``negotiate_protocol`` branches for
``schema_version`` and ``protocol_version`` (both names survive on their wire
surfaces; no alias lookup table).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from mergecraft.cli import agent_protocol as agent_protocol_mod
from mergecraft.cli.agent_protocol import (
    AGENT_PROTOCOL_VERSION,
    PROTOCOL_BUDGET_FIELDS,
    ProtocolNegotiationError,
    format_event_line,
    negotiate_protocol,
    protocol_budget_payload,
)
from mergecraft.cli.global_surface import CLI_JSON_SCHEMA_VERSION, cli_json_dumps


def _agent_event() -> dict[str, Any]:
    return json.loads(format_event_line("run_started"))


def _cli_payload() -> dict[str, Any]:
    return json.loads(cli_json_dumps({"ok": True}))


# ── Dual-field wire stamps (both survive; aliased, not collapsed) ─────────────


def test_cli_json_stamps_schema_version() -> None:
    """Current: CLI JSON uses ``schema_version`` (``CLI_JSON_SCHEMA_VERSION``)."""
    payload = _cli_payload()
    assert payload["schema_version"] == CLI_JSON_SCHEMA_VERSION
    assert CLI_JSON_SCHEMA_VERSION == "1.0.0"


def test_agent_jsonl_stamps_flat_protocol_version() -> None:
    """Current: agent JSONL stamps ``protocol_version`` (not a negotiated set)."""
    event = _agent_event()
    assert event["protocol_version"] == AGENT_PROTOCOL_VERSION
    assert AGENT_PROTOCOL_VERSION == "1"


def test_schema_version_and_protocol_version_are_distinct_unreconciled_fields() -> None:
    """D12: two wire fields remain distinct; aliased via adapter, not collapsed.

    CLI JSON stamps ``schema_version``; agent JSONL stamps ``protocol_version``.
    This pin does not pick a surviving name; it records that they are not the
    same field on the wire.
    """
    event = _agent_event()
    payload = _cli_payload()
    assert "protocol_version" in event
    assert "schema_version" in payload
    assert "schema_version" not in event
    assert "protocol_version" not in payload
    assert AGENT_PROTOCOL_VERSION != CLI_JSON_SCHEMA_VERSION


# ── W5 contract (green after protocol negotiation) ────────────────────────────


def test_negotiate_protocol_selects_a_mutually_supported_version() -> None:
    """Happy: a consumer can offer accepted versions and receive a selection."""
    selected = negotiate_protocol(accepted=(AGENT_PROTOCOL_VERSION, CLI_JSON_SCHEMA_VERSION))
    assert selected in {AGENT_PROTOCOL_VERSION, CLI_JSON_SCHEMA_VERSION, "1", "1.0.0"}


def test_protocol_mismatch_is_retryable() -> None:
    """Error: an unsupported offered version is retryable, not a silent stamp."""
    with pytest.raises(ProtocolNegotiationError, match=r"retry|unsupported|negotiat") as exc_info:
        negotiate_protocol(accepted=("0-unsupported",))
    assert exc_info.value.retryable is True


def test_protocol_declares_budget_fields_for_negotiation() -> None:
    """Edge: W5 publishes named protocol budget fields (not ad-hoc ``**payload``)."""
    names = {str(item) for item in PROTOCOL_BUDGET_FIELDS}
    assert "token_budget" in names
    assert "cost_budget_usd" in names
    assert "tool_call_budget" in names


def test_run_started_wire_stamps_protocol_budget_fields() -> None:
    """Happy: ``run_started`` JSONL includes every ``PROTOCOL_BUDGET_FIELDS`` name."""
    event = json.loads(format_event_line("run_started", **protocol_budget_payload()))
    assert event["event"] == "run_started"
    for name in PROTOCOL_BUDGET_FIELDS:
        assert name in event


def test_d12_exposes_a_version_field_adapter_without_picking_the_survivor() -> None:
    """Happy: D12 — both wire field names negotiate via explicit branches, not an alias map.

    ``schema_version`` and ``protocol_version`` remain distinct stamps on CLI JSON
    vs agent JSONL; negotiation selects the matching literal per offered token.
    """
    assert not hasattr(agent_protocol_mod, "VERSION_FIELD_ALIASES")
    schema_selected = negotiate_protocol(accepted=("schema_version",))
    protocol_selected = negotiate_protocol(accepted=("protocol_version",))
    assert schema_selected == CLI_JSON_SCHEMA_VERSION
    assert protocol_selected == AGENT_PROTOCOL_VERSION
    assert schema_selected != protocol_selected


def test_negotiate_protocol_schema_version_token_selects_cli_json_schema() -> None:
    """Unit: offering only ``schema_version`` selects ``CLI_JSON_SCHEMA_VERSION``, not ``1``."""
    selected = negotiate_protocol(accepted=("schema_version",))
    assert selected == CLI_JSON_SCHEMA_VERSION
    assert selected != AGENT_PROTOCOL_VERSION


def test_negotiate_protocol_protocol_version_token_selects_agent_protocol() -> None:
    """Unit: offering only ``protocol_version`` selects ``AGENT_PROTOCOL_VERSION``."""
    selected = negotiate_protocol(accepted=("protocol_version",))
    assert selected == AGENT_PROTOCOL_VERSION


def test_negotiate_protocol_literal_cli_schema_selects_cli_json_schema() -> None:
    """Unit: offering literal ``1.0.0`` still selects ``CLI_JSON_SCHEMA_VERSION``."""
    selected = negotiate_protocol(accepted=("1.0.0",))
    assert selected == CLI_JSON_SCHEMA_VERSION
    assert selected != AGENT_PROTOCOL_VERSION
