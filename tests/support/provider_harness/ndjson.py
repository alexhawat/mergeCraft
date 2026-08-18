"""NDJSON line helpers for agent stream replay."""

from __future__ import annotations

import json

from tests.support.provider_harness.schema import ResponseBlock


def lines_from_blocks(blocks: list[ResponseBlock]) -> list[str]:
    lines: list[str] = []
    for block in blocks:
        if block.kind == "text" and block.text:
            lines.append(json.dumps({"type": "text", "text": block.text}))
        elif block.kind == "tool_call":
            lines.append(
                json.dumps(
                    {
                        "type": "tool_call",
                        "tool_name": block.tool_name,
                        "tool_call_id": block.tool_call_id,
                        "arguments": block.arguments or {},
                    }
                )
            )
    return lines
