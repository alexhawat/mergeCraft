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

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.config import load_repo_settings
from mergecraft.findings.agent_adapter import (
    finding_for_publication_validation,
    normalize_agent_findings_via_pipeline,
)
from mergecraft.findings.causality import CausalityValidationError, validate_blocking_finding
from mergecraft.mcp.shared import ToolClass, execute, tool
from mergecraft.mcp.tool_state import AnalyzerRunState, primary_repo_state
from mergecraft.review_taxonomy import FINDING_SEVERITIES
from mergecraft.utils.learnings import learnings_file_path

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext

_NOT_READY_REASON = (
    "no deterministic check has run yet. LLM judges are secondary evaluators — call "
    "run_analyzers (and run_static_checks when available) first so mechanically "
    "checkable facts are settled before any judge sees the finding (D14, #45)."
)


def _validate_publication_finding(
    ctx: ToolContext,
    fingerprint: str,
    *,
    causality: str,
    severity: str | None = None,
) -> None:
    """Require structured causality before a blocking finding is confirmed (D2)."""
    row = _finding_row_for_fingerprint(ctx, fingerprint)
    if row is None:
        msg = f"finding fingerprint {fingerprint!r} not found for blocking publication validation"
        raise ValueError(msg)
    finding = finding_for_publication_validation(
        row,
        fingerprint=fingerprint,
        causality=causality,
        severity=severity,
    )
    try:
        validate_blocking_finding(finding)
    except CausalityValidationError as exc:
        raise ValueError(str(exc)) from exc


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
            msg = f"finding fingerprint {fingerprint!r} not found for confirm persistence"
            raise ValueError(msg)
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


def _apply_non_blocking_downgrade(
    ctx: ToolContext,
    fingerprint: str,
    *,
    severity: str,
) -> None:
    """Record a downgrade to a non-blocking severity on every row that carries it.

    Dropping the fingerprint from ``verified_ids`` is not enough: the originating
    ``analyzer_run`` row keeps its Critical/Major severity, so the approve gate
    sees it again as an unverified blocker and the downgrade leaves the run worse
    off than doing nothing. The stored severity is rewritten instead.

    Severity is stored in five places, so this is five writes with no
    transaction and no record of whether a row's severity is the original or a
    rewrite. The overlay design that would make it one write is declined and
    written up under "Deferred designs the review rounds declined" in
    ``docs/test-plans/open-issues-sweep-2026-08-19.md``.
    """
    ctx.tool_state.verified_ids.discard(fingerprint)
    if ctx.tool_state.analyzer_run is not None:
        ctx.tool_state.analyzer_run.verified_ids.discard(fingerprint)
        for row in ctx.tool_state.analyzer_run.findings:
            if isinstance(row, dict) and row.get("fingerprint") == fingerprint:
                row["severity"] = severity
    for row in ctx.tool_state.agent_findings:
        if row.get("fingerprint") == fingerprint:
            row["severity"] = severity
    ctx.tool_state.confirmed_findings = [
        row for row in ctx.tool_state.confirmed_findings if row.get("fingerprint") != fingerprint
    ]


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


def _emit_finding_stage(
    ctx: ToolContext,
    findings: Any,
    *,
    stage: str,
) -> None:
    """Emit one ``mergecraft.finding`` lifecycle span per finding (O9/OB4).

    Resolves the tracer from the active span (the ``mergecraft.run`` span is
    open for the whole run, so the finding span inherits ``review.id`` via
    the D4 close-time merge). Total and non-throwing per the tracing
    contract (#56 D6): any failure degrades to a missing span, never a
    failed tool call.
    """
    try:
        from mergecraft.tracing import Span
        from mergecraft.tracing.tracer import _ACTIVE_SPAN

        active = _ACTIVE_SPAN.get()
        if not isinstance(active, Span):
            return
        from mergecraft.tracing.genai import resolve_capture_policy
        from mergecraft.tracing.signals import emit_finding

        policy = resolve_capture_policy(ctx.tool_state.trust_tier)
        for finding in findings or []:
            emit_finding(
                active.tracer,
                fingerprint=str(getattr(finding, "fingerprint", "") or ""),
                stage=stage,
                severity=str(getattr(finding, "severity", "") or "") or None,
                message=str(getattr(finding, "body", "") or "") or None,
                policy=policy,
            )
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("finding span emission failed ({}): {}", stage, exc)


@dataclass(slots=True)
class AgentFindingLike:
    """Minimal row shape for lifecycle span emission (OB4)."""

    fingerprint: str
    severity: str = ""
    body: str = ""

    def __init__(self, fingerprint: str, severity: str = "", body: str = "", **_: Any) -> None:
        # Tolerate extra stored-row keys (path/line/…) — only the three
        # lifecycle fields are read.
        self.fingerprint = fingerprint
        self.severity = severity
        self.body = body


def emit_published_findings(ctx: ToolContext) -> None:
    """Emit the ``published`` lifecycle stage for every confirmed finding.

    Called at the publish seam (``create_pull_request_review``) so the
    documented ``proposed`` → ``verified`` → ``published``/``withdrawn``
    lifecycle is complete in the trace. Non-throwing.
    """
    _emit_finding_stage(
        ctx,
        [
            AgentFindingLike(
                fingerprint=str(row.get("fingerprint", "") or ""),
                severity=str(row.get("severity", "") or ""),
                body=str(row.get("body", "") or ""),
            )
            for row in ctx.tool_state.confirmed_findings
            if isinstance(row, dict) and row.get("fingerprint")
        ],
        stage="published",
    )


def verify_agent_findings_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]) -> dict[str, Any]:
        from mergecraft.agents.verifier import (
            VERIFIER_AGENT_NAME,
            VERIFIER_RUBRIC_VERSION,
            AgentFinding,
            plan_agent_verifications,
        )

        completed = _deterministic_checks_ran(ctx)
        if not completed:
            return {"ready": False, "reason": _NOT_READY_REASON, "dispatch": []}

        state = primary_repo_state(ctx.tool_state)
        repo_root = Path(state.dir)
        repo_settings = load_repo_settings(root=repo_root, load_learnings_files=False)

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
        trust = (
            ctx.tool_state.trust_tier
            if ctx.tool_state.trust_tier in {"trusted", "untrusted"}
            else "trusted"
        )
        normalized_findings = normalize_agent_findings_via_pipeline(
            findings,
            rule_id="agent:draft",
            dedupe=True,
            repo_root=repo_root,
            trust_tier=trust,  # type: ignore[arg-type]  # — trust is str; callee expects TrustTier literal narrowing
        )
        stored: dict[str, dict[str, Any]] = {}
        for item in ctx.tool_state.agent_findings:
            fingerprint = item.get("fingerprint") if isinstance(item, dict) else None
            if isinstance(fingerprint, str) and fingerprint:
                stored[fingerprint] = item
        for finding in normalized_findings:
            row = finding.model_dump(mode="json")
            row["fingerprint"] = finding.identity()
            stored[str(row["fingerprint"])] = row
        ctx.tool_state.agent_findings = list(stored.values())
        _emit_finding_stage(
            ctx, [AgentFindingLike(**row) for row in stored.values()], stage="proposed"
        )
        plan = plan_agent_verifications(
            normalized_findings,
            budget=repo_settings.review.verification_budget,
            learnings_text=_learnings_text(ctx),
            repo_root=repo_root,
        )
        from mergecraft.findings.ledger import (
            ensure_finding_ledger,
            ledger_round_index,
            record_over_budget_verifications,
        )

        record_over_budget_verifications(
            ensure_finding_ledger(ctx.tool_state),
            skipped_over_budget=plan.skipped_over_budget,
            round_index=ledger_round_index(ctx.tool_state),
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
            "withdrawn-findings section — capped at the repo's `review.verificationBudget` "
            "(default 24; `0` = unlimited, not disabled), with findings the author "
            "already refuted skipped. Returns ready:false until a "
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
                                "enum": list(FINDING_SEVERITIES),
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
        from mergecraft.agents.gates import BLOCKING_SEVERITIES
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
            new_severity=JudgeVerdict.parse_severity(params.get("new_severity")),
            lane=_run_lane(ctx),
        )
        path = ctx.tool_state.learnings_file_path or learnings_file_path(ctx.tmpdir)
        outcome = record_verifier_verdict(verdict, learnings_path=Path(path))
        stored_row = next(
            (
                row
                for row in ctx.tool_state.agent_findings
                if isinstance(row, dict) and row.get("fingerprint") == outcome.fingerprint
            ),
            None,
        )
        _emit_finding_stage(
            ctx,
            [
                AgentFindingLike(
                    fingerprint=outcome.fingerprint,
                    severity=str((stored_row or {}).get("severity", "") or ""),
                    body=str((stored_row or {}).get("body", "") or ""),
                )
            ],
            stage="withdrawn" if outcome.recorded_withdrawn else "verified",
        )
        if outcome.recorded_withdrawn:
            ctx.tool_state.was_updated = True
            ctx.tool_state.withdrawn_fingerprints.add(outcome.fingerprint)
            from mergecraft.findings.ledger import record_withdrawn_in_ledger

            record_withdrawn_in_ledger(ctx.tool_state)
        if outcome.verdict == "confirm" and outcome.publishable:
            _validate_publication_finding(
                ctx,
                outcome.fingerprint,
                causality=verdict.reason,
            )
            _persist_confirmed_fingerprint(ctx, outcome.fingerprint)
        elif outcome.verdict == "downgrade" and outcome.publishable:
            new_severity = verdict.downgrade_severity
            # Symmetric with the confirm branch: the row has to exist, and a
            # downgrade that lands on a still-blocking severity needs the same
            # structured causality a confirm does.
            _validate_publication_finding(
                ctx,
                outcome.fingerprint,
                causality=verdict.reason,
                severity=new_severity,
            )
            if new_severity in BLOCKING_SEVERITIES:
                _persist_confirmed_fingerprint(
                    ctx,
                    outcome.fingerprint,
                    severity=new_severity,
                )
            else:
                _apply_non_blocking_downgrade(ctx, outcome.fingerprint, severity=new_severity)
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
                    "enum": list(FINDING_SEVERITIES),
                    "description": (
                        "The severity a downgrade rewrites the finding to. Mandatory on a "
                        "downgrade verdict — one without it is rejected, not defaulted. "
                        "Ignored on confirm and drop."
                    ),
                },
            },
            "required": ["fingerprint", "verdict", "reason"],
            "additionalProperties": False,
        },
        execute=execute(_run, "record_finding_verdict"),
    )


__all__ = ["record_finding_verdict_tool", "verify_agent_findings_tool"]
