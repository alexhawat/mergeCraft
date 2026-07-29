"""Agent-manifest security scanner — MCP and skill policy engine (C5)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from mergecraft.analyzers.agentsec.mcp_manifest import discover_mcp_documents
from mergecraft.analyzers.agentsec.policy import (
    NativeRule,
    RuleMatch,
    apply_rules,
    load_native_rules,
)
from mergecraft.analyzers.agentsec.skill_manifest import discover_skill_documents
from mergecraft.analyzers.agentsec.skillspector import scan_with_skillspector
from mergecraft.analyzers.cluster import cluster_findings
from mergecraft.analyzers.finding import Finding, make_finding

if TYPE_CHECKING:
    from pathlib import Path

TrustTier = Literal["trusted", "untrusted"]
_TOOL = "agentsec"
_CATEGORY = "Security & Privacy"


@dataclass(frozen=True, slots=True)
class AgentSecScanResult:
    """Outcome of scanning changed agent manifests."""

    findings: list[Finding]
    skipped: bool = False
    skip_reason: str | None = None


def scan_manifests(
    *,
    repo_root: Path,
    changed_files: list[str],
    tier: TrustTier = "trusted",
) -> AgentSecScanResult:
    """Scan changed MCP and skill manifests with native YAML rules."""
    _ = tier
    repo_root = repo_root.resolve()
    scoped = [path for path in changed_files if path.strip()]
    if not scoped:
        return AgentSecScanResult(
            findings=[],
            skipped=True,
            skip_reason="skipped agentsec: no changed manifest paths",
        )

    documents = [
        *discover_mcp_documents(repo_root=repo_root, changed_files=scoped),
        *discover_skill_documents(repo_root=repo_root, changed_files=scoped),
    ]
    if not documents:
        return AgentSecScanResult(
            findings=[],
            skipped=True,
            skip_reason="skipped agentsec: no agent manifests in changed files",
        )

    rules = load_native_rules()
    native_matches = apply_rules(documents=documents, rules=rules)
    findings = [_finding_from_match(match) for match in native_matches]

    corroboration_paths = [repo_root / document.path for document in documents]
    findings.extend(
        scan_with_skillspector(repo_root=repo_root, paths=corroboration_paths),
    )
    return AgentSecScanResult(findings=cluster_findings(findings))


def _finding_from_match(match: RuleMatch) -> Finding:
    severity = match.rule.severity
    if match.rule.requires_verification and severity not in {"Critical", "Major"}:
        severity = "Major"
    return make_finding(
        tool=_TOOL,
        rule_id=match.rule.rule_id,
        category=_CATEGORY,
        severity=severity,
        confidence=match.rule.confidence,
        message=match.rule.message,
        path=match.path,
        start_line=match.start_line,
        end_line=match.end_line,
        source="analyzer",
        evidence=[match.snippet] if match.snippet else [],
        remediation=match.rule.remediation or None,
    )


__all__ = [
    "AgentSecScanResult",
    "NativeRule",
    "load_native_rules",
    "scan_manifests",
]
