"""luacheck ``--formatter plain`` line parser."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.analyzers.parsers._common import (
    coerce_line,
    map_confidence,
    map_native_severity,
    require_diagnostic_text,
    resolve_repo_relative_path,
    taxonomy_category,
)

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.manifest import AnalyzerManifest

_LINE = re.compile(
    r"^(?P<path>.+):(?P<line>\d+):(?P<col>\d+):\s+"
    r"(?:\((?P<code>[EWC]\d+)\)\s+)?(?P<message>.+)$"
)


def parse_luacheck_text(raw: str, *, manifest: AnalyzerManifest, repo_root: Path) -> list[Finding]:
    category = taxonomy_category(manifest)
    findings: list[Finding] = []
    for line in raw.splitlines():
        match = _LINE.match(line.strip())
        if match is None:
            continue
        code = match.group("code") or "luacheck"
        native = "error" if str(code).startswith("E") else "warning"
        start_line = coerce_line(match.group("line"))
        findings.append(
            make_finding(
                tool=manifest.id,
                rule_id=str(code),
                category=category,
                severity=map_native_severity(manifest, native),
                confidence=map_confidence(None),
                message=match.group("message").strip() or str(code),
                path=resolve_repo_relative_path(match.group("path"), repo_root=repo_root),
                start_line=start_line,
                end_line=start_line,
                source="analyzer",
            )
        )
    require_diagnostic_text(raw, matched=bool(findings), what="luacheck plain")
    return findings


__all__ = ["parse_luacheck_text"]
