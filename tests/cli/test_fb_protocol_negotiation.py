"""W3 FB — #400 ``negotiate_protocol`` dead-else regression guards.

Wave plan: ``.ignorelocal/waves/open-issues-sweep-2026-08-22-wave-plan.md``
Authoring wave: **W3** (FB RED). Implementation: **W4** (drop unreachable ``else``).

``tests/cli/test_da_protocol_negotiation.py`` already pins dual-field wire stamps
and budget fields — this module pins FB negotiation contracts only. Tests use
explicit ``schema_version`` / ``protocol_version`` field tokens and version
literals; they do **not** depend on the unreachable ``else`` alias lookup in
``negotiate_protocol`` (D8).
"""

from __future__ import annotations

import pytest

from mergecraft.cli.agent_protocol import (
    AGENT_PROTOCOL_VERSION,
    ProtocolNegotiationError,
    negotiate_protocol,
)
from mergecraft.cli.global_surface import CLI_JSON_SCHEMA_VERSION


@pytest.mark.parametrize(
    "token",
    [
        "0-unsupported",
        "bogus",
        "2",
        "99",
        "schema_version_v2",
    ],
)
def test_negotiate_protocol_rejects_unknown_tokens(token: str) -> None:
    """Error (#400): unknown offered tokens raise ``ProtocolNegotiationError``."""
    with pytest.raises(ProtocolNegotiationError, match=r"unsupported|retry|negotiat"):
        negotiate_protocol(accepted=(token,))


def test_negotiate_protocol_schema_version_field_token() -> None:
    """Happy (#400): ``schema_version`` field token selects CLI JSON schema (explicit branch)."""
    selected = negotiate_protocol(accepted=("schema_version",))
    assert selected == CLI_JSON_SCHEMA_VERSION
    assert selected != AGENT_PROTOCOL_VERSION


def test_negotiate_protocol_protocol_version_field_token() -> None:
    """Happy (#400): ``protocol_version`` field token selects agent protocol (explicit branch)."""
    selected = negotiate_protocol(accepted=("protocol_version",))
    assert selected == AGENT_PROTOCOL_VERSION
    assert selected != CLI_JSON_SCHEMA_VERSION


def test_negotiate_protocol_literal_agent_version() -> None:
    """Happy (#400): literal ``1`` negotiates to ``AGENT_PROTOCOL_VERSION``."""
    selected = negotiate_protocol(accepted=(AGENT_PROTOCOL_VERSION,))
    assert selected == AGENT_PROTOCOL_VERSION


def test_negotiate_protocol_literal_cli_schema_version() -> None:
    """Happy (#400): literal ``1.0.0`` negotiates to ``CLI_JSON_SCHEMA_VERSION``."""
    selected = negotiate_protocol(accepted=(CLI_JSON_SCHEMA_VERSION,))
    assert selected == CLI_JSON_SCHEMA_VERSION
    assert selected != AGENT_PROTOCOL_VERSION


def test_negotiate_protocol_prefers_agent_when_both_literals_offered() -> None:
    """Edge (#400): when both supported literals overlap, agent wire version wins."""
    selected = negotiate_protocol(accepted=(CLI_JSON_SCHEMA_VERSION, AGENT_PROTOCOL_VERSION))
    assert selected == AGENT_PROTOCOL_VERSION
