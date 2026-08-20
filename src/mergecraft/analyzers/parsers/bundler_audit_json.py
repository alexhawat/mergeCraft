"""bundler-audit ``--format json`` output parser."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.analyzers.parsers._common import (
    map_confidence,
    map_native_severity,
    require_json_object,
    taxonomy_category,
)

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.manifest import AnalyzerManifest


def _result_native_level(result: dict[str, Any]) -> str:
    result_type = str(result.get("type") or "").casefold()
    if result_type in {"insecure_source", "insecuresource"}:
        return "warning"
    return "error"


def parse_bundler_audit_json(
    raw: str, *, manifest: AnalyzerManifest, repo_root: Path
) -> list[Finding]:
    _ = repo_root
    payload = require_json_object(raw, what="bundler-audit JSON output")

    category = taxonomy_category(manifest)
    findings: list[Finding] = []
    results = payload.get("results")
    if not isinstance(results, list):
        return findings
    for result in results:
        if not isinstance(result, dict):
            continue
        advisory_raw = result.get("advisory")
        advisory = advisory_raw if isinstance(advisory_raw, dict) else {}
        gem_raw = result.get("gem")
        gem = gem_raw if isinstance(gem_raw, dict) else {}
        rule_id = str(advisory.get("id") or result.get("type") or "bundler-audit")
        title = str(advisory.get("title") or rule_id)
        gem_name = str(gem.get("name") or "")
        gem_version = str(gem.get("version") or "")
        evidence = [f"gem: {gem_name} {gem_version}".strip()] if gem_name else []
        findings.append(
            make_finding(
                tool=manifest.id,
                rule_id=rule_id,
                category=category,
                severity=map_native_severity(manifest, _result_native_level(result)),
                confidence=map_confidence(None),
                message=title,
                path="Gemfile.lock",
                start_line=1,
                end_line=1,
                source="analyzer",
                evidence=evidence,
            )
        )
    return findings


__all__ = ["parse_bundler_audit_json"]
