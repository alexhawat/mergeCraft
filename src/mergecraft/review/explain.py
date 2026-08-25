"""Finding explanation payloads shared by CLI and MCP."""

from __future__ import annotations

from typing import Any


def finding_explain_payload(
    finding_id: str,
    packet: dict[str, Any],
    *,
    review_id: str | None = None,
) -> dict[str, Any]:
    """Build the structured explain payload for a stored finding packet."""
    state = packet.get("state", "unverified")
    kinds = packet.get("kinds", [])
    kinds_text = ", ".join(str(item) for item in kinds) if isinstance(kinds, list) else "none"
    payload: dict[str, Any] = {
        "verb": "explain",
        "finding_id": finding_id,
        "paths": [],
        "summary": f"Finding {finding_id} is {state} (kinds: {kinds_text}).",
        "packet": packet,
    }
    if review_id is not None:
        payload["review_id"] = review_id
    return payload


__all__ = ["finding_explain_payload"]
