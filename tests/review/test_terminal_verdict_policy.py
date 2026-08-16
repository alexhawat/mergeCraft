"""VP2 fail-closed terminal verdict — policy, validator, and outcome resolver.

Wave plan: ``.ignorelocal/01-review-integrity-wave-plan.md`` (VP2.1 RED, VP2.2
impl; xfail markers cleared after VP2.2; VP2.3 live ``run_static_checks`` persist;
VP2.4 sticky failed static_checks across empty-plan rerun).

Pinned contracts (W0):
    D2 — missing verdict → ``RunOutcome.inconclusive``, not ``failed``.
    D4 — identical resubmit is idempotent; a conflicting payload fails closed.
    D5 — ``validate_submission`` returns a typed ``SubmissionValidation``, not a bool.
    D8 — semantic rejection is fallback-eligible (``terminal_submission_received``
         stays false) and maps to ``inconclusive``.
    D9 — ``request_changes`` with zero findings is semantically rejected.
    V3 — provider success without a terminal verdict is not a successful review.
    Convention 3 — do not widen ``RunOutcome``.
    Convention 4 — do not change ``decide_approval``'s signature.
"""

from __future__ import annotations

import inspect
import json
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.agents.gates import decide_approval
from mergecraft.agents.post_run import finalize_agent_result
from mergecraft.agents.shared import AgentResult, AgentRunContext, AgentUsage, ResolvedInstructions
from mergecraft.agents.verifier import AgentFinding
from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.mcp.comment import create_issue_comment_tool, report_progress_tool
from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.review import create_pull_request_review_tool
from mergecraft.mcp.shared import ToolResult
from mergecraft.mcp.static_checks import _persist_static_checks, run_static_checks_tool
from mergecraft.mcp.tool_state import AnalyzerRunState, init_tool_state, primary_repo_state
from mergecraft.modes import compute_modes
from mergecraft.review_checks import StaticCheckConfig
from mergecraft.review_taxonomy import FINDING_MARKER_PREFIX, finding_fingerprint
from mergecraft.run_outcome import RunOutcome, run_succeeded_for_outcome
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path

_MISSING_VERDICT_REASON = "no terminal review verdict was submitted for this attempt"
_DECIDE_APPROVAL_PARAMS = ("findings", "run_succeeded", "tier")
_CLOSED_OUTCOMES = frozenset(
    {
        "passed",
        "failed",
        "inconclusive",
        "infra_error",
        "timed_out",
        "configuration_error",
    }
)

# Closed ``rejection_reason`` vocabulary (D5). Schema / semantic / policy stay
# distinct so a check-run can name which class of rejection fired.
_REASON_INVALID_VERDICT = "invalid_verdict"
_REASON_UNKNOWN_FIELDS = "unknown_fields"
_REASON_MISSING_REQUIRED = "missing_required_fields"
_REASON_REQUEST_CHANGES_NO_FINDINGS = "request_changes_without_findings"
_REASON_APPROVE_CONFIRMED_BLOCKER = "approve_with_confirmed_blocker"
_REASON_APPROVE_FAILED_GATE = "approve_with_failed_required_gate"
_REASON_CONFLICTING_SUBMISSION = "conflicting_submission"


def _ctx(
    tmp_path: Path,
    *,
    issue_number: int | None = 7,
    static_checks: list[StaticCheckConfig] | None = None,
    static_checks_enabled: bool = False,
) -> ToolContext:
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request", issue_number=issue_number, is_pr=True),
            shell="restricted",
        ),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_server_url="",
        tmpdir=str(tmp_path),
        pr_approve_enabled=True,
        static_checks=list(static_checks or []),
        static_checks_enabled=static_checks_enabled,
    )


def _run_ctx(tool_ctx: ToolContext) -> AgentRunContext:
    return AgentRunContext(
        payload=tool_ctx.payload,
        mcp_server_url=tool_ctx.mcp_server_url,
        tmpdir=tool_ctx.tmpdir,
        subagent_denied_tools=(),
        instructions=ResolvedInstructions(),
        tool_state=tool_ctx.tool_state,
    )


def _classify(
    result: AgentResult,
    *,
    mode: str = "Review",
    final_summary_written: bool = False,
) -> tuple[RunOutcome, str | None]:
    """Drive the real ``_classify_outcome`` with the VP2 ``mode`` parameter."""
    from mergecraft.main_outcome import _classify_outcome

    outcome, reason = _classify_outcome(
        result=result,
        setup_reason="",
        setup_policy="warn",
        prep_reason=None,
        mode=mode,
        final_summary_written=final_summary_written,
    )
    return outcome, reason


def _validate(submission: dict[str, Any], *, state: Any) -> Any:
    """Import ``validate_submission`` inside the body so collection stays green."""
    from mergecraft.mcp.verdict import validate_submission

    return validate_submission(submission, state=state)


def _validation_type() -> type[Any]:
    from mergecraft.mcp.verdict import SubmissionValidation

    return SubmissionValidation


def _validation_state(
    tool_state: Any,
    *,
    confirmed_findings: list[Finding] | None = None,
    static_checks: list[dict[str, str]] | None = None,
    withdrawn_fingerprints: frozenset[str] | None = None,
) -> Any:
    """Consultation inputs the validator reads (D5 / required-gate rows).

    ``state`` duck-types ``ToolState`` fields plus the VP2.2 surfaces the
    validator consults: verifier-confirmed findings, ``run_static_checks``
    status rows, and withdrawn fingerprints.
    """
    return SimpleNamespace(
        terminal_submission=tool_state.terminal_submission,
        terminal_submission_conflict=tool_state.terminal_submission_conflict,
        confirmed_findings=list(confirmed_findings or []),
        static_checks=list(static_checks or []),
        withdrawn_fingerprints=set(withdrawn_fingerprints or []),
        tool_state=tool_state,
        analyzer_run=tool_state.analyzer_run,
    )


def _approve_payload() -> dict[str, Any]:
    return {
        "verdict": "approve",
        "summary": "No blocking issues in the diff.",
        "findings": [],
    }


def _blocker_finding() -> Finding:
    return make_finding(
        tool="vp2-fixture",
        rule_id="VP2-BLOCKER",
        category="Security & Privacy",
        severity="Critical",
        confidence="certain",
        message="Secret written to logs.",
        path="src/app.py",
        start_line=12,
        end_line=12,
        source="agent",
        evidence=["logger.info(api_key)"],
        fingerprint="vp2-blocker-cr",
    )


def _trivial_finding() -> Finding:
    return make_finding(
        tool="vp2-fixture",
        rule_id="VP2-NIT",
        category="Maintainability & Code Quality",
        severity="Trivial",
        confidence="possible",
        message="Missing trailing period in a docstring.",
        path="src/app.py",
        start_line=1,
        end_line=1,
        source="agent",
        evidence=["line 1"],
        fingerprint="vp2-trivial-tr",
    )


def _agent_blocker() -> AgentFinding:
    return AgentFinding(
        path="src/app.py",
        body="Secret written to logs.",
        severity="Critical",
        line=12,
        fingerprint="vp2-blocker-cr",
    )


def _assert_typed_rejection(validation: Any, reason: str) -> None:
    validation_cls = _validation_type()
    assert isinstance(validation, validation_cls)
    assert type(validation) is not bool
    assert validation.accepted is False
    assert validation.rejection_reason == reason


def _assert_decide_approval_signature_unchanged() -> None:
    params = inspect.signature(decide_approval).parameters
    assert tuple(params) == _DECIDE_APPROVAL_PARAMS
    assert params["run_succeeded"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["tier"].kind is inspect.Parameter.KEYWORD_ONLY


def _assert_run_outcome_not_widened() -> None:
    assert {member.value for member in RunOutcome} == _CLOSED_OUTCOMES
    assert len(RunOutcome) == 6


async def _submit_verdict(ctx: ToolContext, payload: dict[str, Any]) -> ToolResult:
    from mergecraft.mcp.verdict import submit_review_verdict_tool

    return await submit_review_verdict_tool(ctx).execute(payload)


class _RecordingGitHub(GitHubClient):
    """Captures review and comment payloads instead of sending them."""

    def __init__(self) -> None:
        super().__init__(token="test-token")
        self.review_payloads: list[dict[str, Any]] = []
        self.comment_payloads: list[dict[str, Any]] = []
        self._comment_id = 100

    async def create_review(
        self, owner: str, repo: str, pull_number: int, **payload: Any
    ) -> dict[str, Any]:
        self.review_payloads.append(payload)
        return {
            "id": 1,
            "node_id": "n1",
            "html_url": "https://example.test/1",
            "state": payload.get("event") or "COMMENTED",
        }

    async def create_issue_comment(
        self, owner: str, repo: str, issue_number: int, body: str
    ) -> dict[str, Any]:
        self._comment_id += 1
        record = {
            "id": self._comment_id,
            "html_url": f"https://example.test/comments/{self._comment_id}",
            "body": body,
            "issue_number": issue_number,
        }
        self.comment_payloads.append(record)
        return record


def test_valid_approve_and_clear_gates_succeeds(tmp_path: Path) -> None:
    """A schema-valid ``approve`` with no blockers and passing gates is accepted."""
    from mergecraft.mcp.verdict import validation_state_from_tool_context

    ctx = _ctx(tmp_path)
    derived = validation_state_from_tool_context(ctx)
    assert derived.tool_state is ctx.tool_state
    assert derived.analyzer_run is ctx.tool_state.analyzer_run
    assert derived.terminal_submission is ctx.tool_state.terminal_submission
    state = _validation_state(ctx.tool_state, static_checks=[{"name": "lint", "status": "passed"}])
    validation = _validate(_approve_payload(), state=state)
    assert isinstance(validation, _validation_type())
    assert validation.accepted is True
    assert validation.rejection_reason is None

    result = AgentResult(
        success=True,
        terminal_submission_received=True,
        terminal_submission_id="sub-1",
    )
    outcome, reason = _classify(result, mode="Review")
    _assert_run_outcome_not_widened()
    assert outcome is RunOutcome.passed
    assert reason is None
    assert decide_approval([_trivial_finding()], run_succeeded=True, tier="trusted") == "success"


def test_agent_approve_with_verified_blocker_fails_structurally(tmp_path: Path) -> None:
    """``approve`` over a verifier-confirmed Critical/Major finding is rejected."""
    blocker = _blocker_finding()
    ctx = _ctx(tmp_path)
    ctx.tool_state.analyzer_run = AnalyzerRunState(
        ran=True,
        findings=[blocker.model_dump()],
        verified_ids={blocker.fingerprint},
    )
    state = _validation_state(ctx.tool_state, confirmed_findings=[blocker])
    validation = _validate(_approve_payload(), state=state)
    _assert_typed_rejection(validation, _REASON_APPROVE_CONFIRMED_BLOCKER)

    conclusion = decide_approval([blocker], run_succeeded=True, tier="trusted")
    assert conclusion == "failure"


@pytest.mark.asyncio
async def test_live_confirm_blocks_approve_via_verified_ids(tmp_path: Path) -> None:
    """Live path: ``record_finding_verdict(confirm)`` must populate ``verified_ids``.

    Does not seed ``verified_ids``. The fingerprint must come from the verdict
    tool so ``validation_state_from_tool_context`` sees the confirmed blocker.
    """
    from mergecraft.mcp.verdict import (
        submit_review_verdict_tool,
        validation_state_from_tool_context,
    )
    from mergecraft.mcp.verification import record_finding_verdict_tool

    blocker = _blocker_finding()
    ctx = _ctx(tmp_path)
    ctx.tool_state.analyzer_run = AnalyzerRunState(
        ran=True,
        findings=[blocker.model_dump()],
        verified_ids=set(),
    )
    recorded = await record_finding_verdict_tool(ctx).execute(
        {
            "fingerprint": blocker.fingerprint,
            "verdict": "confirm",
            "reason": "Reproduced the secret leak.",
        }
    )
    assert recorded.is_error is False
    from mergecraft.mcp.verification import _persist_confirmed_fingerprint

    assert callable(_persist_confirmed_fingerprint)
    assert blocker.fingerprint in ctx.tool_state.analyzer_run.verified_ids
    assert blocker.fingerprint in ctx.tool_state.verified_ids

    derived = validation_state_from_tool_context(ctx)
    _assert_typed_rejection(
        _validate(_approve_payload(), state=derived),
        _REASON_APPROVE_CONFIRMED_BLOCKER,
    )
    verdict = await submit_review_verdict_tool(ctx).execute(_approve_payload())
    assert verdict.is_error is True
    assert _REASON_APPROVE_CONFIRMED_BLOCKER in verdict.content[0]["text"]
    assert ctx.tool_state.terminal_submission is None


@pytest.mark.asyncio
async def test_live_agent_confirm_blocks_approve_without_analyzer_findings(
    tmp_path: Path,
) -> None:
    """A confirmed agent-authored blocker must reject approve without seeding analyzer findings."""
    from mergecraft.mcp.verdict import (
        submit_review_verdict_tool,
        validation_state_from_tool_context,
    )
    from mergecraft.mcp.verification import record_finding_verdict_tool, verify_agent_findings_tool

    finding = _agent_blocker()
    ctx = _ctx(tmp_path)
    ctx.tool_state.analyzer_run = AnalyzerRunState(ran=True, findings=[], verified_ids=set())
    planned = await verify_agent_findings_tool(ctx).execute({"findings": [finding.model_dump()]})
    assert planned.is_error is False
    recorded = await record_finding_verdict_tool(ctx).execute(
        {
            "fingerprint": finding.fingerprint,
            "verdict": "confirm",
            "reason": "Reproduced the secret leak.",
        }
    )
    assert recorded.is_error is False
    assert finding.fingerprint in ctx.tool_state.verified_ids
    assert ctx.tool_state.analyzer_run.findings == []

    derived = validation_state_from_tool_context(ctx)
    _assert_typed_rejection(
        _validate(_approve_payload(), state=derived),
        _REASON_APPROVE_CONFIRMED_BLOCKER,
    )
    verdict = await submit_review_verdict_tool(ctx).execute(_approve_payload())
    assert verdict.is_error is True
    assert _REASON_APPROVE_CONFIRMED_BLOCKER in verdict.content[0]["text"]


@pytest.mark.asyncio
async def test_confirm_survives_analyzer_rerun(tmp_path: Path) -> None:
    """A later ``run_analyzers`` replace must not drop a confirmed blocker."""
    from mergecraft.mcp.analyzers import _store_run_state
    from mergecraft.mcp.verdict import (
        submit_review_verdict_tool,
        validation_state_from_tool_context,
    )
    from mergecraft.mcp.verification import record_finding_verdict_tool

    blocker = _blocker_finding()
    ctx = _ctx(tmp_path)
    ctx.tool_state.analyzer_run = AnalyzerRunState(
        ran=True,
        findings=[blocker.model_dump()],
        verified_ids=set(),
    )
    recorded = await record_finding_verdict_tool(ctx).execute(
        {
            "fingerprint": blocker.fingerprint,
            "verdict": "confirm",
            "reason": "Reproduced the secret leak.",
        }
    )
    assert recorded.is_error is False
    _store_run_state(ctx, AnalyzerRunState(ran=True, findings=[], verified_ids=set()))
    assert blocker.fingerprint in ctx.tool_state.verified_ids
    derived = validation_state_from_tool_context(ctx)
    _assert_typed_rejection(
        _validate(_approve_payload(), state=derived),
        _REASON_APPROVE_CONFIRMED_BLOCKER,
    )
    verdict = await submit_review_verdict_tool(ctx).execute(_approve_payload())
    assert verdict.is_error is True
    assert _REASON_APPROVE_CONFIRMED_BLOCKER in verdict.content[0]["text"]


def test_request_changes_with_verified_blocker_blocks(tmp_path: Path) -> None:
    """``request_changes`` with a confirmed blocker is a usable verdict; the gate blocks."""
    blocker = _blocker_finding()
    finding = _agent_blocker()
    ctx = _ctx(tmp_path)
    state = _validation_state(ctx.tool_state, confirmed_findings=[blocker])
    validation = _validate(
        {
            "verdict": "request_changes",
            "summary": "One critical finding stands.",
            "findings": [finding.model_dump()],
        },
        state=state,
    )
    assert isinstance(validation, _validation_type())
    assert validation.accepted is True
    assert validation.rejection_reason is None

    assert decide_approval([blocker], run_succeeded=True, tier="trusted") == "failure"


def test_no_terminal_submission_is_inconclusive() -> None:
    """D2: a successful provider result with no terminal verdict is ``inconclusive``."""
    from mergecraft.main_outcome import _is_review_mode

    _assert_run_outcome_not_widened()
    assert _is_review_mode("Review") is True
    assert _is_review_mode("IncrementalReview") is True
    assert _is_review_mode("Build") is False
    assert _is_review_mode(None) is False
    review_mode = next(m for m in compute_modes("claude") if m.name == "Review")
    assert _is_review_mode(review_mode) is True
    result = AgentResult(success=True, terminal_submission_received=False)
    assert result.success is True
    assert result.terminal_submission_received is False

    for mode in ("Review", "IncrementalReview"):
        outcome, reason = _classify(result, mode=mode)
        assert outcome is RunOutcome.inconclusive
        assert outcome is not RunOutcome.failed
        assert reason == _MISSING_VERDICT_REASON
        assert run_succeeded_for_outcome(outcome) is False

    build_outcome, _ = _classify(result, mode="Build")
    assert build_outcome is RunOutcome.passed


def test_prose_lgtm_without_terminal_call_cannot_approve() -> None:
    """Narrative ``LGTM`` is not an input to ``decide_approval`` and cannot pass a review."""
    _assert_decide_approval_signature_unchanged()
    params = inspect.signature(decide_approval).parameters
    assert "output" not in params
    assert "narrative" not in params
    assert "approved" not in params
    assert "would_approve" not in params

    result = AgentResult(
        success=True,
        output="LGTM — looks good to me.",
        terminal_submission_received=False,
    )
    outcome, reason = _classify(result, mode="Review")
    assert outcome is RunOutcome.inconclusive
    assert outcome is not RunOutcome.passed
    assert reason == _MISSING_VERDICT_REASON

    conclusion = decide_approval(
        [],
        run_succeeded=run_succeeded_for_outcome(outcome),
        tier="trusted",
    )
    assert conclusion != "success"


def test_invalid_verdict_enum_rejected(tmp_path: Path) -> None:
    """Schema: ``\"lgtm\"`` is not a verdict — typed rejection, not a bool."""
    ctx = _ctx(tmp_path)
    validation = _validate(
        {**_approve_payload(), "verdict": "lgtm"},
        state=_validation_state(ctx.tool_state),
    )
    _assert_typed_rejection(validation, _REASON_INVALID_VERDICT)


def test_unknown_fields_rejected(tmp_path: Path) -> None:
    """Schema: an unrecognized key is a typed rejection, not a silent drop."""
    ctx = _ctx(tmp_path)
    validation = _validate(
        {**_approve_payload(), "unexpected_field": "nope"},
        state=_validation_state(ctx.tool_state),
    )
    _assert_typed_rejection(validation, _REASON_UNKNOWN_FIELDS)


def test_missing_required_fields_rejected(tmp_path: Path) -> None:
    """Schema: absent ``summary`` / ``verdict`` is a typed rejection."""
    ctx = _ctx(tmp_path)
    state = _validation_state(ctx.tool_state)
    for omit in ("summary", "verdict"):
        payload = _approve_payload()
        del payload[omit]
        validation = _validate(payload, state=state)
        _assert_typed_rejection(validation, _REASON_MISSING_REQUIRED)


def test_request_changes_with_no_findings_is_semantically_rejected(tmp_path: Path) -> None:
    """D9: ``request_changes`` with zero findings is a semantic rejection."""
    ctx = _ctx(tmp_path)
    validation = _validate(
        {
            "verdict": "request_changes",
            "summary": "Please change things.",
            "findings": [],
        },
        state=_validation_state(ctx.tool_state),
    )
    _assert_typed_rejection(validation, _REASON_REQUEST_CHANGES_NO_FINDINGS)
    # Schema-valid (findings default to []) — this is not a missing-field error.
    assert validation.rejection_reason != _REASON_MISSING_REQUIRED


@pytest.mark.asyncio
async def test_duplicate_conflicting_submissions_fail_closed(tmp_path: Path) -> None:
    """D4: a differing payload is rejected and the attempt is unusable."""
    ctx = _ctx(tmp_path)
    first = await _submit_verdict(ctx, _approve_payload())
    assert first.is_error is False
    original_id = ctx.tool_state.terminal_submission.id  # type: ignore[union-attr]

    conflicting = {**_approve_payload(), "summary": "Actually this needs changes."}
    second = await _submit_verdict(ctx, conflicting)
    assert second.is_error is True
    assert ctx.tool_state.terminal_submission_conflict is True
    assert ctx.tool_state.terminal_submission is not None
    assert ctx.tool_state.terminal_submission.id == original_id

    validation = _validate(conflicting, state=_validation_state(ctx.tool_state))
    _assert_typed_rejection(validation, _REASON_CONFLICTING_SUBMISSION)

    finalized = await finalize_agent_result(_run_ctx(ctx), AgentResult(success=True))
    assert finalized.terminal_submission_received is False
    assert finalized.diagnostics
    outcome, reason = _classify(finalized, mode="Review")
    assert outcome is RunOutcome.inconclusive
    assert outcome is not RunOutcome.passed
    assert reason is not None
    assert run_succeeded_for_outcome(outcome) is False


@pytest.mark.asyncio
async def test_identical_resubmission_is_idempotent(tmp_path: Path) -> None:
    """D4: the same payload hash returns the original id and remains a usable verdict."""
    ctx = _ctx(tmp_path)
    payload = _approve_payload()
    first = await _submit_verdict(ctx, payload)
    assert first.is_error is False
    original = ctx.tool_state.terminal_submission
    assert original is not None
    original_id = original.id

    second = await _submit_verdict(ctx, payload)
    assert second.is_error is False
    assert ctx.tool_state.terminal_submission is original
    assert ctx.tool_state.terminal_submission_conflict is False

    validation = _validate(payload, state=_validation_state(ctx.tool_state))
    assert isinstance(validation, _validation_type())
    assert validation.accepted is True

    finalized = await finalize_agent_result(_run_ctx(ctx), AgentResult(success=True))
    assert finalized.terminal_submission_received is True
    assert finalized.terminal_submission_id == original_id
    outcome, reason = _classify(finalized, mode="Review")
    assert outcome is RunOutcome.passed
    assert reason is None
    assert run_succeeded_for_outcome(outcome) is True


def test_provider_success_without_verdict_is_not_a_successful_review() -> None:
    """V3: ``_classify_outcome`` must not return ``passed`` when no verdict was submitted."""
    result = AgentResult(success=True, output="done", terminal_submission_received=False)
    outcome, reason = _classify(result, mode="Review")
    assert outcome is not RunOutcome.passed
    assert outcome is RunOutcome.inconclusive
    assert reason == _MISSING_VERDICT_REASON
    assert run_succeeded_for_outcome(outcome) is False


def test_missing_verdict_leaves_run_fallback_eligible(tmp_path: Path) -> None:
    """D8 / D13: absence and semantic rejection both leave ``received=False``."""
    missing = AgentResult(success=True, terminal_submission_received=False)
    outcome, reason = _classify(missing, mode="Review")
    assert missing.terminal_submission_received is False
    assert outcome is RunOutcome.inconclusive
    assert reason == _MISSING_VERDICT_REASON
    assert outcome is not RunOutcome.failed
    assert run_succeeded_for_outcome(outcome) is False

    ctx = _ctx(tmp_path)
    validation = _validate(
        {
            "verdict": "request_changes",
            "summary": "Please change things.",
            "findings": [],
        },
        state=_validation_state(ctx.tool_state),
    )
    _assert_typed_rejection(validation, _REASON_REQUEST_CHANGES_NO_FINDINGS)
    rejected = AgentResult(
        success=True,
        terminal_submission_received=False,
        diagnostics={"rejection_reason": validation.rejection_reason},
    )
    rejected_outcome, _ = _classify(rejected, mode="Review")
    assert rejected.terminal_submission_received is False
    assert rejected_outcome is RunOutcome.inconclusive
    assert rejected_outcome is not RunOutcome.failed


def test_fresh_valid_verdict_does_not_trigger_fallback() -> None:
    """A usable terminal submission is not fallback-eligible (D13)."""
    result = AgentResult(
        success=True,
        terminal_submission_received=True,
        terminal_submission_id="sub-fresh",
    )
    outcome, reason = _classify(result, mode="Review")
    assert result.terminal_submission_received is True
    assert outcome is RunOutcome.passed
    assert reason is None
    assert run_succeeded_for_outcome(outcome) is True


def test_approve_with_failing_required_deterministic_check_fails(tmp_path: Path) -> None:
    """``approve`` with a failed required ``run_static_checks`` gate is rejected."""
    from mergecraft.agents.gates import has_failed_required_static_check

    ctx = _ctx(tmp_path)
    failed_rows = [{"name": "lint", "status": "failed"}]
    assert has_failed_required_static_check(failed_rows) is True
    assert has_failed_required_static_check([{"name": "lint", "status": "passed"}]) is False
    assert has_failed_required_static_check([]) is False
    state = _validation_state(
        ctx.tool_state,
        static_checks=failed_rows,
    )
    validation = _validate(_approve_payload(), state=state)
    _assert_typed_rejection(validation, _REASON_APPROVE_FAILED_GATE)


@pytest.mark.asyncio
async def test_approve_after_failed_run_static_checks_tool_is_rejected(
    tmp_path: Path,
) -> None:
    """Live path: a failing ``run_static_checks`` gate must reject ``approve`` (D8).

    Does not inject ``static_checks=`` into a hand-built SimpleNamespace. Rows
    must come from ``run_static_checks_tool`` → ``ToolState`` →
    ``validation_state_from_tool_context``.
    """
    from mergecraft.mcp.verdict import (
        submit_review_verdict_tool,
        validation_state_from_tool_context,
    )

    ctx = _ctx(
        tmp_path,
        static_checks=[StaticCheckConfig(name="lint", command="python -c 'raise SystemExit(1)'")],
        static_checks_enabled=True,
    )
    checks_result = await run_static_checks_tool(ctx).execute({})
    assert checks_result.is_error is False
    payload = json.loads(checks_result.content[0]["text"])
    assert any(check.get("status") == "failed" for check in payload["checks"])
    # Direct pin: `_persist_static_checks` must have written the failed row
    # onto ToolState. Deleting the helper fails this import; skipping the
    # write leaves `tool_state.static_checks` without a failed row.
    assert callable(_persist_static_checks)
    assert any(row.get("status") == "failed" for row in ctx.tool_state.static_checks)

    verdict = await submit_review_verdict_tool(ctx).execute(_approve_payload())
    assert verdict.is_error is True
    assert _REASON_APPROVE_FAILED_GATE in verdict.content[0]["text"]
    assert ctx.tool_state.terminal_submission is None

    derived = validation_state_from_tool_context(ctx)
    assert any(row.get("status") == "failed" for row in derived.static_checks)
    _assert_typed_rejection(
        _validate(_approve_payload(), state=derived),
        _REASON_APPROVE_FAILED_GATE,
    )


@pytest.mark.asyncio
async def test_approve_then_failed_static_check_is_unusable_at_finalize(
    tmp_path: Path,
) -> None:
    """A stored ``approve`` must not stay usable after a later failed gate."""
    ctx = _ctx(
        tmp_path,
        static_checks=[StaticCheckConfig(name="lint", command="python -c 'raise SystemExit(1)'")],
        static_checks_enabled=True,
    )
    first = await _submit_verdict(ctx, _approve_payload())
    assert first.is_error is False
    original = ctx.tool_state.terminal_submission
    assert original is not None
    original_id = original.id

    checks_result = await run_static_checks_tool(ctx).execute({})
    assert checks_result.is_error is False
    assert any(row.get("status") == "failed" for row in ctx.tool_state.static_checks)

    finalized = await finalize_agent_result(_run_ctx(ctx), AgentResult(success=True))
    assert finalized.terminal_submission_received is False
    assert finalized.terminal_submission_id is None
    assert finalized.diagnostics.get("rejection_reason") == _REASON_APPROVE_FAILED_GATE
    assert ctx.tool_state.terminal_submission is not None
    assert ctx.tool_state.terminal_submission.id == original_id
    outcome, _reason = _classify(finalized, mode="Review")
    assert outcome is RunOutcome.inconclusive
    assert run_succeeded_for_outcome(outcome) is False


@pytest.mark.asyncio
async def test_failed_static_check_survives_empty_plan_rerun(
    tmp_path: Path,
) -> None:
    """A later empty ``plan_checks`` must not wipe a prior ``failed`` row.

    Suffix-filtered ``changed_files`` that match no gate must leave a prior
    ``failed`` row in place, so ``approve`` stays rejected (D8).
    """
    from mergecraft.mcp.verdict import (
        submit_review_verdict_tool,
        validation_state_from_tool_context,
    )

    lint = StaticCheckConfig(
        name="lint",
        command="python -c 'raise SystemExit(1)'",
        suffixes=(".py",),
    )
    assert isinstance(lint.suffixes, tuple)
    assert lint.suffixes == (".py",)

    ctx = _ctx(tmp_path, static_checks=[lint], static_checks_enabled=True)
    first = await run_static_checks_tool(ctx).execute({"changed_files": ["src/foo.py"]})
    assert first.is_error is False
    first_payload = json.loads(first.content[0]["text"])
    assert any(check.get("status") == "failed" for check in first_payload["checks"])

    second = await run_static_checks_tool(ctx).execute({"changed_files": ["README.md"]})
    assert second.is_error is False
    second_payload = json.loads(second.content[0]["text"])
    assert second_payload.get("ran") is False or second_payload.get("checks") == []

    verdict = await submit_review_verdict_tool(ctx).execute(_approve_payload())
    assert verdict.is_error is True
    assert _REASON_APPROVE_FAILED_GATE in verdict.content[0]["text"]
    assert ctx.tool_state.terminal_submission is None

    derived = validation_state_from_tool_context(ctx)
    assert any(row.get("status") == "failed" for row in derived.static_checks)
    _assert_typed_rejection(
        _validate(_approve_payload(), state=derived),
        _REASON_APPROVE_FAILED_GATE,
    )


def test_verifier_dropped_finding_does_not_block_approval() -> None:
    """A dropped finding is omitted before ``decide_approval``; the remainder may approve.

    Regression pin on the existing gate (convention 4). The verifier drop is
    applied by the caller — this test drives the real ``decide_approval``, it
    does not reimplement severity ranking.
    """
    _assert_decide_approval_signature_unchanged()
    dropped = _blocker_finding()
    remaining = [_trivial_finding()]
    # Guard-deletion pin: if the dropped Critical were left in the list, the
    # monotone-in-blockers gate would still fail. Callers must strip first.
    assert decide_approval([dropped, *remaining], run_succeeded=True, tier="trusted") == "failure"
    conclusion = decide_approval(remaining, run_succeeded=True, tier="trusted")
    assert conclusion != "failure"
    assert conclusion == "success"


def test_verifier_confirmed_finding_blocks_approval() -> None:
    """A verifier-confirmed Critical/Major finding blocks through real ``decide_approval``."""
    _assert_decide_approval_signature_unchanged()
    confirmed = _blocker_finding()
    conclusion = decide_approval([confirmed], run_succeeded=True, tier="trusted")
    assert conclusion == "failure"
    # Narrative is not an input — the same list still fails if we pretend the
    # agent approved. Deleting the blocker check would make this succeed.
    assert "would_approve" not in inspect.signature(decide_approval).parameters


@pytest.mark.asyncio
async def test_publication_cannot_bypass_structural_policy(tmp_path: Path) -> None:
    """Posting ``APPROVE`` / writing ``ApprovalRecord`` cannot outvote ``decide_approval``."""
    _assert_decide_approval_signature_unchanged()
    github = _RecordingGitHub()
    ctx = _ctx(tmp_path)
    ctx.github = github
    primary_repo_state(ctx.tool_state).checkout_sha = "abc123"

    spec = create_pull_request_review_tool(ctx)
    result = await spec.execute(
        {"pull_number": 7, "body": "Looks good.", "approved": True},
    )
    assert result.is_error is False
    assert ctx.tool_state.approval is not None
    assert ctx.tool_state.approval.would_approve is True
    assert github.review_payloads[0]["event"] == "APPROVE"

    blocker = _blocker_finding()
    conclusion = decide_approval([blocker], run_succeeded=True, tier="trusted")
    assert conclusion == "failure"
    assert "would_approve" not in inspect.signature(decide_approval).parameters


@pytest.mark.asyncio
async def test_existing_review_and_comment_behaviour_unchanged(tmp_path: Path) -> None:
    """Regression pin: ``create_pull_request_review`` and comment tools still behave as today."""
    github = _RecordingGitHub()
    ctx = _ctx(tmp_path)
    ctx.github = github
    primary_repo_state(ctx.tool_state).checkout_sha = "abc123"

    review_spec = create_pull_request_review_tool(ctx)
    first = await review_spec.execute(
        {
            "pull_number": 7,
            "body": "review body",
            "comments": [{"path": "src/app.py", "line": 12, "body": "A finding."}],
        }
    )
    assert first.is_error is False
    assert ctx.tool_state.review is not None
    assert ctx.tool_state.review.id == 1
    assert ctx.tool_state.terminal_submission is not None
    assert ctx.tool_state.terminal_submission.verdict == "request_changes"
    inline = github.review_payloads[0].get("comments") or []
    assert inline
    expected_fp = finding_fingerprint(path="src/app.py", body="A finding.")
    assert f"{FINDING_MARKER_PREFIX}{expected_fp} -->" in inline[0]["body"]

    replay = await review_spec.execute({"pull_number": 7, "body": "review body again"})
    assert replay.is_error is False
    replay_text = replay.content[0]["text"]
    assert "already submitted" in replay_text
    assert len(github.review_payloads) == 1

    comment = await create_issue_comment_tool(ctx).execute(
        {"issueNumber": 7, "body": "a regular comment"},
    )
    assert comment.is_error is False
    assert github.comment_payloads
    assert "a regular comment" in github.comment_payloads[0]["body"]

    progress = await report_progress_tool(ctx).execute({"body": "still working"})
    assert progress.is_error is False
    assert ctx.tool_state.last_progress_body == "still working"


def test_both_harness_paths_obey_the_same_contract() -> None:
    """An OpenCode-shaped and a Codex-shaped ``AgentResult`` reach the same outcome."""
    opencode = AgentResult(
        success=True,
        output="LGTM from opencode",
        metadata={"agent": "opencode", "harness": "opencode"},
        usage=AgentUsage(agent="opencode", input_tokens=10, output_tokens=4),
        terminal_submission_received=False,
    )
    codex = AgentResult(
        success=True,
        output="LGTM from codex",
        metadata={"agent": "codex", "harness": "codex"},
        usage=AgentUsage(agent="codex", input_tokens=10, output_tokens=4),
        terminal_submission_received=False,
    )
    opencode_outcome, opencode_reason = _classify(opencode, mode="Review")
    codex_outcome, codex_reason = _classify(codex, mode="Review")
    assert opencode_outcome is codex_outcome
    assert opencode_reason == codex_reason
    assert opencode_outcome is RunOutcome.inconclusive
    assert opencode_reason == _MISSING_VERDICT_REASON
    assert RunOutcome.passed not in {opencode_outcome, codex_outcome}
