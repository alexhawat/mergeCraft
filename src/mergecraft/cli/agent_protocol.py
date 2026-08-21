"""Agent JSONL protocol for ``mergecraft review --agent`` (CC1)."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, Any, TextIO

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

AGENT_PROTOCOL_VERSION = "1"

# Reusable CLI golden for file 8 RV5 — JSONL agent events, not a second console split (D11).
FIRST_FINDING_GOLDEN_RELPATH = "tests/cli/goldens/review_first_finding.jsonl"


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
) -> set[str]:
    """Call ``on_finding`` once per novel row. Returns the updated seen set."""
    emitted = seen if seen is not None else set()
    if on_finding is None:
        return emitted
    for row in rows:
        key = finding_event_key(row)
        if key in emitted:
            continue
        emitted.add(key)
        on_finding(row)
    return emitted


__all__ = [
    "AGENT_PROTOCOL_VERSION",
    "FIRST_FINDING_GOLDEN_RELPATH",
    "AgentProtocolStream",
    "finding_event_key",
    "format_event_line",
    "notify_findings",
]
