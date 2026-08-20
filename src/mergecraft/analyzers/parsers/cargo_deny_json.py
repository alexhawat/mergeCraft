"""cargo-deny ``--format json`` JSONL diagnostic parser."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.analyzers.parsers._common import (
    coerce_line,
    iter_json_objects,
    map_confidence,
    map_native_severity,
    resolve_repo_relative_path,
    taxonomy_category,
)

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.manifest import AnalyzerManifest

_SEVERITY_ALIASES: dict[str, str] = {
    "error": "error",
    "warning": "warning",
    "note": "note",
    "help": "note",
}


def _label_location(fields: dict[str, Any], *, repo_root: Path) -> tuple[str, int]:
    labels = fields.get("labels")
    if isinstance(labels, list):
        for label in labels:
            if not isinstance(label, dict):
                continue
            raw_path = str(label.get("file") or label.get("path") or "")
            line = coerce_line(label.get("line", 1))
            if raw_path:
                return resolve_repo_relative_path(raw_path, repo_root=repo_root), line
            if line > 1:
                return "Cargo.toml", line
    return "Cargo.toml", 1


def parse_cargo_deny_json(
    raw: str, *, manifest: AnalyzerManifest, repo_root: Path
) -> list[Finding]:
    category = taxonomy_category(manifest)
    findings: list[Finding] = []
    for item in iter_json_objects(raw):
        if str(item.get("type") or "") != "diagnostic":
            continue
        fields = item.get("fields")
        if not isinstance(fields, dict):
            continue
        native = _SEVERITY_ALIASES.get(str(fields.get("severity") or "warning").casefold())
        if native is None or native not in manifest.severity_map:
            continue
        path, start_line = _label_location(fields, repo_root=repo_root)
        findings.append(
            make_finding(
                tool=manifest.id,
                rule_id=str(fields.get("code") or "cargo-deny"),
                category=category,
                severity=map_native_severity(manifest, native),
                confidence=map_confidence(None),
                message=str(fields.get("message") or "cargo-deny finding"),
                path=path,
                start_line=start_line,
                end_line=start_line,
                source="analyzer",
            )
        )
    return findings


__all__ = ["parse_cargo_deny_json"]
