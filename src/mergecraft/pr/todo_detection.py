"""Deterministic TODO/FIXME/HACK scan on diff additions (DG8)."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_DIFF_FILE_RE = re.compile(r"^diff --git a/(.+?) b/(.+?)$")
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
    current_path: str | None = None
    new_line = 0

    for raw_line in diff.splitlines():
        file_match = _DIFF_FILE_RE.match(raw_line)
        if file_match:
            current_path = file_match.group(2)
            continue

        if current_path is None:
            continue

        hunk_match = _HUNK_RE.match(raw_line)
        if hunk_match:
            new_line = int(hunk_match.group(1))
            continue

        prefix = raw_line[:1]
        if prefix == "+":
            content = raw_line[1:]
            if _TODO_RE.search(content):
                findings.append(
                    TodoFinding(
                        path=current_path,
                        line=new_line,
                        text=content.strip(),
                        risk_level=_risk_level_for(current_path, content),
                    )
                )
            new_line += 1
        elif prefix == " ":
            new_line += 1

    return findings


__all__ = ["RiskLevel", "TodoFinding", "scan_todo_additions"]
