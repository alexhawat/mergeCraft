"""TruffleHog JSONL output parser."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.analyzers.parsers._common import (
    coerce_line,
    map_confidence,
    map_native_severity,
    taxonomy_category,
)

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.manifest import AnalyzerManifest


def _line_from_metadata(metadata: dict[str, Any]) -> int:
    data = metadata.get("Data") or metadata
    if isinstance(data, dict):
        filesystem = data.get("Filesystem") or {}
        if isinstance(filesystem, dict) and "line" in filesystem:
            return coerce_line(filesystem.get("line", 1))
    return 1


def _path_from_metadata(metadata: dict[str, Any]) -> str:
    data = metadata.get("Data") or metadata
    if isinstance(data, dict):
        filesystem = data.get("Filesystem") or {}
        if isinstance(filesystem, dict) and filesystem.get("file"):
            return str(filesystem["file"])
    return "unknown"


def parse_trufflehog_jsonl(
    raw: str, *, manifest: AnalyzerManifest, repo_root: Path
) -> list[Finding]:
    _ = repo_root
    category = taxonomy_category(manifest)
    findings: list[Finding] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        item = json.loads(stripped)
        if not isinstance(item, dict):
            continue
        metadata = item.get("SourceMetadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        path = _path_from_metadata(metadata)
        start_line = _line_from_metadata(metadata)
        verified = bool(item.get("Verified"))
        native_level = "verified" if verified else "unverified"
        detector = str(item.get("DetectorType") or "secret")
        findings.append(
            make_finding(
                tool=manifest.id,
                rule_id=detector,
                category=category,
                severity=map_native_severity(manifest, native_level),
                confidence=map_confidence("likely" if verified else "possible"),
                message=f"{detector} secret detected",
                path=path,
                start_line=start_line,
                end_line=start_line,
                source="analyzer",
                evidence=[f"detector={detector}"],
            )
        )
    return findings


__all__ = ["parse_trufflehog_jsonl"]
