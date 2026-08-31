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

_ROTATION_FIRST_REMEDIATION = (
    "Rotate the exposed credential immediately, then remove it from repository "
    "history (for example with git filter-repo or BFG)."
)


def _line_from_metadata(metadata: dict[str, Any]) -> int:
    data = metadata.get("Data") or metadata
    if isinstance(data, dict):
        filesystem = data.get("Filesystem") or {}
        if isinstance(filesystem, dict) and "line" in filesystem:
            return coerce_line(filesystem.get("line", 1))
    return 1


def _path_from_metadata(metadata: dict[str, Any], *, repo_root: Path | None) -> str:
    data = metadata.get("Data") or metadata
    if isinstance(data, dict):
        filesystem = data.get("Filesystem") or {}
        if isinstance(filesystem, dict) and filesystem.get("file"):
            raw_path = str(filesystem["file"])
            if repo_root is not None:
                from mergecraft.analyzers.parsers._common import resolve_repo_relative_path

                return resolve_repo_relative_path(raw_path, repo_root=repo_root)
            return raw_path
    return "unknown"


def _detector_name(item: dict[str, Any]) -> str:
    if item.get("DetectorName"):
        return str(item["DetectorName"])
    if item.get("DetectorType") is not None:
        return str(item["DetectorType"])
    extra = item.get("ExtraData") or {}
    if isinstance(extra, dict) and extra.get("name"):
        return str(extra["name"])
    return "secret"


def parse_trufflehog_jsonl(
    raw: str, *, manifest: AnalyzerManifest, repo_root: Path
) -> list[Finding]:
    category = taxonomy_category(manifest)
    findings: list[Finding] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            item = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        if item.get("level") and item.get("msg"):
            continue
        metadata = item.get("SourceMetadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        path = _path_from_metadata(metadata, repo_root=repo_root)
        start_line = _line_from_metadata(metadata)
        verified = bool(item.get("Verified"))
        native_level = "verified" if verified else "unverified"
        detector = _detector_name(item)
        findings.append(
            make_finding(
                tool=manifest.id,
                rule_id=detector,
                category=category,
                severity=map_native_severity(manifest, native_level),
                confidence=map_confidence("likely" if verified else "possible"),
                message=f"{detector} secret detected at {path}:{start_line}",
                path=path,
                start_line=start_line,
                end_line=start_line,
                source="analyzer",
                evidence=[f"detector={detector}"],
                remediation=_ROTATION_FIRST_REMEDIATION,
            )
        )
    return findings


__all__ = ["parse_trufflehog_jsonl"]
