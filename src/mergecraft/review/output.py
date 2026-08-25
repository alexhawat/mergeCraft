"""Finding serialization helpers shared by CLI and MCP."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.analyzers.finding import finding_json_record, resolve_finding_short_ids

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mergecraft.analyzers.finding import Finding


def finding_json_records(findings: Sequence[Finding]) -> list[dict[str, Any]]:
    """Serialize findings for structured export with stable short ids."""
    short_ids = resolve_finding_short_ids([row.fingerprint for row in findings])
    return [finding_json_record(row, short_id=short_ids[row.fingerprint]) for row in findings]


__all__ = ["finding_json_records"]
