"""cargo-audit ``--json`` output parser."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.analyzers.parsers._common import (
    map_confidence,
    map_native_severity,
    require_json_object,
    resolve_repo_relative_path,
    taxonomy_category,
)

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.manifest import AnalyzerManifest


def _lockfile_path(payload: dict[str, Any], *, repo_root: Path) -> str:
    lockfile = payload.get("lockfile")
    if isinstance(lockfile, dict):
        raw_path = str(lockfile.get("path") or "Cargo.lock")
    else:
        raw_path = "Cargo.lock"
    return resolve_repo_relative_path(raw_path, repo_root=repo_root) or "Cargo.lock"


def _advisory_finding(
    entry: object,
    *,
    manifest: AnalyzerManifest,
    category: str,
    path: str,
    native_level: str,
) -> Finding | None:
    if not isinstance(entry, dict):
        return None
    advisory_raw = entry.get("advisory")
    advisory = advisory_raw if isinstance(advisory_raw, dict) else {}
    package_raw = entry.get("package")
    package = package_raw if isinstance(package_raw, dict) else {}
    rule_id = str(advisory.get("id") or "cargo-audit")
    title = str(advisory.get("title") or rule_id)
    pkg_name = str(package.get("name") or advisory.get("package") or "")
    pkg_version = str(package.get("version") or "")
    evidence = [f"package: {pkg_name} {pkg_version}".strip()] if pkg_name else []
    return make_finding(
        tool=manifest.id,
        rule_id=rule_id,
        category=category,
        severity=map_native_severity(manifest, native_level),
        confidence=map_confidence(None),
        message=title,
        path=path,
        start_line=None,
        end_line=None,
        source="analyzer",
        evidence=evidence,
    )


def parse_cargo_audit_json(
    raw: str, *, manifest: AnalyzerManifest, repo_root: Path
) -> list[Finding]:
    payload = require_json_object(raw, what="cargo-audit JSON output")

    category = taxonomy_category(manifest)
    path = _lockfile_path(payload, repo_root=repo_root)
    findings: list[Finding] = []

    vulns = payload.get("vulnerabilities")
    vuln_list = vulns.get("list") if isinstance(vulns, dict) else []
    if isinstance(vuln_list, list):
        for entry in vuln_list:
            finding = _advisory_finding(
                entry,
                manifest=manifest,
                category=category,
                path=path,
                native_level="error",
            )
            if finding is not None:
                findings.append(finding)

    warnings = payload.get("warnings")
    if isinstance(warnings, dict):
        for group in warnings.values():
            if not isinstance(group, list):
                continue
            for entry in group:
                finding = _advisory_finding(
                    entry,
                    manifest=manifest,
                    category=category,
                    path=path,
                    native_level="warning",
                )
                if finding is not None:
                    findings.append(finding)
    return findings


__all__ = ["parse_cargo_audit_json"]
