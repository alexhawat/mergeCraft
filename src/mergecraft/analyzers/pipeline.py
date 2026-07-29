"""Canonical analyzer pipeline — detect, run, scope, cluster, budget (W7)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from loguru import logger

from mergecraft.analyzers.budget import default_inline_budget, place_findings
from mergecraft.analyzers.cluster import cluster_findings
from mergecraft.analyzers.finding import Finding
from mergecraft.analyzers.lockfile import lock_digest
from mergecraft.analyzers.registry import detect_enabled
from mergecraft.analyzers.review_gate import filter_for_review
from mergecraft.analyzers.scope import (
    annotate_introduced_by_pr,
    base_comparison_available,
    scope_findings,
    suppress_withdrawn_findings,
)
from mergecraft.analyzers.trust import evaluate_manifest_for_tier
from mergecraft.config import load_repo_settings
from mergecraft.mcp.review import format_analyzer_inline_body
from mergecraft.mcp.tool_state import AnalyzerRunState, AnalyzerStatusRow

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.config.settings import AnalyzersSettings

TrustTier = Literal["trusted", "untrusted"]


def _serialize_finding(finding: Finding) -> dict[str, Any]:
    return finding.model_dump()


def _load_learnings(repo_root: Path) -> str:
    learnings = repo_root / ".mergecraft" / "learnings.md"
    if not learnings.is_file():
        return ""
    return learnings.read_text(encoding="utf-8")


def _analyzers_settings(repo_root: Path) -> AnalyzersSettings:
    return load_repo_settings(root=repo_root, load_learnings_files=False).analyzers


def _settings_overrides(settings: AnalyzersSettings) -> dict[str, Any]:
    return {
        "analyzers": {
            "enabled": settings.enabled,
            "inlineBudget": settings.inline_budget,
            "baseComparison": settings.base_comparison,
            "overrides": {
                analyzer_id: {"enabled": override.enabled}
                for analyzer_id, override in settings.overrides.items()
                if override.enabled is not None
            },
        }
    }


def _build_pre_merge_summary(
    rows: list[AnalyzerStatusRow],
    *,
    lockfile_digest_value: str,
) -> str:
    ran = [row for row in rows if row.status in {"passed", "failed"}]
    skipped = [row for row in rows if row.status == "unavailable"]
    parts = [f"{len(ran)} ran"]
    if skipped:
        reasons = ", ".join(f"{row.id}: {row.reason or 'skipped'}" for row in skipped)
        parts.append(f"{len(skipped)} skipped ({reasons})")
    parts.append(f"lock {lockfile_digest_value}")
    return "; ".join(parts)


def run_analyzer_pipeline(
    *,
    repo_root: Path,
    changed_files: list[str],
    tier: TrustTier,
    diff_text: str = "",
    inline_budget: int | None = None,
    offline: bool = False,
) -> AnalyzerRunState:
    """Run enabled analyzers end-to-end and return scoped, budgeted findings."""
    settings = _analyzers_settings(repo_root)
    if not settings.enabled:
        return AnalyzerRunState(
            ran=False,
            reason=(
                "analyzers disabled in .mergecraft/config.yaml — report the Analyzers "
                "pre-merge row as skipped"
            ),
        )

    manifests = detect_enabled(
        repo_root=repo_root,
        changed_files=changed_files,
        settings_overrides=_settings_overrides(settings),
    )
    if not manifests:
        return AnalyzerRunState(
            ran=False,
            reason=(
                "no catalog analyzers matched this diff — report the Analyzers pre-merge "
                "row as skipped"
            ),
        )

    rows: list[AnalyzerStatusRow] = []
    raw_findings: list[Finding] = []

    from mergecraft.analyzers.adapters import run_adapter

    for manifest in manifests:
        decision = evaluate_manifest_for_tier(manifest=manifest, tier=tier)
        if decision.skipped:
            rows.append(
                AnalyzerStatusRow(
                    id=manifest.id,
                    status="unavailable",
                    reason=decision.reason,
                )
            )
            continue
        try:
            result = run_adapter(
                tool_id=manifest.id,
                repo_root=repo_root,
                changed_files=changed_files,
                tier=tier,
            )
        except (KeyError, OSError, ValueError) as exc:
            logger.info("analyzer {} unavailable: {}", manifest.id, exc)
            rows.append(
                AnalyzerStatusRow(
                    id=manifest.id,
                    status="unavailable",
                    reason=str(exc),
                )
            )
            continue

        if result.skipped:
            rows.append(
                AnalyzerStatusRow(
                    id=manifest.id,
                    status="unavailable",
                    reason=result.skip_reason,
                )
            )
            continue

        status = "failed" if result.findings else "passed"
        rows.append(
            AnalyzerStatusRow(
                id=manifest.id,
                status=status,
                finding_count=len(result.findings),
            )
        )
        raw_findings.extend(result.findings)

    learnings_text = _load_learnings(repo_root)
    if diff_text.strip():
        scoped = scope_findings(
            raw_findings,
            diff_text=diff_text,
            repo_root=repo_root,
            learnings_text=learnings_text,
        )
    else:
        scoped = suppress_withdrawn_findings(raw_findings, learnings_text)

    base_run = base_comparison_available(
        base_comparison=settings.base_comparison,
        offline=offline,
    )
    scoped = annotate_introduced_by_pr(scoped, base_run_performed=base_run)

    clustered = cluster_findings(scoped)
    budget = (
        inline_budget
        if inline_budget is not None
        else (settings.inline_budget or default_inline_budget())
    )
    placement = place_findings(clustered, inline_budget=budget)

    serialized = [_serialize_finding(f) for f in clustered]
    inline_payload: list[dict[str, Any]] = []
    for item in placement.inline:
        if isinstance(item, Finding):
            inline_payload.append(
                {
                    "finding": _serialize_finding(item),
                    "inlineBody": format_analyzer_inline_body(item),
                    "path": item.path,
                    "line": item.start_line,
                }
            )

    lock_path = repo_root / ".mergecraft" / "analyzers.lock"
    digest = lock_digest(lock_path)
    summary = _build_pre_merge_summary(rows, lockfile_digest_value=digest)

    executed = [row for row in rows if row.status in {"passed", "failed"}]
    if not executed:
        return AnalyzerRunState(
            ran=False,
            reason=(
                "every enabled analyzer was skipped in this environment — report the "
                "Analyzers pre-merge row as skipped, not failed"
            ),
            analyzers=rows,
            findings=serialized,
            inline=inline_payload,
            mechanical_section=placement.mechanical_section,
            pre_merge_summary=summary,
            lockfile_digest=digest,
        )

    return AnalyzerRunState(
        ran=True,
        analyzers=rows,
        findings=serialized,
        inline=inline_payload,
        mechanical_section=placement.mechanical_section,
        pre_merge_summary=summary,
        lockfile_digest=digest,
    )


def analyzer_run_metadata(*, tool_id: str, result: object) -> dict[str, str]:
    """Return review metadata naming the tool version and config that ran (D5/C1.5)."""
    from mergecraft.analyzers.adapters import AdapterRunResult

    if not isinstance(result, AdapterRunResult):
        return {}
    version_note = result.version_note or ""
    config_note = result.config_note or ""
    payload: dict[str, str] = {}
    if version_note:
        payload["version_note"] = version_note
        payload["version"] = version_note
    if config_note:
        payload["config"] = config_note
    if tool_id:
        payload["tool"] = tool_id
    return payload


__all__ = ["analyzer_run_metadata", "filter_for_review", "run_analyzer_pipeline"]
