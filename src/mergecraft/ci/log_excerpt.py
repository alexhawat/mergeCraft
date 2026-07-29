"""Log excerpt and index extraction for CI pipeline logs (K1.2 excerpt strategy)."""

from __future__ import annotations

import re
from typing import Any, Literal

LogType = Literal["error", "warning", "failure", "trace"]


def analyze_log(logs: str, excerpt_lines: int = 80) -> dict[str, Any]:
    """Index error markers and build a focused excerpt from raw workflow logs."""
    clean = re.sub(r"\x1b\[[0-9;]*m", "", logs)
    lines = clean.split("\n")
    total = len(lines)
    index: list[dict[str, Any]] = []
    patterns: list[tuple[LogType, re.Pattern[str], re.Pattern[str] | None]] = [
        ("error", re.compile(r"##\[error\]", re.I), None),
        ("error", re.compile(r"\bError:", re.I), None),
        ("error", re.compile(r"\bERR_", re.I), None),
        ("error", re.compile(r"exit code [1-9]", re.I), None),
        ("warning", re.compile(r"##\[warning\]", re.I), None),
        ("warning", re.compile(r"\bWARN\b", re.I), re.compile(r"apt|dpkg|Reading package", re.I)),
        ("failure", re.compile(r"\d+ failed", re.I), None),
        ("failure", re.compile(r"FAIL\b", re.I), None),
        ("failure", re.compile(r"[✕✗×]"), None),
        ("trace", re.compile(r"^\s+at\s+", re.I), None),
    ]
    for i, line in enumerate(lines):
        for log_type, pattern, skip in patterns:
            if pattern.search(line):
                if skip and skip.search(line):
                    continue
                if log_type == "trace" and index and index[-1]["type"] == "trace":
                    continue
                truncated = line[:117] + "..." if len(line) > 120 else line
                index.append({"line": i + 1, "content": truncated.strip(), "type": log_type})
                break
    error_line = -1
    for i in range(len(lines) - 1, -1, -1):
        if re.search(r"##\[error\]", lines[i], re.I):
            error_line = i
            break
    if error_line == -1:
        start = max(0, total - excerpt_lines)
        end = total
    else:
        context_after = 5
        context_before = excerpt_lines - context_after
        start = max(0, error_line - context_before)
        end = min(total, error_line + context_after)
    return {
        "totalLines": total,
        "index": index,
        "excerpt": {
            "content": "\n".join(lines[start:end]),
            "startLine": start + 1,
            "endLine": end,
        },
    }


__all__ = ["LogType", "analyze_log"]
