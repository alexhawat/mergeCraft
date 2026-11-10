"""TruffleHog JSONL output parser.

The field-extraction helpers are public because the SARIF converter in
``scripts/native_output_to_sarif.py`` shares them: the in-Action parser and
the CI evidence artifact must agree on the path, line, and detector name for
the same finding, or the two ingest paths report the same secret differently.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from loguru import logger

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


def line_from_metadata(metadata: dict[str, Any]) -> int:
    data = metadata.get("Data") or metadata
    if isinstance(data, dict):
        filesystem = data.get("Filesystem") or {}
        if isinstance(filesystem, dict) and "line" in filesystem:
            return coerce_line(filesystem.get("line", 1))
    return 1


def path_from_metadata(metadata: dict[str, Any], *, repo_root: Path | None) -> str:
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


def detector_name(item: dict[str, Any]) -> str:
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
    """Parse TruffleHog ``-j`` JSONL, one JSON document per line.

    A single undecodable line (a truncated write, a stray banner) is skipped so
    the findings on every other line survive (#1234). Output where *no*
    non-empty line decodes is still unparsable and raises ``ValueError``, so
    the adapter reports a skipped scan rather than a clean one.
    """
    category = taxonomy_category(manifest)
    findings: list[Finding] = []
    decoded_lines = 0
    invalid_lines = 0
    for index, line in enumerate(raw.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            item = json.loads(stripped)
        except json.JSONDecodeError as exc:
            invalid_lines += 1
            logger.debug("trufflehog: skipping undecodable JSONL line {}: {}", index, exc.msg)
            continue
        decoded_lines += 1
        if not isinstance(item, dict):
            continue
        if item.get("level") and item.get("msg"):
            continue
        metadata = item.get("SourceMetadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        path = path_from_metadata(metadata, repo_root=repo_root)
        start_line = line_from_metadata(metadata)
        verified = bool(item.get("Verified"))
        native_level = "verified" if verified else "unverified"
        detector = detector_name(item)
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
    if invalid_lines and not decoded_lines:
        msg = f"trufflehog output has no decodable JSONL line ({invalid_lines} invalid)"
        raise ValueError(msg)
    return findings


__all__ = [
    "detector_name",
    "line_from_metadata",
    "parse_trufflehog_jsonl",
    "path_from_metadata",
]
