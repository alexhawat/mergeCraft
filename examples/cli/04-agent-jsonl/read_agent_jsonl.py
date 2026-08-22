#!/usr/bin/env python3
"""Consume mergecraft review --agent JSONL and map exit codes to verdict labels."""

from __future__ import annotations

import json
import sys
from typing import Any

# Named exits from docs/EXIT-CODES.md — branch orchestrators on these, not stderr prose.
EXIT_LABELS: dict[int, str] = {
    0: "pass",
    10: "findings",
    11: "blocked",
    12: "failed",
    20: "inconclusive",
    30: "configuration",
    40: "infra",
    50: "timeout",
    2: "usage",
}


def _load_events() -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in sys.stdin:
        stripped = line.strip()
        if not stripped:
            continue
        events.append(json.loads(stripped))
    return events


def main() -> int:
    events = _load_events()
    kinds = [str(event.get("event")) for event in events]
    verdict = next((event for event in events if event.get("event") == "verdict"), None)
    if verdict is None:
        sys.stderr.write("verdict=missing\n")
        return 1

    exit_code = int(verdict.get("exit_code", 0))
    outcome = str(verdict.get("outcome", "unknown"))
    label = EXIT_LABELS.get(exit_code, "unknown")
    protocol = str(events[0].get("protocol_version", "?")) if events else "?"

    lines = (
        f"protocol_version={protocol}",
        f"events={','.join(kinds)}",
        f"outcome={outcome}",
        f"exit_code={exit_code}",
        f"verdict={label}",
    )
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
