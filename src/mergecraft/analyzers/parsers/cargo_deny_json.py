"""cargo-deny ``--format json`` JSONL diagnostic parser."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.analyzers.parsers._common import (
    coerce_optional_line,
    load_jsonl_objects,
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


def _package_coordinate(fields: dict[str, Any]) -> str:
    for key in ("package", "crate", "krate"):
        raw = fields.get(key)
        if isinstance(raw, dict):
            name = str(raw.get("name") or "").strip()
            version = str(raw.get("version") or "").strip()
            if name:
                return f"{name} {version}".strip()
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    graphs = fields.get("graphs")
    if not isinstance(graphs, list):
        return ""
    for graph in graphs:
        if not isinstance(graph, dict):
            continue
        krate = graph.get("Krate") or graph.get("krate") or graph.get("package")
        if not isinstance(krate, dict):
            continue
        name = str(krate.get("name") or "").strip()
        version = str(krate.get("version") or "").strip()
        if name:
            return f"{name} {version}".strip()
    return ""


def _label_location(fields: dict[str, Any], *, repo_root: Path) -> tuple[str, int | None]:
    labels = fields.get("labels")
    if isinstance(labels, list):
        for label in labels:
            if not isinstance(label, dict):
                continue
            raw_path = str(label.get("file") or label.get("path") or "")
            line = coerce_optional_line(label.get("line"))
            if raw_path:
                return resolve_repo_relative_path(raw_path, repo_root=repo_root), line
            if line is not None:
                return "Cargo.toml", line
    return "Cargo.toml", None


def parse_cargo_deny_json(
    raw: str, *, manifest: AnalyzerManifest, repo_root: Path
) -> list[Finding]:
    category = taxonomy_category(manifest)
    findings: list[Finding] = []
    for item in load_jsonl_objects(raw):
        if str(item.get("type") or "") != "diagnostic":
            continue
        fields = item.get("fields")
        if not isinstance(fields, dict):
            continue
        native = _SEVERITY_ALIASES.get(str(fields.get("severity") or "warning").casefold())
        if native is None or native not in manifest.severity_map:
            continue
        path, start_line = _label_location(fields, repo_root=repo_root)
        base = str(fields.get("message") or "cargo-deny finding")
        coordinate = _package_coordinate(fields)
        message = f"{base} ({coordinate})" if coordinate and coordinate not in base else base
        findings.append(
            make_finding(
                tool=manifest.id,
                rule_id=str(fields.get("code") or "cargo-deny"),
                category=category,
                severity=map_native_severity(manifest, native),
                confidence=map_confidence(None),
                message=message,
                path=path,
                start_line=start_line,
                end_line=start_line,
                source="analyzer",
            )
        )
    return findings


__all__ = ["parse_cargo_deny_json"]
