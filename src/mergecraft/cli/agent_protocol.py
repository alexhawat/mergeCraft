"""Agent JSONL protocol for ``mergecraft review --agent`` (CC1)."""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

AGENT_PROTOCOL_VERSION = "1"


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


__all__ = [
    "AGENT_PROTOCOL_VERSION",
    "AgentProtocolStream",
    "format_event_line",
]
