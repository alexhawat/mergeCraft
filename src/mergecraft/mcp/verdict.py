"""Terminal review verdict MCP tool (VP1) and semantic validation (VP2).

Records a typed terminal submission on ``ToolState`` without publishing to
GitHub. VP2 adds ``validate_submission`` and wires it into the tool so
schema-invalid and semantically-invalid payloads fail closed without setting
``terminal_submission``.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator

from mergecraft.findings.agent_adapter import (
    coerce_agent_finding,
    normalize_agent_findings_via_pipeline,
)
from mergecraft.mcp.shared import ToolClass, execute, tool
from mergecraft.mcp.tool_state import TerminalSubmission, ToolState, primary_repo_state
from mergecraft.modes._api_only_scope import API_ONLY_SCOPE
from mergecraft.review_taxonomy import FINDING_SEVERITIES
from mergecraft.tracing.redaction import redact_attrs

if TYPE_CHECKING:
    from collections.abc import Iterable

    from mergecraft.analyzers.finding import Finding
    from mergecraft.mcp.context import ToolContext

_ALLOWED_VERDICTS = frozenset({"approve", "request_changes"})
_ALLOWED_TOP_LEVEL_KEYS = frozenset({"verdict", "summary", "findings"})
_REQUIRED_TOP_LEVEL_KEYS = frozenset({"verdict", "summary"})
_REVIEW_MODES = frozenset({"Review", "IncrementalReview"})
_SCOPE_PROVENANCE = frozenset({"api", "checkout", "local-diff", "commit-info"})
_UNIFIED_DIFF_MARKERS = ("diff --git", "--- a/", "+++ b/")

REJECTION_INVALID_VERDICT = "invalid_verdict"
REJECTION_UNKNOWN_FIELDS = "unknown_fields"
REJECTION_MISSING_REQUIRED_FIELDS = "missing_required_fields"
REJECTION_REQUEST_CHANGES_NO_FINDINGS = "request_changes_without_findings"
REJECTION_APPROVE_CONFIRMED_BLOCKER = "approve_with_confirmed_blocker"
REJECTION_APPROVE_FAILED_GATE = "approve_with_failed_required_gate"
REJECTION_CONFLICTING_SUBMISSION = "conflicting_submission"
REJECTION_SCOPE_UNAVAILABLE = "scope_unavailable"

_TERMINAL_TOOL_NAMES = frozenset({"submit_review_verdict", "create_pull_request_review"})


class ReviewPhase(StrEnum):
    """Closed review-phase vocabulary (D10 / VP4)."""

    INIT = "INIT"
    ESTABLISH_SCOPE = "ESTABLISH_SCOPE"
    COLLECT_EVIDENCE = "COLLECT_EVIDENCE"
    REVIEW = "REVIEW"
    NORMALIZE = "NORMALIZE"
    VERIFY_BLOCKERS = "VERIFY_BLOCKERS"
    SUBMIT = "SUBMIT"
    POLICY = "POLICY"
    PUBLISH = "PUBLISH"
    COMPLETE = "COMPLETE"


class VerdictDiagnostic(StrEnum):
    """Closed vocabulary for terminal-verdict shadow diagnostics (VP3)."""

    provider_failure = "provider_failure"
    provider_success_without_submission = "provider_success_without_submission"
    schema_invalid = "schema_invalid"
    semantic_invalid = "semantic_invalid"
    policy_rejection = "policy_rejection"
    agent_approved_but_blocked = "agent_approved_but_blocked"
    approved = "approved"
    fallback_triggered = "fallback_triggered"


def span_attrs_for_verdict_diagnostic(
    diagnostic: VerdictDiagnostic,
    *,
    summary: str,
) -> dict[str, Any]:
    """Build redacted span attrs carrying a closed ``VerdictDiagnostic`` code."""
    return redact_attrs(
        {
            "verdict.diagnostic": diagnostic.value,
            "summary": summary,
        }
    )


def stamp_review_phase_on_active_span(phase: ReviewPhase) -> None:
    """Stamp ``review.phase`` on the active span when one is open (D10).

    OB4 / O9 — the same transition seam also emits a ``mergecraft.phase``
    point span via the active span's tracer, so the trace shows the
    lifecycle as it advances and a run that dies early visibly stops before
    the terminal phases. Best-effort: a span-emission failure must never
    break the transition itself (convention 3).
    """
    from mergecraft.tracing import Span
    from mergecraft.tracing.tracer import _ACTIVE_SPAN

    active = _ACTIVE_SPAN.get()
    if isinstance(active, Span):
        active.set_attribute("review.phase", phase.value)
        active.set_attribute("mergecraft.review.phase", phase.value)
        try:
            from mergecraft.tracing.signals import emit_phase

            emit_phase(active.tracer, phase=phase)
        except Exception:
            logger.debug("phase span emission skipped for {}", phase.value)


def _current_review_phase(tool_state: ToolState) -> ReviewPhase:
    raw = tool_state.review_phase
    if not raw:
        return ReviewPhase.INIT
    return ReviewPhase(raw)


def _looks_like_unified_diff(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return any(marker in stripped for marker in _UNIFIED_DIFF_MARKERS)


def record_terminal_rejection(tool_state: ToolState, rejection_reason: str) -> None:
    """Remember why the most recent terminal tool attempt was refused (W5)."""
    tool_state.last_terminal_rejection = rejection_reason


def terminal_tool_was_attempted(tool_state: ToolState) -> bool:
    """Return whether a terminal review tool was invoked this run."""
    for call in tool_state.tool_calls:
        tool_name = getattr(call, "tool", None)
        if tool_name in _TERMINAL_TOOL_NAMES:
            return True
    return False


def scope_blocks_terminal(tool_state: ToolState) -> bool:
    """Return whether review scope is missing for a terminal tool in Review modes."""
    mode = tool_state.selected_mode
    if mode not in _REVIEW_MODES:
        return False
    if tool_state.review_phase != ReviewPhase.INIT.value:
        return False
    primary = primary_repo_state(tool_state)
    if primary.diff_path:
        return False
    return not (mode == "IncrementalReview" and primary.incremental_changed_paths)


def _has_unsubmitted_review(tool_state: ToolState) -> bool:
    """Return whether a Review-mode run still lacks a terminal submission."""
    mode = tool_state.selected_mode
    if mode == "Review":
        return tool_state.terminal_submission is None
    if mode == "IncrementalReview":
        return tool_state.terminal_submission is None and not tool_state.final_summary_written
    return False


def record_scope_rejection_if_blocked(tool_state: ToolState) -> None:
    """Record a scope-guard refusal when post-run classification needs one (W5)."""
    if tool_state.last_terminal_rejection is not None:
        return
    if not scope_blocks_terminal(tool_state):
        return
    if terminal_tool_was_attempted(tool_state):
        record_terminal_rejection(tool_state, REJECTION_SCOPE_UNAVAILABLE)
        return
    if tool_state.selected_mode not in _REVIEW_MODES:
        return
    if not _has_unsubmitted_review(tool_state):
        return
    record_terminal_rejection(tool_state, REJECTION_SCOPE_UNAVAILABLE)


def _scope_refusal_detail(tool_state: ToolState) -> str:
    primary = primary_repo_state(tool_state)
    if primary.diff_path:
        return "diff_path is set but review_phase is still INIT"
    if primary.incremental_changed_paths:
        return "incremental_changed_paths is set but diff_path is missing"
    return "no materialized diff has been recorded yet (review_phase is INIT)"


def register_review_scope(
    tool_state: ToolState,
    *,
    diff_path: str,
    provenance: Literal["api", "checkout", "local-diff", "commit-info"],
    review_scope: str | None = None,
) -> None:
    """Record evidence-backed review scope and advance past ``INIT`` (D4)."""
    if provenance not in _SCOPE_PROVENANCE:
        msg = f"invalid scope provenance: {provenance!r}"
        raise ValueError(msg)
    primary_repo_state(tool_state).diff_path = diff_path
    tool_state.scope_provenance = provenance
    tool_state.review_scope = (
        review_scope
        if review_scope is not None
        else (API_ONLY_SCOPE if provenance == "api" else None)
    )
    tool_state.review_phase = ReviewPhase.ESTABLISH_SCOPE.value
    stamp_review_phase_on_active_span(ReviewPhase.ESTABLISH_SCOPE)


def establish_offline_review_scope(tool_state: ToolState, *, diff_path: str) -> None:
    """Advance an offline run past ``INIT`` once its diff scope is materialized.

    ``checkout_pr`` is how the Action path establishes review scope, but an
    offline run (``--base``/``--head``, ``--diff``, ``--cwd``) has no PR to
    check out — its scope comes from the materialized diff. Without this
    transition the run stays in ``INIT`` and every terminal tool is refused
    by :func:`ensure_review_scope_for_terminal`, so an offline review could
    never record a verdict (issue #470).
    """
    register_review_scope(tool_state, diff_path=diff_path, provenance="local-diff")


async def _resolve_pr_head_sha(ctx: ToolContext, *, pull_number: int) -> str:
    pr = await ctx.scm.get_pull(ctx.repo.owner, ctx.repo.name, pull_number)
    head = pr.get("head") or {}
    return str(head.get("sha") or "").strip().lower()


async def validate_review_scope_evidence(
    ctx: ToolContext,
    *,
    diff_path: str,
    head_sha: str,
) -> None:
    """Validate diff evidence and PR-head binding before scope is recorded (D4)."""
    path = Path(diff_path)
    if not path.is_file():
        msg = f"diff_path does not exist: {diff_path}"
        raise ValueError(msg)
    text = path.read_text(encoding="utf-8")
    if not _looks_like_unified_diff(text):
        msg = f"diff_path is empty or not a unified diff: {diff_path}"
        raise ValueError(msg)
    pull_number = ctx.tool_state.pr_number or primary_repo_state(ctx.tool_state).issue_number
    if pull_number is None:
        msg = "establish_review_scope requires a PR number on this run"
        raise ValueError(msg)
    api_head = await _resolve_pr_head_sha(ctx, pull_number=int(pull_number))
    if not api_head:
        msg = "could not resolve PR head sha from the API"
        raise ValueError(msg)
    if head_sha.strip().lower() != api_head:
        msg = f"head_sha {head_sha!r} does not match the PR head {api_head!r} from the API"
        raise ValueError(msg)


async def reject_diff_that_does_not_match_the_pr(
    ctx: ToolContext, *, diff_path: str, pull_number: int
) -> None:
    """Bind a caller-supplied diff to the PR GitHub actually reports (D4).

    The caller supplies ``diff_path`` and can read the real ``head_sha`` from the
    API, so shape plus a matching head SHA proved only that a file exists and
    looks like a diff. A reviewing agent holding a shell tool could write any
    file and satisfy the fail-closed scope gate without reading the change —
    which is the one thing that gate exists to prevent.

    The diff's paths must therefore cover every path GitHub reports for the PR,
    and introduce none it does not report. This binds scope to the real change
    set; it does not authenticate hunk contents, so a diff naming the right
    files with altered bodies is still out of reach of this check.
    """
    from mergecraft.mcp.checkout import changed_paths_in_diff, pull_request_path_expectations

    text = Path(diff_path).read_text(encoding="utf-8")
    required, allowed = await pull_request_path_expectations(ctx, pull_number=pull_number)
    if not required:
        msg = "could not resolve the PR's changed files from the API"
        raise ValueError(msg)
    diff_paths = set(changed_paths_in_diff(text))
    if not diff_paths:
        msg = "diff_path names no files; it cannot describe the PR head"
        raise ValueError(msg)
    missing = sorted(required - diff_paths)
    unexpected = sorted(diff_paths - allowed)
    if missing or unexpected:
        detail: list[str] = []
        if missing:
            detail.append(f"missing {len(missing)} file(s) the PR changes: {missing[:5]}")
        if unexpected:
            detail.append(f"names {len(unexpected)} file(s) the PR does not: {unexpected[:5]}")
        msg = f"diff_path does not match the pull request — {'; '.join(detail)}"
        raise ValueError(msg)


def ensure_review_scope_for_terminal(tool_state: ToolState, tool_name: str) -> None:
    """Raise when a Review-mode terminal tool runs before review scope exists (D10).

    Scope is evidence-backed (D4) and may be established by ``checkout_pr``,
    :func:`establish_review_scope`, :func:`establish_offline_review_scope`, or
    ``get_commit_info`` when its SHA equals the PR head.
    """
    mode = tool_state.selected_mode
    if mode not in _REVIEW_MODES or _current_review_phase(tool_state) != ReviewPhase.INIT:
        return
    if primary_repo_state(tool_state).diff_path:
        return
    if mode == "IncrementalReview":
        primary = primary_repo_state(tool_state)
        if primary.incremental_changed_paths:
            return
    detail = _scope_refusal_detail(tool_state)
    record_terminal_rejection(tool_state, REJECTION_SCOPE_UNAVAILABLE)
    routes = (
        "checkout_pr (fetch the PR branch or degrade to api-only with diffPath)",
        "establish_review_scope (diff_path + base_sha + head_sha matching the PR head)",
        "get_commit_info (when sha equals the PR head — writes commit-<sha>.diff)",
        "offline runs via --base/--head, --diff, or --cwd (establish_offline_review_scope)",
    )
    msg = (
        f"{tool_name} requires review scope before the terminal verdict can be "
        f"recorded. Establish scope via one of: {'; '.join(routes)}. "
        f"This run: {detail}."
    )
    raise ValueError(msg)


def record_validated_terminal_submission(
    ctx: ToolContext,
    submission: dict[str, Any],
    *,
    findings: list[Any] | None = None,
) -> TerminalSubmission:
    """Validate and record a terminal submission on ``ToolState`` (VP4 delegate path)."""
    payload_hash = _canonical_payload_hash(_submission_dict_for_hash(submission))
    existing = ctx.tool_state.terminal_submission

    if existing is not None:
        if existing.payload_hash == payload_hash:
            if ctx.tool_state.terminal_submission_conflict:
                return existing
            validation = validate_submission(
                submission,
                state=validation_state_from_tool_context(ctx),
            )
            if not validation.accepted:
                record_terminal_rejection(ctx.tool_state, validation.rejection_reason or "")
                msg = f"terminal submission rejected: {validation.rejection_reason}"
                raise ValueError(msg)
            return existing
        ctx.tool_state.terminal_submission_conflict = True
        msg = (
            "terminal submission conflict: a different verdict payload was already "
            "recorded for this run"
        )
        raise ValueError(msg)

    validation = validate_submission(
        submission,
        state=validation_state_from_tool_context(ctx),
    )
    if not validation.accepted:
        record_terminal_rejection(ctx.tool_state, validation.rejection_reason or "")
        msg = f"terminal submission rejected: {validation.rejection_reason}"
        raise ValueError(msg)

    verdict = submission["verdict"]
    summary = submission["summary"]
    resolved_findings = findings if findings is not None else list(submission.get("findings") or [])

    recorded = TerminalSubmission(
        id=uuid.uuid4().hex,
        verdict=verdict,
        summary=str(summary),
        findings=list(resolved_findings),
        payload_hash=payload_hash,
        submitted_at=datetime.now(UTC).isoformat(),
        attempt_id=ctx.tool_state.attempt_id,
    )
    ctx.tool_state.terminal_submission = recorded
    ctx.tool_state.terminal_submission_conflict = False
    return recorded


def verdict_satisfies_attempt(
    submission: TerminalSubmission,
    *,
    current_attempt_id: int,
) -> bool:
    """Return whether ``submission`` belongs to the active model-chain attempt (V7)."""
    return submission.attempt_id == current_attempt_id


def _canonical_payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _submission_dict_for_hash(submission: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-serializable submission dict for canonical hashing."""
    findings_raw = submission.get("findings") or []
    serializable_findings: list[Any] = []
    for item in findings_raw:
        if hasattr(item, "model_dump"):
            serializable_findings.append(item.model_dump())
        else:
            serializable_findings.append(item)
    return {
        "verdict": submission["verdict"],
        "summary": submission["summary"],
        "findings": serializable_findings,
    }


@dataclass(frozen=True, slots=True)
class SubmissionValidation:
    """Typed validator result (D5) — not a bare bool."""

    accepted: bool
    rejection_reason: str | None


def _finding_fingerprint(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("fingerprint") or "")
    return str(getattr(item, "fingerprint", "") or "")


def _coerce_confirmed_finding(item: Any) -> Finding | None:
    from mergecraft.analyzers.finding import Finding, FindingValidationError, make_finding

    if isinstance(item, Finding):
        return item
    if not isinstance(item, dict):
        return None
    try:
        return Finding.model_validate(item)
    except (FindingValidationError, ValueError, TypeError):  # fmt: skip
        pass
    severity = item.get("severity")
    if not severity:
        return None
    from typing import cast

    from mergecraft.analyzers.finding import IntroducedByPr

    introduced_raw = str(item.get("introduced_by_pr") or "unknown")
    introduced = cast(
        "IntroducedByPr",
        introduced_raw if introduced_raw in {"true", "false", "unknown"} else "unknown",
    )
    # The fallback constructor validates too — a present-but-invalid category,
    # severity or confidence, or a non-numeric line, must return ``None`` like
    # any other unreadable row rather than raising out through the approve gate.
    try:
        return make_finding(
            tool=str(item.get("tool") or "agent"),
            rule_id=str(item.get("rule_id") or "agent:confirmed"),
            category=str(item.get("category") or "Functional Correctness"),
            severity=str(severity),
            confidence=str(item.get("confidence") or "likely"),
            message=str(item.get("message") or item.get("body") or ""),
            path=str(item.get("path") or ""),
            start_line=int(item.get("start_line") or item.get("line") or 1),
            end_line=int(item.get("end_line") or item.get("line") or 1),
            source="agent",
            fingerprint=str(item.get("fingerprint") or "") or None,
            introduced_by_pr=introduced,
        )
    except (FindingValidationError, ValueError, TypeError):  # fmt: skip
        return None


@dataclass(frozen=True, slots=True)
class ValidationState:
    """The graded consultation inputs ``validate_submission`` reads (D5, D12).

    Every analyzer and agent row this run knows about is graded exactly once,
    by ``build_validation_state``, into one of three populations. Producer and
    consumer therefore agree by construction instead of by ``getattr`` — the
    approve gate cannot silently read ``None`` for a renamed field.

    Attributes:
        terminal_submission: The verdict already recorded on this run, if any.
        terminal_submission_conflict: True once a conflicting payload arrived.
        confirmed_findings: Findings the agent itself asserted — verifier
            confirms and agent-authored rows. Withdrawn rows are already gone.
        unverified_findings: Analyzer rows nobody verified or withdrew.
        ungradable_fingerprints: Rows no coercion could read. They block, since
            approving over a finding nobody could grade is the fail-open branch.
        static_checks: The last ``run_static_checks`` status rows.
        withdrawn_fingerprints: What a verifier ``drop`` retired this run.
    """

    terminal_submission: TerminalSubmission | None = None
    terminal_submission_conflict: bool = False
    confirmed_findings: tuple[Finding, ...] = ()
    unverified_findings: tuple[Finding, ...] = ()
    ungradable_fingerprints: tuple[str, ...] = ()
    static_checks: tuple[dict[str, str], ...] = ()
    withdrawn_fingerprints: frozenset[str] = frozenset()


def build_validation_state(
    *,
    terminal_submission: TerminalSubmission | None = None,
    terminal_submission_conflict: bool = False,
    asserted_findings: Iterable[Any] = (),
    analyzer_findings: Iterable[Any] = (),
    verified_fingerprints: Iterable[str] = (),
    static_checks: Iterable[Any] = (),
    withdrawn_fingerprints: Iterable[str] = (),
) -> ValidationState:
    """Grade every known finding once and return the partitioned state.

    One pass, not two inverted ones: a row is withdrawn (dropped), asserted or
    verified (confirmed), readable but unverified, or ungradable. ``asserted``
    rows are graded first so a fingerprint the agent confirmed is never also
    counted as unverified.

    Args:
        terminal_submission (TerminalSubmission | None): Recorded verdict.
        terminal_submission_conflict (bool): Whether a conflict was recorded.
        asserted_findings (Iterable[Any]): Rows the agent asserted itself.
        analyzer_findings (Iterable[Any]): Rows the analyzer run produced.
        verified_fingerprints (Iterable[str]): Fingerprints a verifier confirmed.
        static_checks (Iterable[Any]): ``run_static_checks`` status rows.
        withdrawn_fingerprints (Iterable[str]): Fingerprints a ``drop`` retired.

    Returns:
        ValidationState: The graded populations, ready for the gate.

    Examples:
        >>> state = build_validation_state()
        >>> state.confirmed_findings, state.unverified_findings
        ((), ())
    """
    withdrawn = frozenset(withdrawn_fingerprints)
    verified = frozenset(verified_fingerprints)

    confirmed: list[Finding] = []
    unverified: list[Finding] = []
    ungradable: list[str] = []
    seen: set[str] = set()

    def _grade(item: Any, *, asserted: bool) -> None:
        fingerprint = _finding_fingerprint(item)
        if fingerprint and (fingerprint in withdrawn or fingerprint in seen):
            return
        coerced = _coerce_confirmed_finding(item)
        if coerced is None:
            # An asserted row the agent wrote badly is its own problem; an
            # analyzer row nobody can read is a blocker. Either way the
            # fingerprint stays unspent: a malformed asserted row must not
            # claim the fingerprint of the analyzer row that carries the same
            # one, which would drop a real blocker out of both populations.
            if not asserted:
                ungradable.append(fingerprint or "<no fingerprint>")
            return
        if fingerprint:
            seen.add(fingerprint)
        if asserted or fingerprint in verified:
            confirmed.append(coerced)
        else:
            unverified.append(coerced)

    for item in asserted_findings:
        _grade(item, asserted=True)
    for item in analyzer_findings:
        _grade(item, asserted=False)

    return ValidationState(
        terminal_submission=terminal_submission,
        terminal_submission_conflict=terminal_submission_conflict,
        confirmed_findings=tuple(confirmed),
        unverified_findings=tuple(unverified),
        ungradable_fingerprints=tuple(ungradable),
        static_checks=tuple(dict(row) for row in static_checks if isinstance(row, dict)),
        withdrawn_fingerprints=withdrawn,
    )


def _blocks_approve(state: ValidationState) -> bool:
    """Whether any finding this run knows about must prevent an ``approve`` (D12, #263).

    One walk over both populations, because the rejection is the same either
    way: a blocking severity that survives the causality policy closes the
    approve path, whether a verifier confirmed the finding or nobody looked at
    it. Attribution is *not* a second condition — under the default
    ``base_comparison: "diff"`` no base run happens, so every diff-scoped
    finding stays ``introduced_by_pr: "unknown"`` and gating on ``"true"`` would
    exempt ruff, mypy, bandit and semgrep from the gate entirely. Where a base
    run *did* happen, a pre-existing finding is stamped ``"false"`` and the
    causality policy already downgrades it below the blocking threshold.

    The agent's valves are ``drop`` (the fingerprint leaves the state) and
    ``downgrade`` (the stored severity is rewritten), both applied before this
    runs — so approve stays reachable under a fail-closed gate.

    Args:
        state (ValidationState): The graded populations for this run.

    Returns:
        bool: True when ``approve`` must be rejected.

    Examples:
        >>> _blocks_approve(build_validation_state())
        False
    """
    from mergecraft.agents.gates import blocking_findings

    if state.ungradable_fingerprints:
        logger.warning(
            "{} analyzer finding(s) could not be graded; blocking approve: {}",
            len(state.ungradable_fingerprints),
            ", ".join(state.ungradable_fingerprints),
        )
        return True
    return bool(blocking_findings([*state.confirmed_findings, *state.unverified_findings]))


def withdrawn_fingerprints_for_state(tool_state: ToolState, *, tmpdir: str | None) -> set[str]:
    """Collect the fingerprints a verifier ``drop`` retired.

    ``ToolState.withdrawn_fingerprints`` is authoritative **within a run** —
    only canonical fingerprints survive the learnings round trip, so the live
    set is what makes the valve reliable here. The learnings file is the
    **cross-run** memory of the same decision, read through the parser analyzer
    suppression uses, and is unioned in so a drop recorded before this state was
    built (or by an earlier run) still counts. The default tmpdir path is
    resolved the way the writer resolves it, or a run that never set an explicit
    learnings path would not see its own file.
    """
    from mergecraft.analyzers.scope import withdrawn_fingerprints
    from mergecraft.utils.learnings import learnings_file_path

    candidates: list[str] = [
        raw for raw in (tool_state.learnings_file_path, tool_state.xrepo_learnings_file_path) if raw
    ]
    if not candidates and tmpdir:
        candidates.append(learnings_file_path(tmpdir))

    collected: set[str] = set(tool_state.withdrawn_fingerprints)
    for raw in candidates:
        path = Path(raw)
        if not path.is_file():
            continue
        collected |= set(withdrawn_fingerprints(path.read_text(encoding="utf-8")))
    return collected


def validation_state_from_tool_state(
    tool_state: ToolState, *, tmpdir: str | None = None
) -> ValidationState:
    """Grade a live ``ToolState`` into the state ``validate_submission`` reads."""
    analyzer_run = tool_state.analyzer_run
    verified: set[str] = set(tool_state.verified_ids)
    if analyzer_run is not None:
        verified |= set(analyzer_run.verified_ids)
    return build_validation_state(
        terminal_submission=tool_state.terminal_submission,
        terminal_submission_conflict=tool_state.terminal_submission_conflict,
        asserted_findings=tool_state.confirmed_findings,
        analyzer_findings=analyzer_run.findings if analyzer_run is not None else (),
        verified_fingerprints=verified,
        static_checks=tool_state.static_checks,
        withdrawn_fingerprints=withdrawn_fingerprints_for_state(tool_state, tmpdir=tmpdir),
    )


def validation_state_from_tool_context(ctx: ToolContext) -> ValidationState:
    """Build the consultation object from a live ``ToolContext``."""
    return validation_state_from_tool_state(ctx.tool_state, tmpdir=ctx.tmpdir)


def validate_submission(
    submission: dict[str, Any], *, state: ValidationState
) -> SubmissionValidation:
    """Pure semantic + structural validation for a terminal verdict payload (D5, D9)."""
    if state.terminal_submission_conflict:
        return SubmissionValidation(
            accepted=False,
            rejection_reason=REJECTION_CONFLICTING_SUBMISSION,
        )

    if not isinstance(submission, dict):
        return SubmissionValidation(
            accepted=False,
            rejection_reason=REJECTION_MISSING_REQUIRED_FIELDS,
        )

    unknown = set(submission.keys()) - _ALLOWED_TOP_LEVEL_KEYS
    if unknown:
        return SubmissionValidation(
            accepted=False,
            rejection_reason=REJECTION_UNKNOWN_FIELDS,
        )

    for key in _REQUIRED_TOP_LEVEL_KEYS:
        if key not in submission:
            return SubmissionValidation(
                accepted=False,
                rejection_reason=REJECTION_MISSING_REQUIRED_FIELDS,
            )

    verdict = submission["verdict"]
    if verdict not in _ALLOWED_VERDICTS:
        return SubmissionValidation(
            accepted=False,
            rejection_reason=REJECTION_INVALID_VERDICT,
        )

    findings_raw = submission.get("findings", [])
    if findings_raw is None:
        findings_raw = []
    if not isinstance(findings_raw, list):
        return SubmissionValidation(
            accepted=False,
            rejection_reason=REJECTION_MISSING_REQUIRED_FIELDS,
        )

    if verdict == "request_changes" and len(findings_raw) == 0:
        return SubmissionValidation(
            accepted=False,
            rejection_reason=REJECTION_REQUEST_CHANGES_NO_FINDINGS,
        )

    if verdict == "approve":
        from mergecraft.agents.gates import has_failed_required_static_check

        if _blocks_approve(state):
            return SubmissionValidation(
                accepted=False,
                rejection_reason=REJECTION_APPROVE_CONFIRMED_BLOCKER,
            )
        if has_failed_required_static_check(list(state.static_checks)):
            return SubmissionValidation(
                accepted=False,
                rejection_reason=REJECTION_APPROVE_FAILED_GATE,
            )

    return SubmissionValidation(accepted=True, rejection_reason=None)


class SubmitReviewVerdictParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["approve", "request_changes"]
    summary: str
    findings: list[Any] = Field(default_factory=list)

    @field_validator("findings", mode="before")
    @classmethod
    def _coerce_findings(cls, value: object) -> list[Any]:
        if not isinstance(value, list):
            msg = "findings must be a list"
            raise ValueError(msg)
        coerced: list[Any] = []
        for item in value:
            finding = coerce_agent_finding(item)
            if finding.severity not in FINDING_SEVERITIES:
                msg = f"severity must be one of {FINDING_SEVERITIES!r}, got {finding.severity!r}"
                raise ValueError(msg)
            coerced.append(finding)
        return coerced


def recorded_submission_payload(submission: Any) -> dict[str, Any]:
    findings: list[Any] = []
    for item in submission.findings:
        if hasattr(item, "model_dump"):
            findings.append(item.model_dump(mode="json"))
        else:
            findings.append(item)
    return {
        "verdict": submission.verdict,
        "summary": submission.summary,
        "findings": findings,
    }


def revalidate_recorded_submission(ctx: ToolContext) -> None:
    """Reject a stored verdict that current evidence has made unusable."""
    submission = ctx.tool_state.terminal_submission
    if submission is None:
        return
    validation = validate_submission(
        recorded_submission_payload(submission),
        state=validation_state_from_tool_context(ctx),
    )
    if not validation.accepted:
        msg = f"terminal submission rejected: {validation.rejection_reason}"
        raise ValueError(msg)


def after_terminal_submission_recorded(
    ctx: ToolContext,
    recorded: TerminalSubmission,
    *,
    replayed: bool,
) -> None:
    """Run post-record hooks for a newly persisted terminal submission.

    Idempotent replays (same payload hash) skip enterprise audit so the JSONL
    stream does not accumulate duplicate ``terminal_verdict`` rows.
    """
    if replayed:
        return
    from mergecraft.enterprise.audit import maybe_audit_blocking_terminal_submission

    maybe_audit_blocking_terminal_submission(ctx, recorded)


def submit_review_verdict_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]) -> dict[str, Any]:
        ensure_review_scope_for_terminal(ctx.tool_state, "submit_review_verdict")
        validated = SubmitReviewVerdictParams.model_validate(params)
        repo_root = Path(primary_repo_state(ctx.tool_state).dir)
        trust = (
            ctx.tool_state.trust_tier
            if ctx.tool_state.trust_tier in {"trusted", "untrusted"}
            else "trusted"
        )
        normalized_findings = normalize_agent_findings_via_pipeline(
            list(validated.findings),
            rule_id="agent:terminal",
            dedupe=True,
            repo_root=repo_root,
            trust_tier=trust,  # type: ignore[arg-type]
        )
        submission_dict = {
            "verdict": validated.verdict,
            "summary": validated.summary,
            "findings": [
                item.model_dump() if hasattr(item, "model_dump") else item
                for item in normalized_findings
            ],
        }
        existing = ctx.tool_state.terminal_submission
        existing_id = existing.id if existing is not None else None
        recorded = record_validated_terminal_submission(
            ctx,
            submission_dict,
            findings=normalized_findings,
        )
        replayed = existing_id is not None and recorded.id == existing_id
        after_terminal_submission_recorded(ctx, recorded, replayed=replayed)
        ctx.tool_state.review_phase = ReviewPhase.SUBMIT.value
        stamp_review_phase_on_active_span(ReviewPhase.SUBMIT)
        return {
            "recorded": True,
            "id": recorded.id,
            "verdict": recorded.verdict,
            "replayed": replayed,
        }

    return tool(
        name="submit_review_verdict",
        description=(
            "Record the terminal review verdict for this run: approve or request_changes, "
            "a summary, and structured findings. Identical re-submissions are idempotent; "
            "conflicting payloads are rejected. Does not publish to GitHub — call "
            "create_pull_request_review separately when publication is required."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "verdict": {
                    "type": "string",
                    "enum": ["approve", "request_changes"],
                    "description": "Structural terminal verdict for this review run.",
                },
                "summary": {
                    "type": "string",
                    "description": "Short summary of the review outcome.",
                },
                "findings": {
                    "type": "array",
                    "description": "Structured findings backing a request_changes verdict.",
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
                },
            },
            "required": ["verdict", "summary"],
            "additionalProperties": False,
        },
        mutates=False,
        tool_class=ToolClass.TERMINAL_PROTOCOL,
        execute=execute(_run, "submit_review_verdict"),
    )


def establish_review_scope_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]) -> dict[str, Any]:
        diff_path = str(params["diff_path"])
        head_sha = str(params["head_sha"])
        await validate_review_scope_evidence(ctx, diff_path=diff_path, head_sha=head_sha)
        # Only this route takes the diff from the caller. ``get_commit_info``
        # builds its own from the commit API, so there is nothing to authenticate
        # there — re-checking it would demand a single commit cover every file in
        # the PR, which a commit diff legitimately does not.
        pull_number = ctx.tool_state.pr_number or primary_repo_state(ctx.tool_state).issue_number
        if pull_number is not None:
            await reject_diff_that_does_not_match_the_pr(
                ctx, diff_path=diff_path, pull_number=int(pull_number)
            )
        register_review_scope(ctx.tool_state, diff_path=diff_path, provenance="local-diff")
        return {
            "diffPath": diff_path,
            "headSha": head_sha,
            "baseSha": str(params.get("base_sha") or ""),
            "provenance": "local-diff",
            "reviewPhase": ReviewPhase.ESTABLISH_SCOPE.value,
        }

    return tool(
        name="establish_review_scope",
        tool_class=ToolClass.SCOPE,
        mutates=True,
        description=(
            "Establish review scope from an on-disk unified diff that describes the "
            "PR head. Validates that diff_path exists, is non-empty, and head_sha "
            "matches the PR head from the API."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "diff_path": {"type": "string"},
                "base_sha": {"type": "string"},
                "head_sha": {"type": "string"},
            },
            "required": ["diff_path", "base_sha", "head_sha"],
            "additionalProperties": False,
        },
        execute=execute(_run, "establish_review_scope"),
    )


__all__ = [
    "REJECTION_APPROVE_CONFIRMED_BLOCKER",
    "REJECTION_APPROVE_FAILED_GATE",
    "REJECTION_CONFLICTING_SUBMISSION",
    "REJECTION_INVALID_VERDICT",
    "REJECTION_MISSING_REQUIRED_FIELDS",
    "REJECTION_REQUEST_CHANGES_NO_FINDINGS",
    "REJECTION_SCOPE_UNAVAILABLE",
    "REJECTION_UNKNOWN_FIELDS",
    "ReviewPhase",
    "SubmissionValidation",
    "SubmitReviewVerdictParams",
    "ValidationState",
    "VerdictDiagnostic",
    "after_terminal_submission_recorded",
    "build_validation_state",
    "establish_offline_review_scope",
    "establish_review_scope_tool",
    "record_scope_rejection_if_blocked",
    "record_terminal_rejection",
    "record_validated_terminal_submission",
    "recorded_submission_payload",
    "register_review_scope",
    "revalidate_recorded_submission",
    "scope_blocks_terminal",
    "span_attrs_for_verdict_diagnostic",
    "stamp_review_phase_on_active_span",
    "submit_review_verdict_tool",
    "terminal_tool_was_attempted",
    "validate_submission",
    "validation_state_from_tool_context",
    "validation_state_from_tool_state",
    "verdict_satisfies_attempt",
    "withdrawn_fingerprints_for_state",
]
