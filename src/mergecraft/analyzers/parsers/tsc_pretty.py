"""TypeScript ``tsc --pretty false`` diagnostics parser."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.analyzers.parsers._common import (
    coerce_line,
    map_confidence,
    map_native_severity,
    resolve_repo_relative_path,
    taxonomy_category,
)

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.manifest import AnalyzerManifest

# ``file.ts(1,2): error TS1234: message`` (``--pretty false``)
_PAREN_DIAG = re.compile(
    r"^(?P<path>.+)\((?P<line>\d+),(?P<col>\d+)\):\s+"
    r"(?P<level>error|warning)\s+(?P<code>TS\d+):\s+(?P<message>.*)$"
)
# ``file.ts:1:2 - error TS1234: message`` (pretty / some hosts)
_COLON_DIAG = re.compile(
    r"^(?P<path>.+):(?P<line>\d+):(?P<col>\d+)\s+-\s+"
    r"(?P<level>error|warning)\s+(?P<code>TS\d+):\s+(?P<message>.*)$"
)
_ANSI_SGR = re.compile(r"\x1b\[[0-9;]*m")


def parse_tsc_pretty(raw: str, *, manifest: AnalyzerManifest, repo_root: Path) -> list[Finding]:
    category = taxonomy_category(manifest)
    findings: list[Finding] = []
    for line in raw.splitlines():
        stripped = _ANSI_SGR.sub("", line).strip()
        match = _PAREN_DIAG.match(stripped) or _COLON_DIAG.match(stripped)
        if match is None:
            continue
        start_line = coerce_line(match.group("line"))
        findings.append(
            make_finding(
                tool=manifest.id,
                rule_id=match.group("code"),
                category=category,
                severity=map_native_severity(manifest, match.group("level")),
                confidence=map_confidence(None),
                message=match.group("message").strip() or "tsc finding",
                path=resolve_repo_relative_path(match.group("path"), repo_root=repo_root),
                start_line=start_line,
                end_line=start_line,
                source="analyzer",
            )
        )
    return findings


__all__ = ["parse_tsc_pretty"]
