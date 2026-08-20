"""knip ``--reporter json`` output parser (knip 5.42.x shape)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.analyzers.parsers._common import (
    coerce_line,
    map_confidence,
    map_native_severity,
    require_json_object,
    resolve_repo_relative_path,
    taxonomy_category,
)

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.manifest import AnalyzerManifest

_ERROR_TYPES: frozenset[str] = frozenset(
    {"files", "unlisted", "unresolved", "binaries", "duplicates"}
)


def _item_name(item: object) -> str:
    if isinstance(item, dict):
        return str(item.get("name") or item.get("symbol") or "")
    return str(item)


def _item_line(item: object) -> int:
    if isinstance(item, dict):
        return coerce_line(item.get("line", 1))
    return 1


def _issue_finding(
    *,
    manifest: AnalyzerManifest,
    category: str,
    path: str,
    rule_id: str,
    name: str,
    start_line: int,
) -> Finding:
    native = "error" if rule_id in _ERROR_TYPES else "warning"
    message = f"{rule_id}: {name}" if name else rule_id
    return make_finding(
        tool=manifest.id,
        rule_id=rule_id,
        category=category,
        severity=map_native_severity(manifest, native),
        confidence=map_confidence(None),
        message=message,
        path=path,
        start_line=start_line,
        end_line=start_line,
        source="analyzer",
    )


def parse_knip_json(raw: str, *, manifest: AnalyzerManifest, repo_root: Path) -> list[Finding]:
    payload = require_json_object(raw, what="knip JSON output")

    category = taxonomy_category(manifest)
    findings: list[Finding] = []
    unused_files = payload.get("files")
    if isinstance(unused_files, list):
        for file_path in unused_files:
            path = resolve_repo_relative_path(str(file_path), repo_root=repo_root)
            if not path:
                continue
            findings.append(
                _issue_finding(
                    manifest=manifest,
                    category=category,
                    path=path,
                    rule_id="files",
                    name=path,
                    start_line=1,
                )
            )

    issues = payload.get("issues")
    if not isinstance(issues, list):
        return findings
    skip_keys = {"file", "owners"}
    for row in issues:
        if not isinstance(row, dict):
            continue
        path = resolve_repo_relative_path(str(row.get("file") or ""), repo_root=repo_root)
        if not path:
            continue
        for key, value in row.items():
            if key in skip_keys or not isinstance(value, list):
                continue
            for item in value:
                name = _item_name(item)
                if not name:
                    continue
                findings.append(
                    _issue_finding(
                        manifest=manifest,
                        category=category,
                        path=path,
                        rule_id=str(key),
                        name=name,
                        start_line=_item_line(item),
                    )
                )
    return findings


__all__ = ["parse_knip_json"]
