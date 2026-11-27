"""Render deterministic review records and edit their comment markers.

Module: mergecraft.findings.record_render
Depends: mergecraft.classify.risk

Exports:
    Functions:
        merge_deterministic_record_into_comment — Replace or insert the comment's run record.
        reconcile_outcome — Demote an approval-shaped label when the record cannot approve.
        record_is_not_an_approval — Determine approval posture for all record surfaces.
        render_deterministic_review_block — Render the Markdown run record.
        strip_deterministic_record_markers — Remove record markers from agent prose.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from mergecraft.classify.risk import format_risk_line

if TYPE_CHECKING:
    from collections.abc import Sequence


DETERMINISTIC_RECORD_MARKER: str = "<!-- mergecraft-deterministic-record:v1 -->"
REVIEW_BODY_MARKER: str = "<!-- mergecraft-review-body:v1 -->"

PROGRESS_HEADING = "## mergeCraft progress"

# The run record names at most this many reviewed files and change findings;
# the review packet keeps the full lists.
REVIEWED_FILES_SHOWN = 100
CHANGE_FINDINGS_SHOWN = 100
# Agent prose: the block must end at a real terminator. Falling back to ``\Z``
# here meant a marker the agent merely quoted — plausible in a repo that reviews
# its own reviewer — swallowed every finding after it. A bare marker with no
# terminator is removed on its own by the ``replace`` in the stripper below.
_DETERMINISTIC_RECORD_BLOCK_RE = re.compile(
    rf"{re.escape(DETERMINISTIC_RECORD_MARKER)}[\s\S]*?"
    rf"(?=\n{re.escape(REVIEW_BODY_MARKER)}|\n<!-- mergecraft-ledger:|\n\*via mergecraft\*)",
)
# Our own progress comment, where the record legitimately ends the body.
_DETERMINISTIC_RECORD_BLOCK_EOF_RE = re.compile(
    rf"{re.escape(DETERMINISTIC_RECORD_MARKER)}[\s\S]*?"
    r"(?=\n<!-- mergecraft-ledger:|\n\*via mergecraft\*|\Z)",
)
_RECORD_SLOT = "\x00mergecraft-deterministic-record\x00"


def strip_deterministic_record_markers(body: str) -> str:
    """Remove forged or stale deterministic-record markers from agent prose.

    The passes repeat until nothing changes, so a marker rebuilt by removing
    another one is removed too.
    """
    current = body
    while True:
        stripped = (
            _DETERMINISTIC_RECORD_BLOCK_RE.sub("", current)
            .replace(DETERMINISTIC_RECORD_MARKER, "")
            .replace(REVIEW_BODY_MARKER, "")
        )
        if stripped == current:
            return stripped.strip()
        current = stripped


def merge_deterministic_record_into_comment(body: str, *, record_block: str) -> str:
    """Insert or replace the deterministic record block in a progress comment.

    When the comment already carries a record, the new one replaces it in
    place so any surrounding prose keeps its position. The replacement is
    staged through a sentinel because the rendered block itself opens with
    the record marker; substituting it directly would leave the freshly
    inserted block matching the same pattern as the stale ones being cleared.
    """
    block = record_block.strip()
    if DETERMINISTIC_RECORD_MARKER in body:
        staged = _DETERMINISTIC_RECORD_BLOCK_EOF_RE.sub(_RECORD_SLOT, body, count=1)
        staged = _DETERMINISTIC_RECORD_BLOCK_EOF_RE.sub("", staged)
        staged = staged.replace(DETERMINISTIC_RECORD_MARKER, "")
        if PROGRESS_HEADING not in staged:
            staged = f"{PROGRESS_HEADING}\n\n{staged.lstrip()}"
        return f"{staged.replace(_RECORD_SLOT, block).strip()}\n"
    cleaned = _DETERMINISTIC_RECORD_BLOCK_EOF_RE.sub("", body)
    cleaned = cleaned.replace(DETERMINISTIC_RECORD_MARKER, "").strip()
    if not cleaned:
        return f"{PROGRESS_HEADING}\n\n{block}\n"
    if PROGRESS_HEADING not in cleaned:
        cleaned = f"{PROGRESS_HEADING}\n\n{cleaned}"
    parts = cleaned.split("\n", 1)
    if parts[0].strip() == PROGRESS_HEADING:
        tail = parts[1].strip() if len(parts) > 1 else ""
        if tail:
            return f"{PROGRESS_HEADING}\n\n{block}\n\n{tail}\n"
        return f"{PROGRESS_HEADING}\n\n{block}\n"
    return f"{block}\n\n{cleaned}\n"


_INCONCLUSIVE_OUTCOME = "inconclusive"
# The two approval-shaped positive values G0 item 4 forbids when no credentialed
# reviewer ran. Only these are demoted; every other outcome / diagnostic is left
# intact so the reconciliation cannot mask a real failure (F11 / #775).
_APPROVAL_SHAPED_OUTCOME = "passed"
# The coarse step-summary table renders `success` where the record renders
# `passed`; both are the approval-shaped positive the posture must demote.
APPROVAL_SHAPED_OUTCOME_LABELS: tuple[str, ...] = (_APPROVAL_SHAPED_OUTCOME, "success")
APPROVAL_SHAPED_DIAGNOSTIC = "approved"
# #775 — posture lines. G0 item 4 fixes the mapping: `inconclusive` is mergeCraft's
# internal outcome (GitHub's check conclusion stays `neutral`, which it already is).
# When no credentialed reviewer ran, the record may not read as an approval.
# The note states no outcome: the reconciled `Outcome:` line is the only outcome
# claim in the record (LG-D8), so `inconclusive` is not asserted here.
_NO_CREDENTIALED_REVIEWER_NOTE = (
    "no credentialed reviewer ran; the analyzers that ran and were withheld are "
    "listed above, and this record is not an approval"
)
_TERMINAL_REQUEST_CHANGES_NOTE = (
    "the reviewer's terminal verdict was `request_changes`; this record is not an approval"
)


def _credential_gap_with_verdict_note(model: str) -> str:
    """Name the skipped roster slot(s) and the model behind a recorded verdict.

    Rendered when a roster reviewer slot was skipped for missing credentials
    **and** a typed terminal verdict was recorded: the record may not claim no
    reviewer ran, so it names the producer of the verdict instead (LG-D7). The
    note states no outcome — the reconciled ``Outcome:`` line is the only outcome
    claim (LG-D8) — and keeps the not-an-approval posture.
    """
    if model:
        producer = f"the recorded terminal verdict was produced by `{model}`"
    else:
        producer = "the recorded terminal verdict was produced by a model not recorded here"
    return (
        "the roster reviewer slot(s) above were skipped for missing credentials and "
        f"{producer}; this record is not an approval"
    )


def _record_value(value: Any) -> str:
    """Render a ``StrEnum`` / plain value as its wire string (empty when unset)."""
    if value is None:
        return ""
    return str(getattr(value, "value", value))


def _credential_gap_present(credential_degradations: Sequence[str] | None) -> bool:
    """Return whether any roster reviewer slot was skipped for missing credentials."""
    return any(str(line).strip() for line in (credential_degradations or ()))


def _terminal_request_changes(packet: Any, decision: Any) -> bool:
    """Return whether the run's recorded terminal verdict was ``request_changes``.

    ``decide_approval`` (agents/gates.py) wraps the agent's terminal verdict in a
    ``neutral`` structural conclusion and names it in the decision reason; the
    typed ``packet.agent_terminal_verdict`` is the authoritative copy, and the
    reason is the fallback for a packet assembled without it (F12 / #775).
    """
    terminal = getattr(packet, "agent_terminal_verdict", None)
    if _record_value(terminal).strip().lower() == "request_changes":
        return True
    reason = str(getattr(decision, "reason", "") or "").lower()
    return "request_changes" in reason


def _typed_terminal_verdict(packet: Any) -> str:
    """Return the typed terminal verdict recorded on the packet (empty when unset).

    ``_terminal_request_changes`` also honours the decision reason as a fallback,
    but the reason is a derived summary. The record may only say "no credentialed
    reviewer ran" when **no** typed terminal verdict was recorded (LG-D7), so the
    renderer keys that distinction on the authoritative typed field, not the
    reason.
    """
    return _record_value(getattr(packet, "agent_terminal_verdict", None)).strip()


def record_is_not_an_approval(
    *, packet: Any, credential_degradations: Sequence[str] | None = None
) -> bool:
    """Return whether the record must demote its approval-shaped positive claims.

    The two signals are a skipped credentialed reviewer slot and a
    ``request_changes`` terminal verdict. Both surfaces — the embedded
    deterministic record and the coarse step-summary header table — must agree,
    so this single predicate is the authority for both (#775 / G-D9).
    """
    decision = getattr(packet, "decision", None)
    return _credential_gap_present(credential_degradations) or _terminal_request_changes(
        packet, decision
    )


def reconcile_outcome(*, value: Any, not_an_approval: bool, positive: str | Sequence[str]) -> str:
    """Demote an approval-shaped positive value to ``inconclusive``.

    ``positive`` is the surface's approval-shaped label(s): the deterministic
    record renders ``passed``, while the coarse step-summary table renders
    ``success``. Only those positives are demoted; a genuine negative outcome or
    diagnostic is left intact so the reconciliation never hides a real failure
    (F11 / #775).
    """
    rendered = _record_value(value)
    positives = (positive,) if isinstance(positive, str) else tuple(positive)
    if not_an_approval and rendered in positives:
        return _INCONCLUSIVE_OUTCOME
    return rendered


def _blast_radius_record_line(blast_radius: Any) -> str | None:
    """One run-record line naming the blast-radius lane and its reason codes (#1056).

    Total: a packet without a blast radius renders no line, a packet written
    before ``reasons`` existed renders the lane alone, and gates that were not
    measured are named so an unknown never reads as a pass.
    """
    if blast_radius is None:
        return None
    lane = str(getattr(blast_radius, "lane", "") or "").strip()
    if not lane:
        return None
    auto_merge_lane = str(getattr(blast_radius, "auto_merge_lane", "") or "").strip()
    line = f"- **Blast radius:** `{lane}`"
    if auto_merge_lane:
        line += f" ({auto_merge_lane})"
    codes = [
        code
        for reason in list(getattr(blast_radius, "reasons", None) or [])
        if (code := str(getattr(reason, "code", "") or "").strip())
    ]
    if codes:
        line += " — " + ", ".join(f"`{code}`" for code in codes)
    unmeasured = [
        str(getattr(gate, "gate", ""))
        for gate in list(getattr(blast_radius, "checklist", None) or [])
        if getattr(gate, "passed", True) is None
    ]
    if unmeasured:
        line += " · not measured: " + ", ".join(f"`{gate}`" for gate in unmeasured)
    return line


def _format_phase_elapsed(seconds: float) -> str:
    """Render one phase's elapsed seconds for the **Review cost** row (#1075).

    ``{:.0f}s`` rounds real sub-second work (analyzers at 0.124s) down to
    ``0s``, which reads as "the phase did not run". Sub-second values keep one
    decimal instead; under 50 ms that decimal would still render ``0.0s``, so
    those are named ``<0.1s`` — small, but not zero.

    Examples:
        >>> _format_phase_elapsed(0.0)
        '0s'
        >>> _format_phase_elapsed(0.124)
        '0.1s'
        >>> _format_phase_elapsed(0.02)
        '<0.1s'
        >>> _format_phase_elapsed(90.0)
        '90s'
    """
    if seconds <= 0:
        return "0s"
    if seconds < 0.05:
        return "<0.1s"
    if seconds < 1:
        return f"{seconds:.1f}s"
    return f"{seconds:.0f}s"


def render_deterministic_review_block(
    *,
    packet: Any,
    rejection_reason: str | None = None,
    run_url: str | None = None,
    run_outcome: Any | None = None,
    verdict_diagnostic: Any | None = None,
    analyzer_summary: str | None = None,
    agent_summary: str | None = None,
    trust_tier: str | None = None,
    attempt_count: int | None = None,
    token_summary: str | None = None,
    cost_summary: str | None = None,
    llm_review_timing: Any | None = None,
    publication_entrypoint: str | None = None,
    inline_comments_demoted: bool = False,
    comment_fallback_applied: bool = False,
    review_body_truncated: bool = False,
    credential_degradations: Sequence[str] | None = None,
    agent_sandbox_decision: Any | None = None,
    action_pin_sha: str | None = None,
    image_source_sha: str | None = None,
    review_skills: Sequence[str] | None = None,
    review_mcp_servers: Sequence[str] | None = None,
) -> str:
    """Render the authoritative deterministic review record (D6/D7).

    Pure leaf: no I/O. This is the formal review's server-owned record.
    """
    from mergecraft.analyzers.finding import Finding

    decision = getattr(packet, "decision", None)
    agent_meta = getattr(packet, "agent", None)
    self_assessment = getattr(packet, "self_assessment", None)
    findings_raw = list(getattr(packet, "findings", []) or [])
    findings = [
        row if isinstance(row, Finding) else Finding.model_validate(row) for row in findings_raw
    ]
    change_findings = [finding for finding in findings if finding.scope != "run"]
    run_health = getattr(packet, "run_health", None)
    if run_health is not None:
        run_findings = [
            row if isinstance(row, Finding) else Finding.model_validate(row)
            for row in list(getattr(run_health, "findings", []) or [])
        ]
    else:
        run_findings = [finding for finding in findings if finding.scope == "run"]
    deterministic_checks = list(getattr(packet, "deterministic_checks", []) or [])

    # #775 / G-D9 — reconcile the record so a positive claim (`Outcome: passed`,
    # `Verdict diagnostic: approved`) is never rendered beside a signal that the
    # review could not produce an approval. The two negative signals are a
    # skipped credentialed reviewer slot and a `request_changes` terminal
    # verdict; either maps the internal outcome to `inconclusive` (GitHub
    # `neutral`, per G0 item 4). Only the approval-shaped positive values are
    # demoted — a genuine `failed` / `infra_error` / `timed_out` outcome (or a
    # negative diagnostic such as `provider_failure`) is left intact, so the
    # reconciliation never hides a real failure.
    credential_gap = _credential_gap_present(credential_degradations)
    terminal_request_changes = _terminal_request_changes(packet, decision)
    typed_terminal_verdict = _typed_terminal_verdict(packet)
    not_an_approval = record_is_not_an_approval(
        packet=packet, credential_degradations=credential_degradations
    )
    model = ""
    if agent_meta is not None:
        executed = str(getattr(agent_meta, "executed_model", "") or "").strip()
        model = executed or str(getattr(agent_meta, "model", "") or "").strip()

    reviewed_sha = ""
    if self_assessment is not None and getattr(self_assessment, "sha", None):
        reviewed_sha = str(self_assessment.sha)

    header_lines = [
        DETERMINISTIC_RECORD_MARKER,
        "### mergeCraft run record",
        "",
    ]
    # The completed-review recognizer reads the first three rows by position.
    if run_outcome is not None:
        outcome = reconcile_outcome(
            value=run_outcome,
            not_an_approval=not_an_approval,
            positive=_APPROVAL_SHAPED_OUTCOME,
        )
        header_lines.append(f"- **Outcome:** `{outcome}`")
    if verdict_diagnostic is not None:
        diagnostic = reconcile_outcome(
            value=verdict_diagnostic,
            not_an_approval=not_an_approval,
            positive=APPROVAL_SHAPED_DIAGNOSTIC,
        )
        header_lines.append(f"- **Verdict diagnostic:** `{diagnostic}`")
    if decision is not None:
        header_lines.append(f"- **Decision:** `{decision.verdict}` — {decision.reason}")
    risk_line = format_risk_line(getattr(packet, "blast_radius", None))
    if risk_line is not None:
        header_lines.append(f"- {risk_line}")
    change_id = str(getattr(packet, "change_id", "") or "").strip()
    if change_id:
        header_lines.append(f"- **Change:** `{change_id}`")
    changed_files = list(getattr(packet, "files_changed", []) or [])
    if changed_files:
        shown_files = ", ".join(f"`{path}`" for path in changed_files[:REVIEWED_FILES_SHOWN])
        hidden_files = len(changed_files) - REVIEWED_FILES_SHOWN
        if hidden_files > 0:
            shown_files += f", and {hidden_files} more (the review packet lists every file)"
        header_lines.append(f"- **Reviewed files:** {shown_files}")
    triage = getattr(packet, "triage", None)
    if triage is not None and triage.tier == "skip":
        header_lines.append(f"- **Tier:** skip ({triage.recognizer}) — no LLM review ran")
        reapproval = getattr(triage, "reapproval", None)
        if reapproval is not None:
            header_lines.append(
                f"- **Re-approved from:** `{reapproval.prior_head_sha}` "
                f"({reapproval.prior_url}); qualifying path: "
                + ", ".join(f"`{path}`" for path in reapproval.qualifying_paths)
            )
    elif triage is not None and triage.tier == "lite":
        used = getattr(triage, "tokens_used", None)
        usage = "" if used is None else f"; {used} tokens used"
        if used is not None and getattr(triage, "usage_estimated", False):
            usage += " (estimated)"
        header_lines.append(
            f"- **Tier:** lite ({triage.recognizer}) — single-call review, "
            f"cap {triage.token_cap} tokens{usage}; approval is left to a human"
        )
    blast_radius_line = _blast_radius_record_line(getattr(packet, "blast_radius", None))
    if blast_radius_line is not None:
        header_lines.append(blast_radius_line)
    from mergecraft.merge_attention.render import merge_attention_record_lines

    header_lines.extend(merge_attention_record_lines(getattr(packet, "merge_attention", None)))
    coverage = getattr(packet, "coverage", None)
    if coverage is not None:
        from mergecraft.evidence.coverage import coverage_summary_line

        # The record is rendered without the run's settings, so it states the gap but
        # not what the policy did about it; the checks carry that.
        header_lines.append(
            "- **Coverage:** "
            + coverage_summary_line(coverage, on_incomplete=None).removeprefix("Coverage: ")
        )
    if agent_meta is not None:
        provider = str(getattr(agent_meta, "provider", "") or "").strip()
        if provider:
            header_lines.append(f"- **Provider:** `{provider}`")
        requested = str(getattr(agent_meta, "requested_model", "") or "").strip()
        if requested and requested != model:
            header_lines.append(f"- **Requested model:** `{requested}`")
        if getattr(agent_meta, "fallback_occurred", False):
            header_lines.append(
                f"- **Model fallback:** attempt {getattr(agent_meta, 'fallback_index', 0)}"
            )
    if model:
        header_lines.append(f"- **Model:** `{model}`")
    if attempt_count is not None:
        header_lines.append(f"- **Attempts:** {attempt_count}")
    if token_summary:
        header_lines.append(f"- **Tokens:** {token_summary}")
    if cost_summary:
        header_lines.append(f"- **Recorded reviewer model cost:** {cost_summary}")
    metrics = getattr(packet, "run_metrics", None)
    if metrics is not None:
        phase_elapsed = getattr(metrics, "phase_elapsed_s", {}) or {}
        phase_order = ("setup", "analyzers", "agent", "judge", "publish")
        phase_bits = [
            f"{name} {_format_phase_elapsed(float(phase_elapsed[name]))}"
            for name in phase_order
            if name in phase_elapsed
        ]
        phases_text = f" · phases: {', '.join(phase_bits)}" if phase_bits else ""
        header_lines.append(
            "- **Review cost:** "
            f"{getattr(metrics, 'tool_calls', 0)} tool calls · "
            f"{getattr(metrics, 'distinct_files_read', 0)} files read · "
            f"{getattr(metrics, 'diff_lines', 0)} diff lines"
            f"{phases_text}"
        )
        # A packet built before 1.22.0 carries none of the pre-flight fields.
        if hasattr(metrics, "coverage_preflight_refusals"):
            preflight_bits: list[str] = []
            if metrics.coverage_preflight_refusals:
                unread = metrics.unread_added_lines_at_first_verdict
                at_first = f", {unread} added lines unread at the first" if unread else ""
                preflight_bits.append(
                    f"coverage refused {metrics.coverage_preflight_refusals} submission(s){at_first}"
                )
            if metrics.depth_preflight_refused:
                preflight_bits.append("depth refused one submission")
            if preflight_bits:
                header_lines.append(f"- **Verdict pre-flights:** {'; '.join(preflight_bits)}")
        agent_diag = getattr(metrics, "agent_diagnostic", None)
        if isinstance(agent_diag, str) and agent_diag.strip():
            header_lines.append(f"- **Agent stall:** {agent_diag.strip().splitlines()[0]}")
    if llm_review_timing is not None:
        from mergecraft.utils.llm_review_timing import (
            LlmReviewTimingSnapshot,
            format_llm_review_timing_record,
        )

        snapshot = (
            llm_review_timing if isinstance(llm_review_timing, LlmReviewTimingSnapshot) else None
        )
        if snapshot is not None:
            header_lines.append(format_llm_review_timing_record(snapshot))
    if run_url:
        header_lines.append(f"- **Run:** {run_url}")
    if reviewed_sha:
        header_lines.append(f"- **Reviewed SHA:** `{reviewed_sha}`")
    pin = (action_pin_sha or "").strip()
    source = (image_source_sha or "").strip()
    if pin:
        header_lines.append(f"- **Action pin:** `{pin}`")
    if source:
        header_lines.append(f"- **Image source:** `{source}`")
    if pin and source and pin == source:
        header_lines.append(
            "- **Pin lag:** action pin equals baked image source — pinning S "
            "still deploys the digest already stored at S (#641)"
        )
    if review_skills:
        header_lines.append(
            "- **Review skills (injected):** " + ", ".join(f"`{item}`" for item in review_skills)
        )
    if review_mcp_servers:
        header_lines.append(
            "- **Review MCP:** " + ", ".join(f"`{item}`" for item in review_mcp_servers)
        )
    if publication_entrypoint:
        header_lines.append(f"- **Publication path:** `{publication_entrypoint}`")
    if inline_comments_demoted:
        header_lines.append("- **Inline recovery:** demoted inline comments into the review body")
    if comment_fallback_applied:
        header_lines.append(
            "- **Publication recovery:** normal 422 recovery was exhausted; the review "
            "landed as a last-resort bare COMMENT with no inline comments"
        )
    if review_body_truncated:
        header_lines.append(
            "- **Body truncated:** review body exceeded GitHub's 65536-character cap"
        )

    pre_merge_lines = ["", "### Pre-merge checks", ""]
    if credential_gap and typed_terminal_verdict:
        # LG-D7 — a reviewer ran and recorded a typed verdict; the record names
        # the skipped roster slot(s) (the `Credential gap` lines below name them)
        # and the model that produced the verdict, and states no outcome (LG-D8).
        # Keyed on the typed verdict, not the decision-reason fallback: only a
        # recorded typed verdict proves a reviewer ran.
        pre_merge_lines.append(
            f"- **Review integrity:** {_credential_gap_with_verdict_note(model)}"
        )
    elif credential_gap:
        pre_merge_lines.append(f"- **Review integrity:** {_NO_CREDENTIALED_REVIEWER_NOTE}")
    elif terminal_request_changes:
        pre_merge_lines.append(f"- **Review integrity:** {_TERMINAL_REQUEST_CHANGES_NOTE}")
    if analyzer_summary:
        pre_merge_lines.append(f"- **Analyzers:** {analyzer_summary}")
    elif agent_meta is not None and getattr(agent_meta, "dispatched_lens_ids", None):
        lens_ids = ", ".join(agent_meta.dispatched_lens_ids)
        pre_merge_lines.append(f"- **Analyzers:** dispatched lenses: {lens_ids}")
    else:
        pre_merge_lines.append("- **Analyzers:** not recorded on packet")

    if deterministic_checks:
        check_bits = [
            f"{check.name} ({check.status})"
            for check in deterministic_checks
            if getattr(check, "name", None)
        ]
        pre_merge_lines.append(
            f"- **Static checks:** {', '.join(check_bits) if check_bits else 'none recorded'}"
        )
    else:
        pre_merge_lines.append("- **Static checks:** none recorded")

    pre_merge_lines.append("- **CI intelligence:** see packet findings")
    pre_merge_lines.append(f"- **Trust tier:** `{trust_tier or 'unknown'}`")
    if agent_sandbox_decision is not None:
        # #619 Task 7 — the resolved sandbox decision (lane B D1/D2,
        # ``config/trust_policy.py::resolve_agent_sandbox_decision``) already
        # reaches the manifest via ``agent_sandbox_manifest_fields`` but never
        # the sticky progress comment a human actually reads. Duck-typed
        # (``getattr``) like the rest of this function's inputs — a plain
        # ``AgentSandboxDecision`` or an equivalent shim both render.
        configured_tier = getattr(agent_sandbox_decision, "configured_tier", "") or "unknown"
        head_status = getattr(agent_sandbox_decision, "head_status", "") or "unknown"
        override = "granted" if getattr(agent_sandbox_decision, "honour", False) else "refused"
        pre_merge_lines.append(
            f"- **Agent sandbox:** `{configured_tier}` tier, head `{head_status}` — "
            f"override {override}"
        )
    if credential_degradations:
        for line in credential_degradations:
            stripped = line.strip()
            if stripped:
                pre_merge_lines.append(f"- **Credential gap:** {stripped}")

    finding_lines = ["", "<details>", "<summary>Change-scoped findings</summary>", ""]
    if change_findings:
        for finding in change_findings[:CHANGE_FINDINGS_SHOWN]:
            line = f":{finding.start_line}" if finding.path and finding.start_line else ""
            location = f"`{finding.path}{line}` — " if finding.path else ""
            finding_lines.append(f"- **{finding.severity}** · {location}{finding.message}")
        hidden_findings = len(change_findings) - CHANGE_FINDINGS_SHOWN
        if hidden_findings > 0:
            finding_lines.append(
                f"- _and {hidden_findings} more change-scoped findings in the review packet_"
            )
    else:
        finding_lines.append("_No change-scoped findings recorded._")
    finding_lines.extend(["", "</details>"])

    run_health_lines: list[str] = []
    if run_findings:
        run_health_lines = [
            "",
            "<details>",
            "<summary>Run health</summary>",
            "",
        ]
        for finding in run_findings:
            run_health_lines.append(f"- **{finding.severity}** · {finding.message}")
        run_health_lines.append("")
        run_health_lines.append("</details>")

    verdict_lines: list[str] = []
    if decision is not None:
        summary = (agent_summary or "").strip()
        if summary:
            verdict_lines = [
                "",
                "### Agent summary",
                "",
                f"> {summary.replace(chr(10), chr(10) + '> ')}",
            ]
    if rejection_reason:
        # The agent's terminal verdict was refused (scope, schema, semantic or
        # policy). This used to be an ``elif`` on ``decision is None``, which the
        # packet pipeline never produces — ``decide_approval`` always returns a
        # ``PacketDecision`` — so a refused run rendered identically to a clean
        # one. The structural decision and the refusal are separate facts.
        label = (
            "No agent verdict published"
            if rejection_reason == "terminal_publication_failed"
            else "No agent verdict recorded"
        )
        verdict_lines += [
            "",
            f"**{label} — reason:** `{rejection_reason}`",
        ]

    return (
        "\n".join(
            header_lines + pre_merge_lines + finding_lines + run_health_lines + verdict_lines
        ).rstrip()
        + "\n"
    )


__all__ = [
    "APPROVAL_SHAPED_DIAGNOSTIC",
    "APPROVAL_SHAPED_OUTCOME_LABELS",
    "CHANGE_FINDINGS_SHOWN",
    "DETERMINISTIC_RECORD_MARKER",
    "PROGRESS_HEADING",
    "REVIEWED_FILES_SHOWN",
    "REVIEW_BODY_MARKER",
    "merge_deterministic_record_into_comment",
    "reconcile_outcome",
    "record_is_not_an_approval",
    "render_deterministic_review_block",
    "strip_deterministic_record_markers",
]
