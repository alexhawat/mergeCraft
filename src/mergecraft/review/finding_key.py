"""Finding dedup identity — ``(path, body, line)``."""

from __future__ import annotations


def finding_key(row: dict[str, object]) -> tuple[str, str, str]:
    """Identify a finding by its anchor and body.

    ``line`` is part of the identity: the same defect reported at two call
    sites in one file is two findings, and a key without the line collapses
    them. A row with no line keys on ``""``, which cannot collide with any
    line number.
    """
    line = row.get("line")
    return str(row.get("path", "")), str(row.get("body", "")), "" if line is None else str(line)


__all__ = ["finding_key"]
