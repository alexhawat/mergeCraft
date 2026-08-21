"""W2 DA RED — #379 protocol negotiation and unresolved D12 version fields.

Wave plan: ``.ignorelocal/waves/open-issues-sweep-2026-08-20d-a-engine-wave-plan.md``
Authoring wave: **W2**. Implementation: **W5**.

``tests/cli/test_agent_protocol.py`` already greens flat ``protocol_version`` on
events — do not duplicate those. This module pins (1) the current dual-field
reality (CLI JSON ``schema_version`` vs agent JSONL ``protocol_version``) and
(2) that negotiation / retryability / protocol budgets are absent until W5.

D12 is unresolved: do **not** guess which field survives reconciliation.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from mergecraft.cli.agent_protocol import AGENT_PROTOCOL_VERSION, format_event_line
from mergecraft.cli.global_surface import CLI_JSON_SCHEMA_VERSION, cli_json_dumps

_XFAIL_W5 = pytest.mark.xfail(
    reason="green after W5: protocol negotiation / D12 reconcile",
    strict=False,
)


def _agent_event() -> dict[str, Any]:
    return json.loads(format_event_line("run_started"))


def _cli_payload() -> dict[str, Any]:
    return json.loads(cli_json_dumps({"ok": True}))


# ── Current dual-field reality (already true — do not xfail) ──────────────────


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
    """Current D12 gap: two fields, two surfaces, two literals — no adapter yet.

    W5 must reconcile before either is called stable. This pin does not pick a
    surviving name; it records that they are not the same field today.
    """
    event = _agent_event()
    payload = _cli_payload()
    assert "protocol_version" in event
    assert "schema_version" in payload
    assert "schema_version" not in event
    assert "protocol_version" not in payload
    assert AGENT_PROTOCOL_VERSION != CLI_JSON_SCHEMA_VERSION


def test_agent_protocol_module_has_no_negotiate_export() -> None:
    """Current: ``agent_protocol`` announces a version; it does not negotiate one."""
    from mergecraft.cli import agent_protocol

    assert not callable(getattr(agent_protocol, "negotiate_protocol", None))
    assert not callable(getattr(agent_protocol, "negotiate", None))


# ── Desired W5 contract (xfail) ───────────────────────────────────────────────


@_XFAIL_W5
def test_negotiate_protocol_selects_a_mutually_supported_version() -> None:
    """Happy: a consumer can offer accepted versions and receive a selection."""
    from mergecraft.cli import agent_protocol

    negotiate = getattr(agent_protocol, "negotiate_protocol", None) or getattr(
        agent_protocol, "negotiate", None
    )
    assert callable(negotiate)
    selected = negotiate(accepted=(AGENT_PROTOCOL_VERSION, CLI_JSON_SCHEMA_VERSION))
    assert selected is not None
    assert str(selected) in {AGENT_PROTOCOL_VERSION, CLI_JSON_SCHEMA_VERSION, "1", "1.0.0"}


@_XFAIL_W5
def test_protocol_mismatch_is_retryable() -> None:
    """Error: an unsupported offered version is retryable, not a silent stamp."""
    from mergecraft.cli import agent_protocol

    negotiate = getattr(agent_protocol, "negotiate_protocol", None) or getattr(
        agent_protocol, "negotiate", None
    )
    assert callable(negotiate)
    with pytest.raises(
        (LookupError, ValueError, TypeError), match=r"retry|unsupported|negotiat"
    ) as exc_info:
        negotiate(accepted=("0-unsupported",))
    err = exc_info.value
    retryable = getattr(err, "retryable", None)
    if retryable is None:
        retryable = type(err).__name__.casefold().find("retry") >= 0
    assert retryable


@_XFAIL_W5
def test_protocol_declares_budget_fields_for_negotiation() -> None:
    """Edge: W5 publishes named protocol budget fields (not ad-hoc ``**payload``)."""
    from mergecraft.cli import agent_protocol

    fields = getattr(agent_protocol, "PROTOCOL_BUDGET_FIELDS", None)
    assert fields is not None
    names = {str(item) for item in fields}
    assert "token_budget" in names
    assert "cost_budget_usd" in names or "tool_call_budget" in names


@_XFAIL_W5
def test_d12_exposes_a_version_field_adapter_without_picking_the_survivor() -> None:
    """Happy: W5 records how CLI JSON and agent JSONL relate — name left to impl.

    Assert an adapter exists that mentions both current field names. Do not
    require deleting ``schema_version`` or ``protocol_version``.
    """
    from mergecraft.cli import agent_protocol

    adapter = getattr(agent_protocol, "VERSION_FIELD_ALIASES", None) or getattr(
        agent_protocol, "d12_version_aliases", None
    )
    assert adapter is not None
    blob = str(adapter).casefold()
    assert "schema_version" in blob
    assert "protocol_version" in blob
