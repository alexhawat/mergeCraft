"""MyPy JSON-lines output parser."""

from __future__ import annotations

import json
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


def parse_mypy_json(raw: str, *, manifest: AnalyzerManifest, repo_root: Path) -> list[Finding]:
    category = taxonomy_category(manifest)
    findings: list[Finding] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        path = resolve_repo_relative_path(str(item.get("file") or ""), repo_root=repo_root)
        start_line = coerce_line(item.get("line", 1))
        end_line = coerce_line(item.get("end_line", start_line), default=start_line)
        native_level = str(item.get("severity") or "error")
        findings.append(
            make_finding(
                tool=manifest.id,
                rule_id=str(item.get("code") or "mypy"),
                category=category,
                severity=map_native_severity(manifest, native_level),
                confidence=map_confidence(None),
                message=str(item.get("message") or "mypy finding"),
                path=path,
                start_line=start_line,
                end_line=end_line,
                source="analyzer",
            )
        )
    return findings


__all__ = ["parse_mypy_json"]
