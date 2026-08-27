"""Canonical analyzer pipeline — detect, run, scope, cluster, budget (W7)."""

from __future__ import annotations

import time
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger

from mergecraft.analyzers.baseline_suppression import (
    log_suppression_audit,
    should_run_baseline_suppression,
    suppress_baseline_findings,
)
from mergecraft.analyzers.budget import (
    default_inline_budget,
    finding_to_deferred_row,
    place_findings,
    sync_deferred_section,
)
from mergecraft.analyzers.cluster import cluster_findings
from mergecraft.analyzers.finding import Finding
from mergecraft.analyzers.lockfile import lock_digest
from mergecraft.analyzers.registry import detect_enabled
from mergecraft.analyzers.review_gate import filter_for_review
from mergecraft.analyzers.scope import (
    DiffScope,
    annotate_introduced_by_pr,
    base_comparison_available,
    introduced_by_base_diff,
    parse_diff_scope,
    scope_findings,
    suppress_withdrawn_findings,
)
from mergecraft.analyzers.trust import (
    allow_repo_provided_binaries,
    evaluate_manifest_for_mode,
    evaluate_manifest_for_shell,
    evaluate_manifest_for_tier,
    resolve_effective_analyzers_mode,
    resolve_selection_tier,
)
from mergecraft.config import load_repo_settings
from mergecraft.findings.dedup import dedupe_findings
from mergecraft.mcp.review import format_analyzer_inline_body
from mergecraft.mcp.tool_state import AnalyzerRunState, AnalyzerStatusRow

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from mergecraft.analyzers.manifest import AnalyzerManifest
    from mergecraft.config.settings import AnalyzersSettings

TrustTier = Literal["trusted", "untrusted"]


class CatalogScanStatus(StrEnum):
    """Glanceable catalog-level scan label (D6 / #459)."""

    UNAVAILABLE = "unavailable"
    CLEAN = "clean"
    FINDINGS = "findings"


AnalyzersMode = Literal["off", "auto", "full", "untrusted-only"]


def _serialize_finding(finding: Finding) -> dict[str, Any]:
    return finding.model_dump()


def _snapshot_attrs(
    source: dict[str, Any],
) -> Callable[[], dict[str, Any]]:
    """Return a no-arg callable that snapshots ``source`` for ``attrs_source``."""

    def _snap() -> dict[str, Any]:
        return dict(source)

    return _snap


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


def catalog_scan_status(state: AnalyzerRunState) -> CatalogScanStatus:
    """Return the glanceable catalog-level scan label (D6 / #459).

    ``ran=False`` is always ``unavailable`` — including disabled catalogs,
    no-match diffs, and empty tool rows — even when ``findings`` is empty.
    A catalog that executed and produced no findings is ``clean``. Mixed
    passed + skipped rows with ``ran=True`` are not catalog-unavailable.
    """
    if not state.ran:
        return CatalogScanStatus.UNAVAILABLE
    if state.findings:
        return CatalogScanStatus.FINDINGS
    return CatalogScanStatus.CLEAN


def _apply_baseline_suppression(
    scoped: list[Finding],
    *,
    repo_root: Path,
    manifests: list[AnalyzerManifest],
    changed_files: list[str],
    diff_text: str,
    base_comparison: str,
    tier: TrustTier,
    base_ref: str | None,
    offline: bool,
    allow_repo_binaries: bool,
    base_run_performed: bool,
    diff_scope: DiffScope | None = None,
    head_succeeded_manifest_ids: frozenset[str] | None = None,
) -> list[Finding]:
    """Annotate ``introduced_by_pr`` and run base-vs-head suppression when eligible."""
    if not should_run_baseline_suppression(
        diff_text=diff_text,
        base_comparison=base_comparison,
    ):
        return annotate_introduced_by_pr(scoped, base_run_performed=base_run_performed)

    from mergecraft.analyzers.baseline_suppression import collect_base_analyzer_findings

    collection = collect_base_analyzer_findings(
        repo_root=repo_root,
        manifests=manifests,
        changed_files=changed_files,
        head_findings=scoped,
        tier=tier,
        base_ref=base_ref,
        offline=offline,
        allow_repo_binaries=allow_repo_binaries,
    )
    expected = (
        head_succeeded_manifest_ids
        if head_succeeded_manifest_ids is not None
        else collection.succeeded_manifest_ids
    )
    if not collection.collected or collection.succeeded_manifest_ids != expected:
        logger.info(
            "baseline suppression: base collection incomplete "
            "(head={} base={}) — leaving introduced_by_pr unknown",
            sorted(expected),
            sorted(collection.succeeded_manifest_ids),
        )
        return annotate_introduced_by_pr(scoped, base_run_performed=base_run_performed)

    scoped = introduced_by_base_diff(scoped, collection.findings)
    suppression = suppress_baseline_findings(
        head_findings=scoped,
        base_findings=collection.findings,
        diff_text=diff_text,
        base_comparison=base_comparison,
        scope=diff_scope,
    )
    log_suppression_audit(suppression.audit_trail)
    logger.info(
        "baseline suppression: reported={} suppressed={}",
        len(suppression.reported),
        len(suppression.suppressed),
    )
    return suppression.reported


def run_analyzer_pipeline(
    *,
    repo_root: Path,
    changed_files: list[str],
    tier: TrustTier,
    diff_text: str = "",
    inline_budget: int | None = None,
    offline: bool = False,
    base_ref: str | None = None,
    shell: str = "restricted",
    mode: AnalyzersMode = "auto",
) -> AnalyzerRunState:
    """Run enabled analyzers end-to-end and return scoped, budgeted findings.

    ``shell`` is the run's shell policy (``ctx.payload.shell``). Under
    ``"disabled"`` only manifests whose argv mergeCraft ships are selected, and
    repo-provided binaries may not stand in for the pinned ones (#35, D5).

    ``mode`` is the ``analyzers:`` input (``ctx.analyzers_mode``). It narrows
    *selection* only: ``untrusted-only`` — which ``auto`` resolves to on an
    untrusted run (D8) — evaluates manifests at the untrusted tier and
    withholds those needing repo-provided tooling. Execution still uses the
    derived ``tier``, so a mode can never widen what a run may see (#38).
    """
    from mergecraft.tracing.tracer import get_tracer_from_settings

    full_settings = load_repo_settings(root=repo_root, load_learnings_files=False)
    tracer = get_tracer_from_settings(full_settings)
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

    repo_binaries_allowed = allow_repo_provided_binaries(shell=shell)
    effective_mode = resolve_effective_analyzers_mode(mode=mode, tier=tier)
    selection_tier = resolve_selection_tier(mode=effective_mode, tier=tier)
    tier_skip_cause = (
        "analyzers: untrusted-only"
        if selection_tier == "untrusted" and tier == "trusted"
        else "fork PR / pull_request_target"
    )

    with tracer.start_span(
        "mergecraft.analyzers.pipeline",
        attrs_source=lambda: {
            "tier": tier,
            "shell": shell,
            "analyzers.mode": mode,
            "analyzers.effective_mode": effective_mode,
            "analyzers.selection_tier": selection_tier,
            "changed_file_count": len(changed_files),
        },
    ) as parent_span:
        rows: list[AnalyzerStatusRow] = []
        raw_findings: list[Finding] = []
        head_succeeded_manifest_ids: set[str] = set()

        from mergecraft.analyzers.adapters import run_adapter

        for manifest in manifests:
            decision = evaluate_manifest_for_tier(
                manifest=manifest, tier=selection_tier, cause=tier_skip_cause
            )
            if not decision.skipped:
                decision = evaluate_manifest_for_shell(manifest=manifest, shell=shell)
            if not decision.skipped:
                decision = evaluate_manifest_for_mode(manifest=manifest, mode=effective_mode)
            if decision.skipped:
                rows.append(
                    AnalyzerStatusRow(
                        id=manifest.id,
                        status="unavailable",
                        reason=decision.reason,
                    )
                )
                continue
            run_attrs: dict[str, Any] = {"analyzer.id": manifest.id}
            parent_id = parent_span.span_id if hasattr(parent_span, "span_id") else None
            with tracer.start_span(
                "analyzer.run",
                parent_span_id=parent_id,
                attrs_source=_snapshot_attrs(run_attrs),
            ) as child_span:
                run_started = time.perf_counter()
                exit_code = 0
                findings_count = 0
                try:
                    result = run_adapter(
                        tool_id=manifest.id,
                        repo_root=repo_root,
                        changed_files=changed_files,
                        tier=tier,
                        base_ref=base_ref,
                        offline=offline,
                        allow_repo_binaries=repo_binaries_allowed,
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
                    exit_code = 1
                    run_attrs["analyzer.exit_code"] = exit_code
                    run_attrs["analyzer.findings_count"] = 0
                    run_attrs["analyzer.duration_ms"] = round(
                        (time.perf_counter() - run_started) * 1000
                    )
                    run_attrs["error"] = str(exc)
                    child_span.set_status("error", str(exc))
                    continue

                if result.skipped:
                    if result.findings:
                        raw_findings.extend(result.findings)
                    rows.append(
                        AnalyzerStatusRow(
                            id=manifest.id,
                            status="unavailable",
                            reason=result.skip_reason,
                        )
                    )
                    run_attrs["analyzer.exit_code"] = 0
                    run_attrs["analyzer.findings_count"] = 0
                    run_attrs["analyzer.duration_ms"] = round(
                        (time.perf_counter() - run_started) * 1000
                    )
                    run_attrs["analyzer.skipped"] = True
                    continue

                findings_count = len(result.findings)
                status = "failed" if result.findings else "passed"
                head_succeeded_manifest_ids.add(manifest.id)
                rows.append(
                    AnalyzerStatusRow(
                        id=manifest.id,
                        status=status,
                        finding_count=findings_count,
                    )
                )
                raw_findings.extend(result.findings)
                run_attrs["analyzer.exit_code"] = exit_code
                run_attrs["analyzer.findings_count"] = findings_count
                run_attrs["analyzer.duration_ms"] = round(
                    (time.perf_counter() - run_started) * 1000
                )

        learnings_text = _load_learnings(repo_root)
        diff_scope: DiffScope | None = None
        if diff_text.strip():
            diff_scope = parse_diff_scope(diff_text)
            scoped = scope_findings(
                raw_findings,
                diff_text=diff_text,
                repo_root=repo_root,
                learnings_text=learnings_text,
                scope=diff_scope,
            )
        else:
            scoped = suppress_withdrawn_findings(raw_findings, learnings_text)

        from mergecraft.utils.learnings import apply_repo_memory_to_findings

        scoped = apply_repo_memory_to_findings(scoped, repo_root=repo_root, trust_tier=tier)

        base_run = base_comparison_available(
            base_comparison=settings.base_comparison,
            offline=offline,
        )
        scoped = _apply_baseline_suppression(
            scoped,
            repo_root=repo_root,
            manifests=manifests,
            changed_files=changed_files,
            diff_text=diff_text,
            base_comparison=settings.base_comparison,
            tier=tier,
            base_ref=base_ref,
            offline=offline,
            allow_repo_binaries=repo_binaries_allowed,
            base_run_performed=base_run,
            diff_scope=diff_scope,
            head_succeeded_manifest_ids=frozenset(head_succeeded_manifest_ids),
        )

        # Analyzer path: dedupe only — rubric/causality stay on agent findings.
        clustered = dedupe_findings(cluster_findings(scoped))
        budget = (
            inline_budget
            if inline_budget is not None
            else (settings.inline_budget or default_inline_budget())
        )
        placement = place_findings(clustered, inline_budget=budget)

        serialized = [_serialize_finding(f) for f in clustered]
        inline_short_ids = placement.short_ids
        inline_payload: list[dict[str, Any]] = []
        for item in placement.inline:
            if isinstance(item, Finding):
                payload: dict[str, Any] = {
                    "finding": _serialize_finding(item),
                    "inlineBody": format_analyzer_inline_body(
                        item,
                        short_id=inline_short_ids[item.fingerprint],
                    ),
                    "path": item.path,
                }
                if item.start_line is not None:
                    payload["line"] = item.start_line
                inline_payload.append(payload)

        lock_path = repo_root / ".mergecraft" / "analyzers.lock"
        digest = lock_digest(lock_path)
        summary = _build_pre_merge_summary(rows, lockfile_digest_value=digest)
        deferred_findings = [finding_to_deferred_row(finding) for finding in placement.deferred]

        executed = [row for row in rows if row.status in {"passed", "failed"}]
        if not executed:
            run_state = AnalyzerRunState(
                ran=False,
                reason=(
                    "every enabled analyzer was skipped in this environment — report the "
                    "Analyzers pre-merge row as skipped, not failed"
                ),
                analyzers=rows,
                findings=serialized,
                inline=inline_payload,
                mechanical_section=placement.mechanical_section,
                deferred_findings=deferred_findings,
                pre_merge_summary=summary,
                lockfile_digest=digest,
            )
            sync_deferred_section(run_state)
            return run_state

        run_state = AnalyzerRunState(
            ran=True,
            analyzers=rows,
            findings=serialized,
            inline=inline_payload,
            mechanical_section=placement.mechanical_section,
            deferred_findings=deferred_findings,
            pre_merge_summary=summary,
            lockfile_digest=digest,
        )
        sync_deferred_section(run_state)
        return run_state


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


__all__ = [
    "CatalogScanStatus",
    "analyzer_run_metadata",
    "catalog_scan_status",
    "filter_for_review",
    "run_analyzer_pipeline",
]
