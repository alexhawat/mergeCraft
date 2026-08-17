"""Verification MCP tools — route agent-authored findings to the judge (C6, D14).

Verification used to be reachable only for analyzer and CI findings: the
severity gate in ``agents/verifier.py`` had no source condition, but both call
sites (``analyzers/review_gate.py``, ``ci/verification.py``) only ever fed it
tool output. The findings the reviewing model wrote itself — the ones most
likely to be wrong — went straight to publication.

These two tools are the missing seam. ``verify_agent_findings`` takes the
reviewer's drafted findings *before* it calls ``create_pull_request_review``,
returns a budgeted dispatch queue for ``mergecraft-verifier``, and refuses to
plan anything until a deterministic check has run (D14 — an LLM judge is a
secondary signal). ``record_finding_verdict`` takes the verdict back, logs the
pinned judge identity with it (#45), and routes a ``drop`` into the same
withdrawn-findings memory analyzer suppression already reads.

Exports:
    record_finding_verdict_tool: Record one judge verdict for a finding.
    verify_agent_findings_tool: Plan verification dispatches for agent findings.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.mcp.shared import ToolClass, execute, tool
from mergecraft.mcp.tool_state import AnalyzerRunState, primary_repo_state
from mergecraft.utils.learnings import learnings_file_path

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext

_NOT_READY_REASON = (
    "no deterministic check has run yet. LLM judges are secondary evaluators — call "
    "run_analyzers (and run_static_checks when available) first so mechanically "
    "checkable facts are settled before any judge sees the finding (D14, #45)."
)


def _deterministic_checks_ran(ctx: ToolContext) -> list[str]:
    """Return the deterministic checks this run has completed, newest first.

    Only checks that actually executed count. ``run_analyzers`` returning
    ``ran:false`` still counts as a completed pass — the repo simply had no
    analyzer to match — but a run that never called it at all does not, which
    is the ordering D14 asks for.
    """
    completed: list[str] = []
    if ctx.tool_state.analyzer_run is not None:
        completed.append("run_analyzers")
    if ctx.tool_state.static_checks_ran:
        completed.append("run_static_checks")
    return completed


def _learnings_text(ctx: ToolContext) -> str:
    path = ctx.tool_state.learnings_file_path or learnings_file_path(ctx.tmpdir)
    candidate = Path(path)
    if not candidate.is_file():
        return ""
    return candidate.read_text(encoding="utf-8")


def _persist_confirmed_fingerprint(
    ctx: ToolContext,
    fingerprint: str,
    *,
    severity: str | None = None,
) -> None:
    """Record a live confirm outside replaceable ``analyzer_run`` state."""
    ctx.tool_state.verified_ids.add(fingerprint)
    run = ctx.tool_state.analyzer_run
    if run is None:
        run = AnalyzerRunState(ran=True)
        ctx.tool_state.analyzer_run = run
    run.verified_ids.add(fingerprint)
    row = _finding_row_for_fingerprint(ctx, fingerprint)
    if row is None:
        if not severity:
            return
        row = {"fingerprint": fingerprint, "severity": severity}
    else:
        row.setdefault("fingerprint", fingerprint)
        if severity:
            row["severity"] = severity
    existing = {
        item.get("fingerprint")
        for item in ctx.tool_state.confirmed_findings
        if isinstance(item, dict)
    }
    if fingerprint not in existing:
        ctx.tool_state.confirmed_findings.append(row)


def _finding_row_for_fingerprint(ctx: ToolContext, fingerprint: str) -> dict[str, Any] | None:
    run = ctx.tool_state.analyzer_run
    if run is not None:
        for item in run.findings:
            if isinstance(item, dict) and item.get("fingerprint") == fingerprint:
                return dict(item)
    for item in ctx.tool_state.agent_findings:
        if item.get("fingerprint") == fingerprint:
            return dict(item)
    return None


def _run_lane(ctx: ToolContext) -> str | None:
    """Classify the run's blast-radius lane, or ``None`` when unknowable.

    Reuses the packet's classifier rather than a second rule set, so the lane
    a judge is held to is the same lane the merge evidence packet reports.
    """
    from mergecraft.evidence.run_packet import classify_run_blast_radius

    state = primary_repo_state(ctx.tool_state)
    for attr in ("diff_path", "incremental_diff_path"):
        raw = getattr(state, attr, None)
        if not raw:
            continue
        path = Path(raw)
        if not path.is_file():
            continue
        classification = classify_run_blast_radius(path.read_text(encoding="utf-8"))
        if classification is not None:
            return classification.lane
    return None


def verify_agent_findings_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]) -> dict[str, Any]:
        from mergecraft.agents.verifier import (
            VERIFIER_AGENT_NAME,
            VERIFIER_RUBRIC_VERSION,
            AgentFinding,
            plan_agent_verifications,
        )
        from mergecraft.config import load_repo_settings

        completed = _deterministic_checks_ran(ctx)
        if not completed:
            return {"ready": False, "reason": _NOT_READY_REASON, "dispatch": []}

        state = primary_repo_state(ctx.tool_state)
        repo_root = Path(state.dir)
        settings = load_repo_settings(root=repo_root, load_learnings_files=False).analyzers

        findings = [
            AgentFinding(
                path=str(row.get("path", "")),
                body=str(row.get("body", "")),
                severity=str(row.get("severity", "Minor")),
                line=int(row["line"]) if row.get("line") is not None else None,
                fingerprint=str(row.get("fingerprint", "") or ""),
            )
            for row in (params.get("findings") or [])
        ]
        stored: dict[str, dict[str, Any]] = {}
        for item in ctx.tool_state.agent_findings:
            fingerprint = item.get("fingerprint") if isinstance(item, dict) else None
            if isinstance(fingerprint, str) and fingerprint:
                stored[fingerprint] = item
        for finding in findings:
            row = finding.model_dump(mode="json")
            row["fingerprint"] = finding.identity()
            stored[str(row["fingerprint"])] = row
        ctx.tool_state.agent_findings = list(stored.values())
        plan = plan_agent_verifications(
            findings,
            budget=settings.inline_budget,
            learnings_text=_learnings_text(ctx),
            repo_root=repo_root,
        )
        logger.info(
            "agent-finding verification: {} queued, {} already withdrawn, {} over budget "
            "(budget={}, deterministic_checks={})",
            len(plan.dispatch),
            len(plan.skipped_withdrawn),
            len(plan.skipped_over_budget),
            plan.budget,
            ",".join(completed),
        )
        return {
            "ready": True,
            "subagent": VERIFIER_AGENT_NAME,
            "rubricVersion": VERIFIER_RUBRIC_VERSION,
            "deterministicChecks": completed,
            "budget": plan.budget,
            "lane": _run_lane(ctx),
            "dispatch": [
                {
                    "fingerprint": item.fingerprint,
                    "path": item.finding.path,
                    "line": item.finding.line,
                    "severity": item.finding.severity,
                    "citedFile": item.cited_file,
                    "prompt": item.brief,
                }
                for item in plan.dispatch
            ],
            "skippedWithdrawn": plan.skipped_withdrawn,
            "skippedOverBudget": plan.skipped_over_budget,
            "skippedBelowSeverity": plan.skipped_below_severity,
        }

    return tool(
        name="verify_agent_findings",
        tool_class=ToolClass.VERIFICATION,
        description=(
            "Queue the Critical/Major findings you wrote yourself for the "
            "mergecraft-verifier subagent, before you publish them. Returns one dispatch "
            "prompt per finding — already carrying the finding, its cited file and the "
            "withdrawn-findings section — capped at the repo's inline budget, with "
            "findings the author already refuted skipped. Returns ready:false until a "
            "deterministic check has run: the judge is a secondary signal, not a "
            "substitute for analyzers or static gates."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "findings": {
                    "type": "array",
                    "description": "Your drafted findings, pre-publication.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "line": {"type": "number"},
                            "severity": {
                                "type": "string",
                                "enum": ["Critical", "Major", "Minor", "Trivial"],
                            },
                            "body": {"type": "string"},
                            "fingerprint": {"type": "string"},
                        },
                        "required": ["path", "body", "severity"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["findings"],
            "additionalProperties": False,
        },
        execute=execute(_run, "verify_agent_findings"),
    )


def record_finding_verdict_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]) -> dict[str, Any]:
        from mergecraft.agents.verifier import JudgeVerdict, judge_pin, record_verifier_verdict

        completed = _deterministic_checks_ran(ctx)
        if not completed:
            return {"recorded": False, "reason": _NOT_READY_REASON}

        pin = judge_pin(provider=ctx.agent_id, resolved_model=ctx.resolved_model)
        verdict = JudgeVerdict(
            fingerprint=str(params["fingerprint"]),
            verdict=params["verdict"],
            reason=str(params.get("reason") or ""),
            pin=pin,
            deterministic_checks=completed,
            new_severity=(str(params["new_severity"]) if params.get("new_severity") else None),
            lane=_run_lane(ctx),
        )
        path = ctx.tool_state.learnings_file_path or learnings_file_path(ctx.tmpdir)
        outcome = record_verifier_verdict(verdict, learnings_path=Path(path))
        if outcome.recorded_withdrawn:
            ctx.tool_state.was_updated = True
        if outcome.verdict == "confirm" and outcome.publishable:
            _persist_confirmed_fingerprint(ctx, outcome.fingerprint)
        elif outcome.verdict == "downgrade" and outcome.publishable:
            from mergecraft.agents.gates import BLOCKING_SEVERITIES

            new_severity = verdict.new_severity
            if new_severity in BLOCKING_SEVERITIES:
                _persist_confirmed_fingerprint(
                    ctx,
                    outcome.fingerprint,
                    severity=new_severity,
                )
            else:
                ctx.tool_state.verified_ids.discard(outcome.fingerprint)
                if ctx.tool_state.analyzer_run is not None:
                    ctx.tool_state.analyzer_run.verified_ids.discard(outcome.fingerprint)
                ctx.tool_state.confirmed_findings = [
                    row
                    for row in ctx.tool_state.confirmed_findings
                    if row.get("fingerprint") != outcome.fingerprint
                ]
        return {
            "recorded": True,
            "fingerprint": outcome.fingerprint,
            "verdict": outcome.verdict,
            "publishable": outcome.publishable,
            "recordedWithdrawn": outcome.recorded_withdrawn,
            "escalatedToHuman": outcome.escalated_to_human,
            "reason": outcome.reason,
            "judgeModel": pin.model,
            "judgeProvider": pin.provider,
            "judgeModelPinned": pin.model_pinned,
            "judgeVersion": pin.judge_version,
            "rubricVersion": pin.rubric_version,
        }

    return tool(
        name="record_finding_verdict",
        tool_class=ToolClass.REVIEW_WRITE,
        mutates=True,
        description=(
            "Record one mergecraft-verifier verdict for a finding. confirm and downgrade "
            "return publishable:true; drop writes the reason under the withdrawn-findings "
            "heading so the finding stays refuted on later runs — except on a high-stakes "
            "blast-radius lane, where one judge cannot retire a finding and the drop is "
            "escalated instead. The judge's model, provider, judge version and rubric "
            "version are logged with the verdict."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "fingerprint": {
                    "type": "string",
                    "description": "The fingerprint verify_agent_findings returned.",
                },
                "verdict": {"type": "string", "enum": ["confirm", "downgrade", "drop"]},
                "reason": {
                    "type": "string",
                    "description": (
                        "The verifier's reason. On a drop this is written verbatim into "
                        "the withdrawn-findings section, so write it for a future reader."
                    ),
                },
                "new_severity": {
                    "type": "string",
                    "enum": ["Critical", "Major", "Minor", "Trivial"],
                    "description": "Required on a downgrade verdict.",
                },
            },
            "required": ["fingerprint", "verdict", "reason"],
            "additionalProperties": False,
        },
        execute=execute(_run, "record_finding_verdict"),
    )


__all__ = ["record_finding_verdict_tool", "verify_agent_findings_tool"]
