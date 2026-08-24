"""Trivy JSON output parser."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.analyzers.parsers._common import (
    map_confidence,
    map_native_severity,
    resolve_repo_relative_path,
    taxonomy_category,
)
from mergecraft.utils.json_load import try_load_json

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.manifest import AnalyzerManifest


def loads_trivy_object(raw: str) -> dict[str, Any]:
    """Parse trivy JSON, tolerating log lines that precede the object.

    Trivy (and some CI sandboxes) can emit timestamped INFO lines before the
    report. ``json.loads`` then treats the leading year (e.g. ``2026``) as a
    complete value and raises ``Extra data`` at column 5.
    """
    payload = try_load_json(raw)
    if isinstance(payload, dict):
        return cast("dict[str, Any]", payload)  # try_load_json returns object
    msg = "trivy JSON output must be an object"
    raise ValueError(msg)


def parse_trivy_json(raw: str, *, manifest: AnalyzerManifest, repo_root: Path) -> list[Finding]:
    payload = loads_trivy_object(raw)

    category = taxonomy_category(manifest)
    findings: list[Finding] = []
    for result in payload.get("Results") or []:
        if not isinstance(result, dict):
            continue
        target = str(result.get("Target") or "unknown")
        path = resolve_repo_relative_path(target, repo_root=repo_root)
        misconfigs = result.get("Misconfigurations") or []
        for misconfig in misconfigs:
            if not isinstance(misconfig, dict):
                continue
            native_level = str(misconfig.get("Severity") or "unknown").casefold()
            rule_id = str(misconfig.get("ID") or "trivy-config")
            title = str(misconfig.get("Title") or misconfig.get("Description") or rule_id)
            findings.append(
                make_finding(
                    tool=manifest.id,
                    rule_id=rule_id,
                    category=category,
                    severity=map_native_severity(manifest, native_level),
                    confidence=map_confidence(None),
                    message=title,
                    path=path,
                    start_line=1,
                    end_line=1,
                    source="analyzer",
                )
            )
        for vulnerability in result.get("Vulnerabilities") or []:
            if not isinstance(vulnerability, dict):
                continue
            native_level = str(vulnerability.get("Severity") or "unknown").casefold()
            rule_id = str(vulnerability.get("VulnerabilityID") or "trivy")
            title = str(vulnerability.get("Title") or vulnerability.get("Description") or rule_id)
            pkg_name = str(vulnerability.get("PkgName") or "")
            fixed = str(vulnerability.get("FixedVersion") or "").strip()
            remediation = f"Upgrade to {fixed} or later" if fixed else None
            evidence = [f"package: {pkg_name}"] if pkg_name else []
            findings.append(
                make_finding(
                    tool=manifest.id,
                    rule_id=rule_id,
                    category=category,
                    severity=map_native_severity(manifest, native_level),
                    confidence=map_confidence(None),
                    message=title,
                    path=path,
                    start_line=1,
                    end_line=1,
                    source="analyzer",
                    remediation=remediation,
                    evidence=evidence,
                )
            )
    return findings


__all__ = ["loads_trivy_object", "parse_trivy_json"]
