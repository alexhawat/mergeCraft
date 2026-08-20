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
# ``error TS18003: No inputs were found ...`` (project/config, no file location)
_BARE_DIAG = re.compile(r"^(?P<level>error|warning)\s+(?P<code>TS\d+):\s+(?P<message>.*)$")
_ANSI_SGR = re.compile(r"\x1b\[[0-9;]*m")
_PROJECT_PATH = "tsconfig.json"


def parse_tsc_pretty(raw: str, *, manifest: AnalyzerManifest, repo_root: Path) -> list[Finding]:
    category = taxonomy_category(manifest)
    findings: list[Finding] = []
    for line in raw.splitlines():
        stripped = _ANSI_SGR.sub("", line).strip()
        located = _PAREN_DIAG.match(stripped) or _COLON_DIAG.match(stripped)
        bare = None if located is not None else _BARE_DIAG.match(stripped)
        if located is not None:
            start_line: int | None = coerce_line(located.group("line"))
            path = resolve_repo_relative_path(located.group("path"), repo_root=repo_root)
            match = located
        elif bare is not None:
            start_line = None
            path = _PROJECT_PATH
            match = bare
        else:
            continue
        findings.append(
            make_finding(
                tool=manifest.id,
                rule_id=match.group("code"),
                category=category,
                severity=map_native_severity(manifest, match.group("level")),
                confidence=map_confidence(None),
                message=match.group("message").strip() or "tsc finding",
                path=path,
                start_line=start_line,
                end_line=start_line,
                source="analyzer",
            )
        )
    return findings


__all__ = ["parse_tsc_pretty"]
