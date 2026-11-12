"""Biome ``lint --reporter=json`` output parser.

Biome's JSON reporter writes one object, not ESLint's per-file array::

    {"summary": {...}, "command": "lint", "diagnostics": [
        {"category": "lint/suspicious/noDebugger", "severity": "error",
         "description": "...", "location": {"path": {"file": "src/a.js"},
         "span": [0, 9], "sourceCode": "debugger;\\n"}}]}

``span`` is a UTF-8 byte range, so the line is counted in ``sourceCode`` when
the reporter embeds it, else in the file under ``repo_root``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.analyzers.parsers._common import (
    line_at_byte_offset,
    map_confidence,
    map_native_severity,
    read_repo_text,
    require_json_object,
    resolve_repo_relative_path,
    taxonomy_category,
)

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.manifest import AnalyzerManifest


def _location(diagnostic: dict[str, Any]) -> tuple[str, list[Any] | None, str | None]:
    location = diagnostic.get("location")
    if not isinstance(location, dict):
        return "", None, None
    path_field = location.get("path")
    if isinstance(path_field, dict):
        path = str(path_field.get("file") or "")
    else:
        path = str(path_field or "")
    span = location.get("span")
    source = location.get("sourceCode")
    return (
        path,
        span if isinstance(span, list) else None,
        source if isinstance(source, str) else None,
    )


def parse_biome_json(raw: str, *, manifest: AnalyzerManifest, repo_root: Path) -> list[Finding]:
    """Parse a Biome JSON report; a document without ``diagnostics`` raises ``ValueError``."""
    document = require_json_object(raw, what="biome JSON report")
    diagnostics = document.get("diagnostics")
    if not isinstance(diagnostics, list):
        msg = "biome JSON report has no diagnostics array"
        raise ValueError(msg)

    category = taxonomy_category(manifest)
    findings: list[Finding] = []
    for diagnostic in diagnostics:
        if not isinstance(diagnostic, dict):
            continue
        raw_path, span, source = _location(diagnostic)
        path = resolve_repo_relative_path(raw_path, repo_root=repo_root)
        start_line = end_line = 1
        if span and len(span) >= 1:
            text = source if source is not None else read_repo_text(repo_root, path)
            if text is not None:
                start_line = line_at_byte_offset(text, span[0])
                end_line = line_at_byte_offset(text, span[-1]) if len(span) > 1 else start_line
        rule_id = str(diagnostic.get("category") or "biome")
        findings.append(
            make_finding(
                tool=manifest.id,
                rule_id=rule_id,
                category=category,
                severity=map_native_severity(manifest, str(diagnostic.get("severity") or "error")),
                confidence=map_confidence(None),
                message=str(diagnostic.get("description") or rule_id),
                path=path,
                start_line=start_line,
                end_line=max(end_line, start_line),
                source="analyzer",
            )
        )
    return findings


__all__ = ["parse_biome_json"]
