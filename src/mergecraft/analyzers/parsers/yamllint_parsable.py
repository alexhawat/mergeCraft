"""yamllint ``-f parsable`` line parser."""

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
    r"\[(?P<level>error|warning)\]\s+(?P<message>.+)$"
)
_RULE = re.compile(r"\((?P<rule>[^()]+)\)\s*$")


def parse_yamllint_parsable(
    raw: str, *, manifest: AnalyzerManifest, repo_root: Path
) -> list[Finding]:
    category = taxonomy_category(manifest)
    findings: list[Finding] = []
    for line in raw.splitlines():
        match = _LINE.match(line.strip())
        if match is None:
            continue
        message = match.group("message").strip()
        rule_match = _RULE.search(message)
        rule_id = rule_match.group("rule") if rule_match else "yamllint"
        start_line = coerce_line(match.group("line"))
        findings.append(
            make_finding(
                tool=manifest.id,
                rule_id=rule_id,
                category=category,
                severity=map_native_severity(manifest, match.group("level")),
                confidence=map_confidence(None),
                message=message or rule_id,
                path=resolve_repo_relative_path(match.group("path"), repo_root=repo_root),
                start_line=start_line,
                end_line=start_line,
                source="analyzer",
            )
        )
    require_diagnostic_text(raw, matched=bool(findings), what="yamllint parsable")
    return findings


__all__ = ["parse_yamllint_parsable"]
