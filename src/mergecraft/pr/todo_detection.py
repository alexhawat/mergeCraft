"""Deterministic TODO/FIXME/HACK scan on diff additions (DG8).

Library surface only — not wired into the review dispatch path yet.  DG7/DG8
follow-on work connects ``scan_todo_additions`` to comment handlers and modes.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

from mergecraft.analyzers.scope import iter_added_diff_lines

_TODO_RE = re.compile(r"\b(TODO|FIXME|HACK)\b", re.IGNORECASE)
_HIGH_RISK_PATH_PARTS = ("auth", "security", "payment", "billing", "migration")

RiskLevel = Literal["low", "medium", "high"]


class TodoFinding(BaseModel):
    """One TODO-like marker introduced by the diff."""

    model_config = ConfigDict(extra="forbid")

    path: str
    line: int
    text: str
    risk_level: RiskLevel


def _risk_level_for(path: str, text: str) -> RiskLevel:
    lowered_path = path.lower()
    if any(part in lowered_path for part in _HIGH_RISK_PATH_PARTS):
        return "high"
    if "before launch" in text.lower() or "hack" in text.lower():
        return "medium"
    return "low"


def scan_todo_additions(diff: str) -> list[TodoFinding]:
    """Return added lines containing TODO, FIXME, or HACK markers."""
    findings: list[TodoFinding] = []
    for path, line, content in iter_added_diff_lines(diff):
        if _TODO_RE.search(content):
            findings.append(
                TodoFinding(
                    path=path,
                    line=line,
                    text=content.strip(),
                    risk_level=_risk_level_for(path, content),
                )
            )
    return findings


__all__ = ["RiskLevel", "TodoFinding", "scan_todo_additions"]
