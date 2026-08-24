"""Agent JSONL protocol for ``mergecraft review --agent`` (CC1, #379)."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Any, TextIO

from mergecraft.cli.global_surface import CLI_JSON_SCHEMA_VERSION
from mergecraft.review.snapshot import REVIEW_PROTOCOL_VERSION as AGENT_PROTOCOL_VERSION

PROTOCOL_BUDGET_FIELDS: tuple[str, ...] = (
    "token_budget",
    "cost_budget_usd",
    "tool_call_budget",
)

_SUPPORTED_NEGOTIATION_VERSIONS: frozenset[str] = frozenset(
    {AGENT_PROTOCOL_VERSION, CLI_JSON_SCHEMA_VERSION}
)


class ProtocolNegotiationError(ValueError):
    """Raised when no mutually supported protocol version can be selected."""

    retryable: bool

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


def negotiate_protocol(*, accepted: Sequence[str]) -> str:
    """Select a mutually supported protocol version from a consumer offer.

    ``schema_version`` ``1.0.0`` (CLI JSON) and ``protocol_version`` ``1``
    (agent JSONL) are equivalent when offered via their field-name tokens.
    The selected literal is the agent wire version when offered, otherwise
    the CLI schema literal.
    """
    offered: set[str] = set()
    for item in accepted:
        token = str(item)
        offered.add(token)
        if token == "schema_version":
            offered.add(CLI_JSON_SCHEMA_VERSION)
        elif token == "protocol_version":
            offered.add(AGENT_PROTOCOL_VERSION)
    overlap = offered & _SUPPORTED_NEGOTIATION_VERSIONS
    if not overlap:
        raise ProtocolNegotiationError(
            "unsupported protocol version: retry negotiation with "
            f"protocol_version={AGENT_PROTOCOL_VERSION} or "
            f"schema_version={CLI_JSON_SCHEMA_VERSION}"
        )
    if AGENT_PROTOCOL_VERSION in overlap:
        return AGENT_PROTOCOL_VERSION
    return CLI_JSON_SCHEMA_VERSION


def accepted_protocol_versions(
    env: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Consumer protocol offer: ``MERGECRAFT_AGENT_PROTOCOL`` or version ``1``."""
    environ = os.environ if env is None else env
    raw = environ.get("MERGECRAFT_AGENT_PROTOCOL", "").strip()
    if not raw:
        return (AGENT_PROTOCOL_VERSION,)
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def protocol_budget_payload() -> dict[str, int | float]:
    """Named budget fields stamped on ``run_started``."""
    from mergecraft.utils.run_bounds import resolve_run_bounds

    bounds = resolve_run_bounds()
    return {
        "token_budget": bounds.token_budget,
        "cost_budget_usd": bounds.cost_budget_usd,
        "tool_call_budget": bounds.tool_call_budget,
    }


def _base_event(event: str, **payload: Any) -> dict[str, Any]:
    return {"event": event, "protocol_version": AGENT_PROTOCOL_VERSION, **payload}


def format_event_line(event: str, **payload: Any) -> str:
    """Serialize one protocol event as a single JSONL line."""
    return json.dumps(_base_event(event, **payload), ensure_ascii=False) + "\n"


class AgentProtocolStream:
    """Write versioned JSONL events for orchestrators consuming ``--agent``."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream or sys.stdout

    def emit(self, event: str, **payload: Any) -> None:
        self._stream.write(format_event_line(event, **payload))
        self._stream.flush()

    def run_started(self, **payload: Any) -> None:
        self.emit("run_started", **payload)

    def phase(self, name: str, **payload: Any) -> None:
        self.emit("phase", name=name, **payload)

    def finding(self, finding: dict[str, Any], **payload: Any) -> None:
        self.emit("finding", finding=finding, **payload)

    def verdict(self, outcome: str, exit_code: int, **payload: Any) -> None:
        self.emit("verdict", outcome=outcome, exit_code=exit_code, **payload)

    def run_finished(self, exit_code: int, **payload: Any) -> None:
        self.emit("run_finished", exit_code=exit_code, **payload)


def finding_event_key(finding: dict[str, Any]) -> str:
    """Stable identity for deduping streamed finding events."""
    fingerprint = finding.get("fingerprint")
    if fingerprint:
        return str(fingerprint)
    rule_id = finding.get("rule_id")
    path = finding.get("path")
    start_line = finding.get("start_line")
    if rule_id is not None:
        return f"{rule_id}:{path}:{start_line}"
    return json.dumps(finding, sort_keys=True, default=str)


def notify_findings(
    on_finding: Callable[[dict[str, Any]], None] | None,
    rows: Sequence[dict[str, Any]],
    *,
    seen: set[str] | None = None,
    streamed_short_ids: dict[str, str] | None = None,
    refresh: bool = False,
) -> set[str]:
    """Call ``on_finding`` once per novel row. Returns the updated seen set.

    When ``refresh`` is true, rows whose batch-resolved ``short_id`` differs from
    the provisional id already streamed are re-emitted once; unchanged ids are not
    duplicated.
    """
    emitted = seen if seen is not None else set()
    short_ids = streamed_short_ids if streamed_short_ids is not None else {}
    if on_finding is None:
        return emitted
    for row in rows:
        key = finding_event_key(row)
        short_id = row.get("short_id")
        if key in emitted:
            if refresh and isinstance(short_id, str) and short_ids.get(key) != short_id:
                on_finding(row)
                short_ids[key] = short_id
            continue
        emitted.add(key)
        if isinstance(short_id, str):
            short_ids[key] = short_id
        on_finding(row)
    return emitted


__all__ = [
    "AGENT_PROTOCOL_VERSION",
    "PROTOCOL_BUDGET_FIELDS",
    "AgentProtocolStream",
    "ProtocolNegotiationError",
    "accepted_protocol_versions",
    "finding_event_key",
    "format_event_line",
    "negotiate_protocol",
    "notify_findings",
    "protocol_budget_payload",
]
