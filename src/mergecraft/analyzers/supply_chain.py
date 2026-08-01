"""Differential supply-chain scanning — base vs head CVE delta (C2, D6)."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from loguru import logger

from mergecraft.analyzers.adapters import AdapterRunResult
from mergecraft.analyzers.execution import finalize_plan, provision_resolved_plan
from mergecraft.analyzers.parsers import parse_output
from mergecraft.analyzers.parsers.osv_json import _severity_rank
from mergecraft.analyzers.paths import safe_repo_relative_path
from mergecraft.analyzers.registry import get_manifest
from mergecraft.analyzers.resolve import AnalyzerPlan, expand_analyzer_argv
from mergecraft.analyzers.run import run_plan
from mergecraft.analyzers.sandbox import plan_sandbox

if TYPE_CHECKING:
    from mergecraft.analyzers.finding import Finding
    from mergecraft.analyzers.manifest import AnalyzerManifest

TrustTier = Literal["trusted", "untrusted"]

SUPPLY_CHAIN_DIFF_TOOLS: frozenset[str] = frozenset({"osv-scanner", "trivy"})

_PKG_LINE_RE = re.compile(r"^\s*(?:[a-zA-Z0-9_.-]+\s*=\s*)?([a-zA-Z0-9_.-]+)")


def _snapshot_dir(repo_root: Path, files: list[str]) -> Path:
    root = Path(tempfile.mkdtemp(prefix="mergecraft-supply-"))
    for rel in files:
        src = safe_repo_relative_path(repo_root, rel)
        if src is None or not src.is_file():
            continue
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    return root


def _provision_plan(
    plan: AnalyzerPlan,
    *,
    manifest: AnalyzerManifest,
    repo_root: Path,
) -> AnalyzerPlan | None:
    return provision_resolved_plan(plan, manifest=manifest, repo_root=repo_root)


def _resolve_base_file_rel(repo_root: Path, head_rel: str, base_ref: str | None) -> str | None:
    from mergecraft.analyzers.contracts import _fixture_base_rel, _resolve_base_file

    companion = _fixture_base_rel(head_rel)
    if (repo_root / companion).is_file():
        return companion
    if base_ref:
        resolved = _resolve_base_file(repo_root, head_rel, base_ref)
        if resolved is not None and resolved.is_file():
            return str(resolved.relative_to(repo_root.resolve()))
    return None


def _is_direct_dependency(manifest_path: Path, package_name: str) -> bool:
    try:
        text = manifest_path.read_text(encoding="utf-8")
    except OSError:
        return True
    target = package_name.casefold()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _PKG_LINE_RE.match(stripped)
        if match and match.group(1).casefold() == target:
            return True
    return False


def _dependency_relationship(manifest_path: Path | None, package_name: str) -> str:
    if manifest_path is None or not package_name or not manifest_path.is_file():
        return "direct"
    return "direct" if _is_direct_dependency(manifest_path, package_name) else "transitive"


def _vuln_key(finding: Finding) -> str:
    return f"{finding.path}:{finding.rule_id.upper()}"


def _severity_increased(base: Finding, head: Finding) -> bool:
    return _severity_rank(head.severity) > _severity_rank(base.severity)


def _enrich_vuln_finding(
    finding: Finding,
    *,
    fixed_version: str | None,
    relationship: str,
) -> Finding:
    if fixed_version:
        remediation = f"Upgrade to {fixed_version} or later"
    elif finding.remediation:
        remediation = finding.remediation
    else:
        remediation = "Upgrade to a patched version"
    evidence = list(finding.evidence)
    if not any("direct" in item.casefold() or "transitive" in item.casefold() for item in evidence):
        evidence.append(f"dependency: {relationship}")
    return finding.model_copy(update={"remediation": remediation, "evidence": evidence})


def _delta_findings(base: list[Finding], head: list[Finding]) -> list[Finding]:
    base_by_key = {_vuln_key(item): item for item in base}
    delta: list[Finding] = []
    for item in head:
        key = _vuln_key(item)
        previous = base_by_key.get(key)
        if previous is None or _severity_increased(previous, item):
            delta.append(item.model_copy(update={"introduced_by_pr": "true"}))
    return delta


def _manifest_paths(repo_root: Path, files: list[str]) -> dict[str, Path]:
    return {rel: repo_root / rel for rel in files if (repo_root / rel).is_file()}


def _package_names_from_trivy(raw: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    try:
        from mergecraft.analyzers.parsers.trivy_json import loads_trivy_object

        payload = loads_trivy_object(raw)
    except json.JSONDecodeError, ValueError:
        return mapping
    for result in payload.get("Results") or []:
        if not isinstance(result, dict):
            continue
        target = str(result.get("Target") or "")
        rel_path = Path(target).name
        for vulnerability in result.get("Vulnerabilities") or []:
            if not isinstance(vulnerability, dict):
                continue
            pkg = str(vulnerability.get("PkgName") or "")
            if pkg:
                mapping[rel_path] = pkg
                mapping[target] = pkg
    return mapping


def _enrich_trivy_findings(
    findings: list[Finding],
    *,
    repo_root: Path,
    manifest_paths: dict[str, Path],
    package_names: dict[str, str],
) -> list[Finding]:
    enriched: list[Finding] = []
    for finding in findings:
        pkg = package_names.get(finding.path, "")
        if not pkg:
            for key, value in package_names.items():
                if finding.path.endswith(key):
                    pkg = value
                    break
        manifest_path = manifest_paths.get(finding.path)
        if manifest_path is None:
            for rel, path in manifest_paths.items():
                if finding.path.endswith(rel):
                    manifest_path = path
                    break
        fixed = None
        if finding.remediation and "upgrade to" in finding.remediation.casefold():
            fixed = (
                finding.remediation.casefold()
                .split("upgrade to", 1)[-1]
                .split(" or later", 1)[0]
                .strip()
            )
        enriched.append(
            _enrich_vuln_finding(
                finding,
                fixed_version=fixed or None,
                relationship=_dependency_relationship(manifest_path, pkg),
            )
        )
    return enriched


def _run_osv_scan(
    *,
    manifest: AnalyzerManifest,
    repo_root: Path,
    lockfiles: list[str],
    tier: TrustTier,
) -> tuple[list[Finding], str | None]:
    from mergecraft.analyzers.parsers.osv_json import parse_osv_json
    from mergecraft.analyzers.resolve import resolve_analyzer

    plan = resolve_analyzer(manifest=manifest, repo_root=repo_root, managed_available=True)
    provisioned = _provision_plan(plan, manifest=manifest, repo_root=repo_root)
    if provisioned is None:
        return [], plan.reason or f"skipped {manifest.id}: provisioning failed"

    existing = [rel for rel in lockfiles if safe_repo_relative_path(repo_root, rel) is not None]
    argv = expand_analyzer_argv(provisioned.argv, repo_root=repo_root, changed_files=existing)

    finalized = finalize_plan(
        replace(provisioned, argv=argv, cwd=repo_root),
        manifest=manifest,
        repo_root=repo_root,
        changed_files=existing,
        tier=tier,
    )

    scratch = repo_root / ".mergecraft" / "analyzer-scratch" / manifest.id
    scratch.mkdir(parents=True, exist_ok=True)
    sandbox = plan_sandbox(
        manifest=manifest,
        tier=tier,
        repo_root=repo_root,
        scratch_dir=scratch,
    )
    if not sandbox.can_run:
        return [], sandbox.skip_reason

    outcome = run_plan(finalized, sandbox_context=sandbox.context)
    if not outcome.ran:
        return [], outcome.output

    raw = (
        Path(outcome.output_path).read_text(encoding="utf-8")
        if outcome.output_path
        else outcome.output
    )
    manifest_paths = _manifest_paths(repo_root, existing)
    package_names: dict[str, str] = {}
    try:
        payload = json.loads(raw)
        for result in payload.get("results") or []:
            if not isinstance(result, dict):
                continue
            source = result.get("source") or {}
            rel = Path(str(source.get("path") or "")).name
            for package in result.get("packages") or []:
                if not isinstance(package, dict):
                    continue
                pkg_info = package.get("package") or {}
                pkg_name = str(pkg_info.get("name") or "")
                if pkg_name:
                    package_names[rel] = pkg_name
    except json.JSONDecodeError:
        pass

    findings = parse_osv_json(raw, manifest=manifest, repo_root=repo_root)
    enriched: list[Finding] = []
    for finding in findings:
        rel_path = Path(finding.path).name
        manifest_path = manifest_paths.get(rel_path) or manifest_paths.get(finding.path)
        pkg = package_names.get(rel_path, "")
        fixed = None
        if finding.remediation and "upgrade to" in finding.remediation.casefold():
            fixed = (
                finding.remediation.casefold()
                .split("upgrade to", 1)[-1]
                .split(" or later", 1)[0]
                .strip()
            )
        enriched.append(
            _enrich_vuln_finding(
                finding,
                fixed_version=fixed,
                relationship=_dependency_relationship(manifest_path, pkg),
            )
        )
    return enriched, None


def _run_trivy_fs(
    *,
    manifest: AnalyzerManifest,
    repo_root: Path,
    files: list[str],
    tier: TrustTier,
) -> tuple[list[Finding], str | None]:
    from mergecraft.analyzers.resolve import resolve_analyzer

    plan = resolve_analyzer(manifest=manifest, repo_root=repo_root, managed_available=True)
    provisioned = _provision_plan(plan, manifest=manifest, repo_root=repo_root)
    if provisioned is None:
        return [], plan.reason or f"skipped {manifest.id}: provisioning failed"

    binary = provisioned.argv[0] if provisioned.argv else "trivy"
    argv = (
        binary,
        "fs",
        "--quiet",
        "--format",
        "json",
        "--scanners",
        "vuln",
        str(repo_root),
    )
    finalized = finalize_plan(
        replace(provisioned, argv=argv, cwd=repo_root),
        manifest=manifest,
        repo_root=repo_root,
        changed_files=files,
        tier=tier,
    )

    scratch = repo_root / ".mergecraft" / "analyzer-scratch" / manifest.id
    scratch.mkdir(parents=True, exist_ok=True)
    sandbox = plan_sandbox(
        manifest=manifest,
        tier=tier,
        repo_root=repo_root,
        scratch_dir=scratch,
    )
    if not sandbox.can_run:
        return [], sandbox.skip_reason

    outcome = run_plan(finalized, sandbox_context=sandbox.context)
    if not outcome.ran:
        return [], outcome.output

    raw = (
        Path(outcome.output_path).read_text(encoding="utf-8")
        if outcome.output_path
        else outcome.output
    )
    findings = parse_output(raw, manifest=manifest, repo_root=repo_root)
    return (
        _enrich_trivy_findings(
            findings,
            repo_root=repo_root,
            manifest_paths=_manifest_paths(repo_root, files),
            package_names=_package_names_from_trivy(raw),
        ),
        None,
    )


def _iac_files(files: list[str]) -> list[str]:
    selected: list[str] = []
    for rel in files:
        path = Path(rel)
        name = path.name.casefold()
        if name.startswith("dockerfile") or name.endswith(".dockerfile"):
            selected.append(rel)
            continue
        if name.startswith("docker-compose") and path.suffix.casefold() in {".yml", ".yaml"}:
            selected.append(rel)
            continue
        if path.suffix.casefold() in {".tf", ".tfvars"}:
            selected.append(rel)
    return selected


def _run_trivy_config(
    *,
    manifest: AnalyzerManifest,
    repo_root: Path,
    iac_files: list[str],
    tier: TrustTier,
) -> tuple[list[Finding], str | None]:
    if not iac_files:
        return [], None

    from mergecraft.analyzers.resolve import resolve_analyzer

    plan = resolve_analyzer(manifest=manifest, repo_root=repo_root, managed_available=True)
    provisioned = _provision_plan(plan, manifest=manifest, repo_root=repo_root)
    if provisioned is None:
        return [], plan.reason

    paths = [str(repo_root / rel) for rel in iac_files if (repo_root / rel).is_file()]
    if not paths:
        return [], None
    binary = provisioned.argv[0] if provisioned.argv else "trivy"
    argv = (binary, "config", "--quiet", "--format", "json", *paths)
    finalized = finalize_plan(
        replace(provisioned, argv=argv, cwd=repo_root),
        manifest=manifest,
        repo_root=repo_root,
        changed_files=iac_files,
        tier=tier,
    )

    scratch = repo_root / ".mergecraft" / "analyzer-scratch" / f"{manifest.id}-config"
    scratch.mkdir(parents=True, exist_ok=True)
    sandbox = plan_sandbox(
        manifest=manifest,
        tier=tier,
        repo_root=repo_root,
        scratch_dir=scratch,
    )
    if not sandbox.can_run:
        return [], sandbox.skip_reason

    outcome = run_plan(finalized, sandbox_context=sandbox.context)
    if not outcome.ran:
        return [], outcome.output

    raw = (
        Path(outcome.output_path).read_text(encoding="utf-8")
        if outcome.output_path
        else outcome.output
    )
    return parse_output(raw, manifest=manifest, repo_root=repo_root), None


def _scan_side(
    tool_id: str,
    *,
    manifest: AnalyzerManifest,
    repo_root: Path,
    files: list[str],
    tier: TrustTier,
) -> tuple[list[Finding], str | None]:
    snapshot = _snapshot_dir(repo_root, files)
    try:
        if tool_id == "osv-scanner":
            return _run_osv_scan(
                manifest=manifest,
                repo_root=snapshot,
                lockfiles=files,
                tier=tier,
            )
        if tool_id == "trivy":
            fs_findings, err = _run_trivy_fs(
                manifest=manifest,
                repo_root=snapshot,
                files=files,
                tier=tier,
            )
            if err and not fs_findings:
                return [], err
            config_findings, _ = _run_trivy_config(
                manifest=manifest,
                repo_root=snapshot,
                iac_files=_iac_files(files),
                tier=tier,
            )
            return fs_findings + config_findings, None
        msg = f"unsupported differential tool: {tool_id}"
        raise ValueError(msg)
    finally:
        shutil.rmtree(snapshot, ignore_errors=True)


def run_differential_scan(
    *,
    tool_id: str,
    repo_root: Path,
    head_files: list[str],
    base_files: list[str],
    tier: TrustTier = "trusted",
) -> AdapterRunResult:
    """Run base and head supply-chain scans; publish only the CVE delta (C2.1/C2.2)."""
    repo_root = repo_root.resolve()
    manifest = get_manifest(tool_id)

    if not head_files:
        return AdapterRunResult(
            findings=[],
            skipped=True,
            skip_reason=f"skipped {tool_id}: no head manifest paths",
        )

    head_findings, head_err = _scan_side(
        tool_id,
        manifest=manifest,
        repo_root=repo_root,
        files=head_files,
        tier=tier,
    )
    if head_err and not head_findings:
        logger.info("{}", head_err)
        return AdapterRunResult(findings=[], skipped=True, skip_reason=head_err)

    base_findings, base_err = _scan_side(
        tool_id,
        manifest=manifest,
        repo_root=repo_root,
        files=base_files,
        tier=tier,
    )
    if base_err and not base_findings and not head_findings:
        return AdapterRunResult(findings=[], skipped=True, skip_reason=base_err)

    return AdapterRunResult(findings=_delta_findings(base_findings, head_findings))


def run_supply_chain_adapter(
    *,
    tool_id: str,
    repo_root: Path,
    changed_files: list[str],
    base_ref: str | None,
    tier: TrustTier = "trusted",
) -> AdapterRunResult:
    """Run differential supply-chain adapters through the production adapter path (C2)."""
    from mergecraft.analyzers.registry import filter_changed_files_for_manifest

    if tool_id not in SUPPLY_CHAIN_DIFF_TOOLS:
        msg = f"unsupported supply-chain tool: {tool_id}"
        raise ValueError(msg)

    manifest = get_manifest(tool_id)
    scoped = filter_changed_files_for_manifest(manifest, changed_files)
    if not scoped:
        return AdapterRunResult(
            findings=[],
            skipped=True,
            skip_reason=f"skipped {tool_id}: no changed files match detect globs",
        )

    base_files: list[str] = []
    for head_rel in scoped:
        base_rel = _resolve_base_file_rel(repo_root, head_rel, base_ref)
        base_files.append(base_rel or head_rel)

    return run_differential_scan(
        tool_id=tool_id,
        repo_root=repo_root,
        head_files=scoped,
        base_files=base_files,
        tier=tier,
    )


__all__ = ["SUPPLY_CHAIN_DIFF_TOOLS", "run_differential_scan", "run_supply_chain_adapter"]
