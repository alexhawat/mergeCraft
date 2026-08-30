"""Analyzer MCP tools — run catalog analyzers and retrieve scoped findings."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.mcp.shared import ToolClass, execute, tool
from mergecraft.mcp.tool_state import AnalyzerRunState, analyzer_run_key, primary_repo_state
from mergecraft.modes._api_only_scope import API_ONLY_SCOPE, API_ONLY_SCOPE_GUIDANCE

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext


def _load_diff_text(diff_path: Path | None) -> str:
    if diff_path is None or not diff_path.is_file():
        return ""
    return diff_path.read_text(encoding="utf-8")


def _resolve_tier(ctx: ToolContext) -> str:
    return ctx.trust_tier


def _store_run_state(ctx: ToolContext, state: AnalyzerRunState) -> None:
    from mergecraft.findings.ledger import record_deferred_from_analyzer_run

    session_ids = set(ctx.tool_state.verified_ids)
    prior = ctx.tool_state.analyzer_run
    if prior is not None:
        session_ids |= set(prior.verified_ids)
    state.verified_ids = set(state.verified_ids) | session_ids
    ctx.tool_state.analyzer_run = state
    ctx.tool_state.verified_ids = session_ids | set(state.verified_ids)
    record_deferred_from_analyzer_run(ctx.tool_state, state)


def run_analyzers_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]) -> dict[str, Any]:
        state = primary_repo_state(ctx.tool_state)
        repo_root = Path(params.get("repo_root") or state.dir)
        changed = [str(f) for f in (params.get("changed_files") or [])]
        diff_path = params.get("diff_path")
        diff_text = _load_diff_text(Path(diff_path)) if diff_path else ""

        from mergecraft.config import load_repo_settings

        settings = load_repo_settings(root=repo_root, load_learnings_files=False).analyzers
        offline = ctx.payload.event.trigger == "unknown"
        from mergecraft.analyzers.pipeline import run_analyzer_pipeline

        base_ref = params.get("base_ref")
        if base_ref is not None:
            base_ref = str(base_ref).strip() or None

        # An offline `mergecraft review` already ran this pipeline as a pre-pass
        # and recorded the inputs it used. Reuse that result when every keyed
        # input matches, rather than provisioning and executing every analyzer a
        # second time over the same diff. No recorded key — the GitHub Action
        # path, which has no pre-pass — always runs the pipeline.
        request_key = analyzer_run_key(
            repo_root=repo_root,
            changed_files=changed,
            tier=_resolve_tier(ctx),
            shell=str(ctx.payload.shell),
            mode=ctx.analyzers_mode,
            inline_budget=settings.inline_budget,
            offline=offline,
            base_ref=base_ref,
            diff_text=diff_text,
        )
        prior = ctx.tool_state.analyzer_run
        prior_key = prior.key if prior is not None else None
        if prior is not None and prior_key is not None and prior_key.matches(request_key):
            logger.info("analyzers: reusing pre-computed run (inputs unchanged)")
            run_state = prior
        else:
            run_state = run_analyzer_pipeline(
                repo_root=repo_root,
                changed_files=changed,
                tier=_resolve_tier(ctx),  # type: ignore[arg-type]  # — _resolve_tier returns str; run_analyzer_pipeline expects AnalyzerTier literal
                diff_text=diff_text,
                inline_budget=settings.inline_budget,
                offline=offline,
                base_ref=base_ref,
                # #35 — the surface now registers under `shell: disabled`, so the
                # shell has to reach manifest selection or the withhold is lost.
                shell=str(ctx.payload.shell),
                # #38 — likewise the mode: `untrusted-only` (and the `auto` that
                # resolves to it on untrusted runs) only narrows selection if it
                # actually reaches the pipeline.
                mode=ctx.analyzers_mode,
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
        from mergecraft.analyzers.pipeline import catalog_scan_status

        scan_status = catalog_scan_status(run_state)
        payload["catalogScanStatus"] = str(scan_status)
        if not run_state.ran:
            payload["reason"] = run_state.reason or "analyzer catalog unavailable"
        if run_state.mechanical_section:
            payload["mechanicalSection"] = run_state.mechanical_section
        if run_state.deferred_section:
            payload["deferredSection"] = run_state.deferred_section
        if ctx.tool_state.review_scope == API_ONLY_SCOPE:
            payload["scopeNotice"] = API_ONLY_SCOPE_GUIDANCE
        logger.info(
            "analyzers: ran={} tools={} findings={} catalog={}",
            run_state.ran,
            len(run_state.analyzers),
            len(run_state.findings),
            scan_status,
        )
        return payload

    return tool(
        name="run_analyzers",
        tool_class=ToolClass.ANALYSIS,
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
                "base_ref": {
                    "type": "string",
                    "description": (
                        "Optional git base ref for differential contract analyzers "
                        "(oasdiff, squawk, buf). Defaults to fixture-base companions or "
                        "the repo merge base when available."
                    ),
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
        omit_pending_major = bool(params.get("verified_only"))
        findings = list(run_state.findings)
        inline = list(run_state.inline)
        if omit_pending_major:
            from mergecraft.analyzers.finding import Finding
            from mergecraft.analyzers.review_gate import filter_for_review

            finding_objs = [Finding.model_validate(row) for row in findings]
            published = filter_for_review(
                finding_objs,
                verified_ids=set(run_state.verified_ids),
                require_verification=True,
            )
            published_fps = {item.fingerprint for item in published}
            findings = [row for row in findings if row.get("fingerprint") in published_fps]
            inline = [
                row for row in inline if row.get("finding", {}).get("fingerprint") in published_fps
            ]
        return {
            "available": True,
            "ran": run_state.ran,
            "findings": findings,
            "inline": inline,
            "mechanicalSection": run_state.mechanical_section,
            "deferredSection": run_state.deferred_section,
            "preMergeSummary": run_state.pre_merge_summary,
            "lockfileDigest": run_state.lockfile_digest,
        }

    return tool(
        name="analyzer_findings",
        tool_class=ToolClass.ANALYSIS,
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
    "run_analyzers_tool",
]
