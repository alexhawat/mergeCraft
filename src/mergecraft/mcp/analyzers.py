"""Analyzer MCP tools — run catalog analyzers and retrieve scoped findings."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from loguru import logger

from mergecraft.analyzers.adapters import run_adapter
from mergecraft.analyzers.budget import default_inline_budget, place_findings
from mergecraft.analyzers.cluster import cluster_findings
from mergecraft.analyzers.finding import Finding
from mergecraft.analyzers.lockfile import lock_digest
from mergecraft.analyzers.registry import detect_enabled
from mergecraft.analyzers.scope import (
    annotate_introduced_by_pr,
    scope_findings,
    suppress_withdrawn_findings,
)
from mergecraft.analyzers.trust import evaluate_manifest_for_tier
from mergecraft.config import load_repo_settings
from mergecraft.mcp.review import format_analyzer_inline_body
from mergecraft.mcp.shared import execute, tool
from mergecraft.mcp.tool_state import (
    AnalyzerRunState,
    AnalyzerStatusRow,
    primary_repo_state,
)

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext

TrustTier = Literal["trusted", "untrusted"]


def _resolve_tier(ctx: ToolContext) -> TrustTier:
    extra = ctx.payload.extra.get("analyzer_trust_tier")
    if extra in {"trusted", "untrusted"}:
        return cast("TrustTier", extra)
    return ctx.trust_tier


def _serialize_finding(finding: Finding) -> dict[str, Any]:
    return finding.model_dump()


def _load_diff_text(diff_path: Path | None) -> str:
    if diff_path is None or not diff_path.is_file():
        return ""
    return diff_path.read_text(encoding="utf-8")


def _load_learnings(repo_root: Path) -> str:
    learnings = repo_root / ".mergecraft" / "learnings.md"
    if not learnings.is_file():
        return ""
    return learnings.read_text(encoding="utf-8")


def _settings_dict(repo_root: Path) -> dict[str, Any]:
    settings = load_repo_settings(root=repo_root, load_learnings_files=False)
    return {
        "analyzers": {
            "enabled": settings.analyzers.enabled,
            "inlineBudget": settings.analyzers.inline_budget,
            "baseComparison": settings.analyzers.base_comparison,
            "overrides": {
                analyzer_id: {"enabled": override.enabled}
                for analyzer_id, override in settings.analyzers.overrides.items()
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
) -> AnalyzerRunState:
    """Run enabled analyzers end-to-end and return scoped, budgeted findings."""
    settings = _settings_dict(repo_root)
    if not settings.get("analyzers", {}).get("enabled", True):
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
        settings_overrides=settings,
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
            findings = run_adapter(
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

        status = "failed" if findings else "passed"
        rows.append(
            AnalyzerStatusRow(
                id=manifest.id,
                status=status,
                finding_count=len(findings),
            )
        )
        raw_findings.extend(findings)

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
    scoped = annotate_introduced_by_pr(scoped, base_run_performed=False)
    clustered = cluster_findings(scoped)
    budget = inline_budget if inline_budget is not None else default_inline_budget()
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


def _store_run_state(ctx: ToolContext, state: AnalyzerRunState) -> None:
    ctx.tool_state.analyzer_run = state


def run_analyzers_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]) -> dict[str, Any]:
        state = primary_repo_state(ctx.tool_state)
        repo_root = Path(params.get("repo_root") or state.dir)
        changed = [str(f) for f in (params.get("changed_files") or [])]
        diff_path = params.get("diff_path")
        diff_text = _load_diff_text(Path(diff_path)) if diff_path else ""

        tier = _resolve_tier(ctx)
        run_state = run_analyzer_pipeline(
            repo_root=repo_root,
            changed_files=changed,
            tier=tier,
            diff_text=diff_text,
        )
        _store_run_state(ctx, run_state)

        payload: dict[str, Any] = {
            "ran": run_state.ran,
            "analyzers": [
                {
                    "id": row.id,
                    "status": row.status,
                    "reason": row.reason,
                    "findingCount": row.finding_count,
                }
                for row in run_state.analyzers
            ],
            "findingCount": len(run_state.findings),
            "preMergeSummary": run_state.pre_merge_summary,
            "lockfileDigest": run_state.lockfile_digest,
        }
        if not run_state.ran:
            payload["reason"] = run_state.reason
        if run_state.mechanical_section:
            payload["mechanicalSection"] = run_state.mechanical_section
        logger.info(
            "analyzers: ran={} tools={} findings={}",
            run_state.ran,
            len(run_state.analyzers),
            len(run_state.findings),
        )
        return payload

    return tool(
        name="run_analyzers",
        timeout_ms=600_000,
        description=(
            "Run mergeCraft catalog analyzers over the changed files and return per-analyzer "
            "status plus normalized findings scoped to the diff. Returns ran:false when no "
            "analyzer matched the diff or every enabled analyzer was skipped in this "
            "environment — report the Analyzers pre-merge row as skipped, never as a finding. "
            "Only analyzer findings with status failed carry review signal; unavailable means "
            "the tool did not run here."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "changed_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Repo-relative paths changed by the PR.",
                },
                "repo_root": {
                    "type": "string",
                    "description": "Optional repo root override (defaults to the checked-out repo).",
                },
                "diff_path": {
                    "type": "string",
                    "description": "Optional on-disk unified diff for scoping findings to hunks.",
                },
            },
            "additionalProperties": False,
        },
        execute=execute(_run, "run_analyzers"),
    )


def analyzer_findings_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]) -> dict[str, Any]:
        run_state = ctx.tool_state.analyzer_run
        if run_state is None:
            return {
                "available": False,
                "reason": "call run_analyzers first",
                "findings": [],
                "inline": [],
            }
        verified_only = bool(params.get("verified_only"))
        findings = list(run_state.findings)
        inline = list(run_state.inline)
        if verified_only:
            findings = [row for row in findings if row.get("severity") not in {"Critical", "Major"}]
            inline = [
                row
                for row in inline
                if row.get("finding", {}).get("severity") not in {"Critical", "Major"}
            ]
        return {
            "available": True,
            "ran": run_state.ran,
            "findings": findings,
            "inline": inline,
            "mechanicalSection": run_state.mechanical_section,
            "preMergeSummary": run_state.pre_merge_summary,
            "lockfileDigest": run_state.lockfile_digest,
        }

    return tool(
        name="analyzer_findings",
        description=(
            "Retrieve the scoped, clustered, budgeted analyzer finding set from the most recent "
            "run_analyzers call — inline bodies include tool/rule citations and confidence tags. "
            "Use this for placement instead of re-deriving findings from raw tool output."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "verified_only": {
                    "type": "boolean",
                    "description": (
                        "When true, omit Critical/Major findings pending verification (D11)."
                    ),
                }
            },
            "additionalProperties": False,
        },
        execute=execute(_run, "analyzer_findings"),
    )


__all__ = [
    "analyzer_findings_tool",
    "run_analyzer_pipeline",
    "run_analyzers_tool",
]
