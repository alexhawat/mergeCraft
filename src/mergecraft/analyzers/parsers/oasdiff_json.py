"""oasdiff ``breaking --format json`` output parser."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

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

_LEVEL_TO_NATIVE: dict[int, str] = {
    1: "info",
    2: "warning",
    3: "breaking",
}


def _native_level(level: object) -> str:
    if isinstance(level, int):
        return _LEVEL_TO_NATIVE.get(level, "warning")
    if isinstance(level, str) and level.isdigit():
        return _LEVEL_TO_NATIVE.get(int(level), "warning")
    return "warning"


def _source_line(change: dict[str, Any], *, repo_root: Path) -> tuple[str, int]:
    for key in ("revisionSource", "baseSource"):
        source = change.get(key)
        if not isinstance(source, dict):
            continue
        rel = resolve_repo_relative_path(str(source.get("file") or ""), repo_root=repo_root)
        if rel:
            return rel, coerce_line(source.get("line"))
    path = str(change.get("path") or "unknown")
    return path, 1


def parse_oasdiff_json(raw: str, *, manifest: AnalyzerManifest, repo_root: Path) -> list[Finding]:
    payload = json.loads(raw)
    if not isinstance(payload, list):
        msg = "oasdiff JSON output must be an array"
        raise ValueError(msg)

    category = taxonomy_category(manifest)
    findings: list[Finding] = []
    for change in payload:
        if not isinstance(change, dict):
            continue
        native_level = _native_level(change.get("level"))
        rule_id = str(change.get("id") or "breaking-change")
        message = str(change.get("text") or rule_id)
        path, line = _source_line(change, repo_root=repo_root)
        findings.append(
            make_finding(
                tool=manifest.id,
                rule_id=rule_id,
                category=category,
                severity=map_native_severity(manifest, native_level),
                confidence=map_confidence(None),
                message=message,
                path=path,
                start_line=line,
                end_line=line,
                source="analyzer",
                introduced_by_pr="true",
            )
        )
    return findings


__all__ = ["parse_oasdiff_json"]
