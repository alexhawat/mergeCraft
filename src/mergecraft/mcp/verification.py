"""Verification MCP tools — route agent-authored findings to the verifier (C6).

Verification used to be reachable only for analyzer and CI findings: the
severity gate in ``agents/verifier.py`` had no source condition, but both call
sites (``analyzers/review_gate.py``, ``ci/verification.py``) only ever fed it
tool output. The findings the reviewing model wrote itself — the ones most
likely to be wrong — went straight to publication.

These two tools are the missing seam. ``verify_agent_findings`` takes the
reviewer's drafted findings *before* it calls ``create_pull_request_review`` and
returns a budgeted dispatch queue for ``mergecraft-verifier``.
``record_finding_verdict`` takes the verdict back and routes a ``drop`` into the
same withdrawn-findings memory analyzer suppression already reads, so a refuted
finding stays refuted.

Exports:
    record_finding_verdict_tool: Record one verifier verdict for a finding.
    verify_agent_findings_tool: Plan verification dispatches for agent findings.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.mcp.shared import execute, tool
from mergecraft.mcp.tool_state import primary_repo_state
from mergecraft.utils.learnings import learnings_file_path

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext


def _learnings_text(ctx: ToolContext) -> str:
    path = ctx.tool_state.learnings_file_path or learnings_file_path(ctx.tmpdir)
    candidate = Path(path)
    if not candidate.is_file():
        return ""
    return candidate.read_text(encoding="utf-8")


def verify_agent_findings_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]) -> dict[str, Any]:
        from mergecraft.agents.verifier import (
            VERIFIER_AGENT_NAME,
            AgentFinding,
            plan_agent_verifications,
        )
        from mergecraft.config import load_repo_settings

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
        plan = plan_agent_verifications(
            findings,
            budget=settings.inline_budget,
            learnings_text=_learnings_text(ctx),
            repo_root=repo_root,
        )
        logger.info(
            "agent-finding verification: {} queued, {} already withdrawn, {} over budget "
            "(budget={})",
            len(plan.dispatch),
            len(plan.skipped_withdrawn),
            len(plan.skipped_over_budget),
            plan.budget,
        )
        return {
            "ready": True,
            "subagent": VERIFIER_AGENT_NAME,
            "budget": plan.budget,
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
        description=(
            "Queue the Critical/Major findings you wrote yourself for the "
            "mergecraft-verifier subagent, before you publish them. Returns one dispatch "
            "prompt per finding — already carrying the finding, its cited file and the "
            "withdrawn-findings section — capped at the repo's inline budget, with "
            "findings the author already refuted skipped."
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
        from mergecraft.agents.verifier import JudgeVerdict, record_verifier_verdict

        verdict = JudgeVerdict(
            fingerprint=str(params["fingerprint"]),
            verdict=params["verdict"],
            reason=str(params.get("reason") or ""),
            new_severity=(str(params["new_severity"]) if params.get("new_severity") else None),
        )
        path = ctx.tool_state.learnings_file_path or learnings_file_path(ctx.tmpdir)
        outcome = record_verifier_verdict(verdict, learnings_path=Path(path))
        if outcome.recorded_withdrawn:
            ctx.tool_state.was_updated = True
        return {
            "recorded": True,
            "fingerprint": outcome.fingerprint,
            "verdict": outcome.verdict,
            "publishable": outcome.publishable,
            "recordedWithdrawn": outcome.recorded_withdrawn,
            "reason": outcome.reason,
        }

    return tool(
        name="record_finding_verdict",
        mutates=True,
        description=(
            "Record one mergecraft-verifier verdict for a finding. confirm and downgrade "
            "return publishable:true; drop writes the reason under the withdrawn-findings "
            "heading so the finding stays refuted on later runs."
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
