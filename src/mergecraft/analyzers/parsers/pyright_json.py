"""Pyright / BasedPyright JSON output parser."""

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


def parse_pyright_json(raw: str, *, manifest: AnalyzerManifest, repo_root: Path) -> list[Finding]:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        msg = "pyright JSON output must be an object"
        raise ValueError(msg)

    category = taxonomy_category(manifest)
    findings: list[Finding] = []
    for item in payload.get("generalDiagnostics") or []:
        if not isinstance(item, dict):
            continue
        path = resolve_repo_relative_path(str(item.get("file") or ""), repo_root=repo_root)
        severity = str(item.get("severity") or "error")
        rule_id = str(item.get("rule") or "pyright")
        message = str(item.get("message") or "pyright finding")
        range_obj = item.get("range") or {}
        start = range_obj.get("start") or {}
        end = range_obj.get("end") or {}
        start_line = coerce_line(int(start.get("line", 0)) + 1)
        end_line = coerce_line(int(end.get("line", start_line - 1)) + 1, default=start_line)
        findings.append(
            make_finding(
                tool=manifest.id,
                rule_id=rule_id,
                category=category,
                severity=map_native_severity(manifest, severity),
                confidence=map_confidence(None),
                message=message,
                path=path,
                start_line=start_line,
                end_line=end_line,
                source="analyzer",
            )
        )
    return findings


__all__ = ["parse_pyright_json"]
