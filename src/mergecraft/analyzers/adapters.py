"""End-to-end catalog adapter runner (manifest → findings)."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from loguru import logger

from mergecraft.analyzers.execution import finalize_plan, provision_managed_argv
from mergecraft.analyzers.parse import parse_output_file
from mergecraft.analyzers.parsers import parse_output
from mergecraft.analyzers.parsers._common import resolve_repo_relative_path
from mergecraft.analyzers.registry import filter_changed_files_for_manifest, get_manifest
from mergecraft.analyzers.resolve import AnalyzerPlan, expand_analyzer_argv, resolve_analyzer
from mergecraft.analyzers.run import run_plan
from mergecraft.analyzers.sandbox import plan_sandbox

if TYPE_CHECKING:
    from mergecraft.analyzers.finding import Finding
    from mergecraft.analyzers.manifest import AnalyzerManifest
    from mergecraft.analyzers.sandbox import SandboxContext

TrustTier = Literal["trusted", "untrusted"]

DIFFERENTIAL_CONTRACT_TOOLS: frozenset[str] = frozenset({"oasdiff", "squawk", "buf"})
SUPPLY_CHAIN_DIFF_TOOLS: frozenset[str] = frozenset({"osv-scanner", "trivy"})


@dataclass(frozen=True, slots=True)
class AdapterRunResult:
    findings: list[Finding]
    skipped: bool = False
    skip_reason: str | None = None
    version_note: str | None = None
    config_note: str | None = None


def _normalize_paths(findings: list[Finding], *, repo_root: Path) -> list[Finding]:
    normalized: list[Finding] = []
    for finding in findings:
        path = resolve_repo_relative_path(finding.path, repo_root=repo_root)
        normalized.append(finding.model_copy(update={"path": path}))
    return normalized


def _finalize_trufflehog_findings(findings: list[Finding], *, repo_root: Path) -> list[Finding]:
    from mergecraft.analyzers.parsers.trufflehog_jsonl import _ROTATION_FIRST_REMEDIATION

    normalized: list[Finding] = []
    for finding in findings:
        remediation = finding.remediation or _ROTATION_FIRST_REMEDIATION
        if "rotate" not in remediation.casefold():
            remediation = _ROTATION_FIRST_REMEDIATION
        normalized.append(finding.model_copy(update={"remediation": remediation}))
    _ = repo_root
    return normalized


def _format_finding(
    *,
    manifest: AnalyzerManifest,
    path: str,
    line: int,
    message: str,
) -> Finding:
    from mergecraft.analyzers.finding import make_finding
    from mergecraft.analyzers.parsers._common import map_confidence, taxonomy_category

    return make_finding(
        tool=manifest.id,
        rule_id="format",
        category=taxonomy_category(manifest),
        severity=manifest.severity_map.get("warning", "Minor"),
        confidence=map_confidence(None),
        message=message,
        path=path,
        start_line=line,
        end_line=line,
        source="analyzer",
    )


_ANSI_SGR = re.compile(r"\x1b\[[0-9;]*m")

# ruff <= 0.15 lists one `Would reformat: <path>` line per file. ruff >= 0.16
# routes `format --check` through the shared diagnostic renderer instead:
# an `unformatted:` header followed by ` --> <path>:<line>:<col>`. The manifest
# pins 0.15.12 but declares `runtime: repo-native`, so the reviewed repo's own
# ruff decides which spelling arrives and both have to parse.
_LEGACY_REFORMAT_PREFIX = "Would reformat:"
_UNFORMATTED_PREFIX = "unformatted:"
_LOCATION_PREFIX = "-->"


def _location_path(location: str) -> str:
    """Strip the trailing ``:<line>:<col>`` from a diagnostic location.

    Returns ``""`` when the suffix does not parse: a location ruff did not
    render in this shape is not a path, and returning the whole string produced
    a plausible-looking one that then normalised into a finding against a file
    that does not exist.
    """
    head, _, column = location.rpartition(":")
    path, _, line = head.rpartition(":")
    if path and line.isdigit() and column.isdigit():
        return path
    return ""


def _parse_reformat_paths(output: str, *, repo_root: Path) -> list[str]:
    """Collect the files ruff says would be reformatted, in either output format.

    Only paths introduced by an ``unformatted:`` header are taken from the
    diagnostic renderer: ``format --check`` renders ``invalid-syntax:``
    diagnostics with the same ``-->`` arrow, and those are tool failures rather
    than unformatted files. Paths arrive absolute or repo-relative depending on
    how the argv was expanded; ``resolve_repo_relative_path`` normalises both.

    ruff renders each diagnostic as header-then-arrow, so the header only claims
    the arrow on the line immediately after it. Any other line clears the claim:
    letting it persist meant an ``unformatted:`` header with no arrow of its own
    adopted a *later* diagnostic's location — attributing a reformat to the file
    that could not be parsed. The tradeoff is that a non-adjacent arrow is
    dropped rather than mis-attributed: real ruff (measured on 0.16.2) always
    emits them adjacently, so nothing is lost today, but a renderer change would
    show up as missing reformat paths rather than wrong ones.
    """
    paths: list[str] = []
    awaiting_location = False
    for raw_line in output.splitlines():
        stripped = _ANSI_SGR.sub("", raw_line).strip()
        if stripped.startswith(_LEGACY_REFORMAT_PREFIX):
            awaiting_location = False
            raw_path = stripped[len(_LEGACY_REFORMAT_PREFIX) :].strip()
            if raw_path:
                paths.append(resolve_repo_relative_path(raw_path, repo_root=repo_root))
            continue
        if stripped.startswith(_UNFORMATTED_PREFIX):
            awaiting_location = True
            continue
        if awaiting_location and stripped.startswith(_LOCATION_PREFIX):
            raw_path = _location_path(stripped[len(_LOCATION_PREFIX) :].strip())
            if raw_path:
                paths.append(resolve_repo_relative_path(raw_path, repo_root=repo_root))
        awaiting_location = False
    return paths


def _run_ruff_format_check(
    plan: AnalyzerPlan,
    *,
    manifest: AnalyzerManifest,
    repo_root: Path,
    scoped_files: list[str],
    tier: TrustTier,
    sandbox_context: SandboxContext | None,
) -> list[Finding]:
    if not plan.argv:
        return []
    binary = plan.argv[0]
    format_argv = expand_analyzer_argv(
        (binary, "format", "--check", "{files}"),
        repo_root=repo_root,
        changed_files=scoped_files,
    )
    format_plan = replace(
        plan,
        manifest_id=f"{manifest.id}-format",
        argv=format_argv,
    )
    format_plan = finalize_plan(
        format_plan,
        manifest=manifest,
        repo_root=repo_root,
        changed_files=scoped_files,
        tier=tier,
    )
    outcome = run_plan(format_plan, sandbox_context=sandbox_context)
    # "Did not run here" is a skip, never a finding (see run_analyzers' contract
    # in mcp/analyzers.py): a sandbox refusal or a repo ruff too old for
    # `format --check` must not be reported as an unformatted file.
    if not outcome.ran:
        logger.info("skipped ruff format check: {}", outcome.output or "analyzer did not run")
        return []
    if outcome.exit_code == 0:
        return []
    if not scoped_files:
        return []
    reformat_paths = _parse_reformat_paths(outcome.output or "", repo_root=repo_root)
    if reformat_paths:
        return [
            _format_finding(
                manifest=manifest,
                path=rel,
                line=1,
                message="File would be reformatted by ruff format",
            )
            for rel in reformat_paths
        ]
    # Non-zero exit with no unformatted file named at all — a genuine ruff
    # failure (bad config, unparseable source). Emit at scoped_files[0] rather
    # than silently returning nothing: a broken tool should not pass as clean.
    return [
        _format_finding(
            manifest=manifest,
            path=scoped_files[0],
            line=1,
            message="ruff format check failed: analyzer produced no parseable output",
        )
    ]


def run_adapter(
    *,
    tool_id: str,
    repo_root: Path,
    changed_files: list[str],
    tier: TrustTier = "trusted",
    base_ref: str | None = None,
    offline: bool = False,
    allow_repo_binaries: bool = True,
) -> AdapterRunResult:
    """Run one catalog analyzer and return normalized findings.

    ``allow_repo_binaries=False`` (set by the pipeline under ``shell:
    disabled``) forbids ``resolve_analyzer()`` from preferring a binary the
    repo provides, so only mergeCraft's pinned managed binary can run (#35).
    """
    repo_root = repo_root.resolve()
    manifest = get_manifest(tool_id)

    from mergecraft.analyzers.contracts import resolve_analyzer_base_ref, run_differential_adapter

    if tool_id in DIFFERENTIAL_CONTRACT_TOOLS:
        resolved_base = resolve_analyzer_base_ref(
            repo_root,
            base_ref=base_ref,
            offline=offline,
            changed_files=changed_files,
        )
        return run_differential_adapter(
            tool_id=tool_id,
            repo_root=repo_root,
            changed_files=changed_files,
            base_ref=resolved_base,
            tier=tier,
            allow_repo_binaries=allow_repo_binaries,
        )

    if tool_id in SUPPLY_CHAIN_DIFF_TOOLS:
        from mergecraft.analyzers.supply_chain import run_supply_chain_adapter

        resolved_base = resolve_analyzer_base_ref(
            repo_root,
            base_ref=base_ref,
            offline=offline,
            changed_files=changed_files,
        )
        return run_supply_chain_adapter(
            tool_id=tool_id,
            repo_root=repo_root,
            changed_files=changed_files,
            base_ref=resolved_base,
            tier=tier,
            allow_repo_binaries=allow_repo_binaries,
        )

    if tool_id == "agentsec":
        from mergecraft.analyzers.agentsec import scan_manifests

        scoped_files = filter_changed_files_for_manifest(manifest, changed_files)
        if not scoped_files:
            reason = "skipped agentsec: no changed files match detect globs"
            logger.info("{}", reason)
            return AdapterRunResult(findings=[], skipped=True, skip_reason=reason)

        result = scan_manifests(
            repo_root=repo_root,
            changed_files=scoped_files,
            tier=tier,
        )
        if result.skipped:
            return AdapterRunResult(
                findings=[],
                skipped=True,
                skip_reason=result.skip_reason,
                version_note="ran mergeCraft native agent-security policy engine",
                config_note="native YAML rules",
            )
        return AdapterRunResult(
            findings=_normalize_paths(result.findings, repo_root=repo_root),
            version_note="ran mergeCraft native agent-security policy engine",
            config_note="native YAML rules",
        )

    scoped_files = filter_changed_files_for_manifest(manifest, changed_files)
    if not scoped_files:
        reason = f"skipped {tool_id}: no changed files match detect globs"
        logger.info("{}", reason)
        return AdapterRunResult(findings=[], skipped=True, skip_reason=reason)

    plan = resolve_analyzer(
        manifest=manifest,
        repo_root=repo_root,
        managed_available=True,
        allow_repo_binaries=allow_repo_binaries,
    )
    if plan.mode == "skip":
        logger.info("{}", plan.reason)
        return AdapterRunResult(findings=[], skipped=True, skip_reason=plan.reason)

    if plan.mode == "managed":
        provisioned = provision_managed_argv(plan, manifest=manifest, repo_root=repo_root)
        if provisioned is None:
            reason = f"skipped {tool_id}: managed binary provisioning failed"
            return AdapterRunResult(findings=[], skipped=True, skip_reason=reason)
        plan = provisioned

    if plan.mode in {"ci-result", "container"} or not plan.argv:
        reason = f"skipped {tool_id}: mode {plan.mode} unavailable in this environment"
        logger.info("{}", reason)
        return AdapterRunResult(findings=[], skipped=True, skip_reason=reason)

    scratch_dir = repo_root / ".mergecraft" / "analyzer-scratch" / tool_id
    scratch_dir.mkdir(parents=True, exist_ok=True)
    sandbox_decision = plan_sandbox(
        manifest=manifest,
        tier=tier,
        repo_root=repo_root,
        scratch_dir=scratch_dir,
    )
    if not sandbox_decision.can_run:
        return AdapterRunResult(
            findings=[],
            skipped=True,
            skip_reason=sandbox_decision.skip_reason,
        )

    sandbox_context: SandboxContext | None = sandbox_decision.context
    plan = finalize_plan(
        plan,
        manifest=manifest,
        repo_root=repo_root,
        changed_files=scoped_files,
        tier=tier,
    )

    absolute_files = [
        str((repo_root / rel).resolve()) if not Path(rel).is_absolute() else rel
        for rel in scoped_files
    ]
    config_note = plan.config_note
    if tool_id in {"semgrep", "opengrep", "ast-grep"}:
        from mergecraft.analyzers.pattern import (
            augment_pattern_env,
            prepare_pattern_plan,
            scope_pattern_findings,
        )

        plan, ruleset = prepare_pattern_plan(
            plan,
            manifest=manifest,
            repo_root=repo_root,
            file_paths=absolute_files,
        )
        config_note = plan.config_note or f"ruleset: {ruleset.name} ({ruleset.source})"
        plan = replace(plan, env=augment_pattern_env(dict(plan.env), scratch_dir=scratch_dir))

    if tool_id == "jscpd" and plan.argv:
        # JsonReporter writes ``<output>/jscpd-report.json`` rather than stdout.
        plan = replace(
            plan,
            argv=(plan.argv[0], "--output", str(scratch_dir), *plan.argv[1:]),
        )

    outcome = run_plan(plan, sandbox_context=sandbox_context)
    if not outcome.ran:
        reason = outcome.output or f"skipped {tool_id}: analyzer did not run"
        return AdapterRunResult(findings=[], skipped=True, skip_reason=reason)

    if outcome.output_path is None and tool_id == "jscpd":
        report = scratch_dir / "jscpd-report.json"
        if report.is_file():
            findings = parse_output(
                report.read_text(encoding="utf-8"),
                manifest=manifest,
                repo_root=repo_root,
            )
            return AdapterRunResult(
                findings=_normalize_paths(findings, repo_root=repo_root),
                version_note=plan.version_note,
                config_note=config_note,
            )

    if outcome.output_path is None:
        reason = outcome.output or f"skipped {tool_id}: analyzer did not run"
        return AdapterRunResult(findings=[], skipped=True, skip_reason=reason)

    try:
        raw = (
            Path(outcome.output_path).read_text(encoding="utf-8")
            if outcome.output_path
            else outcome.output
        )
        findings = parse_output_file(
            Path(outcome.output_path),
            manifest=manifest,
            repo_root=repo_root,
        )
        if not findings and outcome.output.strip():
            findings = parse_output(outcome.output, manifest=manifest, repo_root=repo_root)
        if tool_id == "jscpd" and not findings:
            report = scratch_dir / "jscpd-report.json"
            if report.is_file():
                findings = parse_output(
                    report.read_text(encoding="utf-8"),
                    manifest=manifest,
                    repo_root=repo_root,
                )
    except (ValueError, KeyError) as exc:
        # Classify the failure: empty output means the analyzer never produced
        # anything (sandbox unavailable outside CI), not that it emitted garbage
        # we could not parse.
        if not (raw or "").strip():
            reason = (
                f"skipped {tool_id}: no output (analyzer did not run — "
                "likely sandbox unavailable outside CI)"
            )
        else:
            reason = f"skipped {tool_id}: failed to parse analyzer output ({exc})"
        logger.info("{}", reason)
        return AdapterRunResult(findings=[], skipped=True, skip_reason=reason)

    if tool_id == "ruff":
        findings = [
            *findings,
            *_run_ruff_format_check(
                plan,
                manifest=manifest,
                repo_root=repo_root,
                scoped_files=scoped_files,
                tier=tier,
                sandbox_context=sandbox_context,
            ),
        ]

    if tool_id == "trufflehog":
        findings = _finalize_trufflehog_findings(findings, repo_root=repo_root)

    if tool_id in {"semgrep", "opengrep", "ast-grep"}:
        from mergecraft.analyzers.pattern import scope_pattern_findings

        findings = scope_pattern_findings(findings, changed_files=scoped_files)

    return AdapterRunResult(
        findings=_normalize_paths(findings, repo_root=repo_root),
        version_note=plan.version_note,
        config_note=config_note,
    )


__all__ = [
    "DIFFERENTIAL_CONTRACT_TOOLS",
    "SUPPLY_CHAIN_DIFF_TOOLS",
    "AdapterRunResult",
    "run_adapter",
]
