"""oxlint ``--format json`` output parser.

oxlint's JSON reporter writes miette-style diagnostics, not ESLint JSON: a bare
array in older releases, wrapped as ``{"diagnostics": [...], ...}`` in newer
ones. Each diagnostic carries ``message``, ``code`` (``eslint(no-debugger)``),
``severity``, ``filename`` and ``labels[].span``. A span has ``line`` when the
release reports it; otherwise its UTF-8 byte ``offset`` is counted in the file
under ``repo_root``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.analyzers.parsers._common import (
    coerce_line,
    line_at_byte_offset,
    load_json,
    map_confidence,
    map_native_severity,
    read_repo_text,
    resolve_repo_relative_path,
    taxonomy_category,
)

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.manifest import AnalyzerManifest


def _diagnostics(raw: str) -> list[Any]:
    payload = load_json(raw)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("diagnostics"), list):
        return list(payload["diagnostics"])
    msg = "oxlint JSON output must be a diagnostics array or an object with diagnostics"
    raise ValueError(msg)


def _line(diagnostic: dict[str, Any], *, repo_root: Path, path: str) -> int:
    labels = diagnostic.get("labels")
    if not isinstance(labels, list) or not labels or not isinstance(labels[0], dict):
        return 1
    span = labels[0].get("span")
    if not isinstance(span, dict):
        return 1
    if span.get("line") is not None:
        return coerce_line(span.get("line"))
    offset = span.get("offset")
    if isinstance(offset, int) and not isinstance(offset, bool):
        text = read_repo_text(repo_root, path)
        if text is not None:
            return line_at_byte_offset(text, offset)
    return 1


def parse_oxlint_json(raw: str, *, manifest: AnalyzerManifest, repo_root: Path) -> list[Finding]:
    """Parse oxlint JSON diagnostics; any other document raises ``ValueError``."""
    category = taxonomy_category(manifest)
    findings: list[Finding] = []
    for diagnostic in _diagnostics(raw):
        if not isinstance(diagnostic, dict):
            continue
        path = resolve_repo_relative_path(
            str(diagnostic.get("filename") or ""), repo_root=repo_root
        )
        line = _line(diagnostic, repo_root=repo_root, path=path)
        rule_id = str(diagnostic.get("code") or "oxlint")
        findings.append(
            make_finding(
                tool=manifest.id,
                rule_id=rule_id,
                category=category,
                severity=map_native_severity(
                    manifest, str(diagnostic.get("severity") or "warning")
                ),
                confidence=map_confidence(None),
                message=str(diagnostic.get("message") or rule_id),
                path=path,
                start_line=line,
                end_line=line,
                source="analyzer",
            )
        )
    return findings


__all__ = ["parse_oxlint_json"]
