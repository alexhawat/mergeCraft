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
from tests.support.tool_context import bind_github_client

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
    bind_github_client(ctx, github)
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
    bind_github_client(ctx, github)
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


@pytest.mark.asyncio
async def test_body_only_comment_is_not_recorded_as_request_changes(tmp_path: Path) -> None:
    """A plain COMMENT review must not fabricate a terminal ``request_changes``."""
    github = _RecordingGitHub()
    ctx = _ctx(tmp_path)
    bind_github_client(ctx, github)
    primary_repo_state(ctx.tool_state).checkout_sha = "abc123"

    result = await create_pull_request_review_tool(ctx).execute(
        {"pull_number": 7, "body": "Leaving a comment only."},
    )
    assert result.is_error is False
    assert ctx.tool_state.terminal_submission is None
    assert github.review_payloads[0]["event"] == "COMMENT"


@pytest.mark.asyncio
async def test_body_only_request_changes_is_rejected_without_findings(tmp_path: Path) -> None:
    """Body-only ``request_changes`` must not evade D9 with a fabricated finding."""
    github = _RecordingGitHub()
    ctx = _ctx(tmp_path)
    bind_github_client(ctx, github)
    primary_repo_state(ctx.tool_state).checkout_sha = "abc123"

    result = await create_pull_request_review_tool(ctx).execute(
        {
            "pull_number": 7,
            "body": "Please change things.",
            "request_changes": True,
        }
    )
    assert result.is_error is True
    assert _REASON_REQUEST_CHANGES_NO_FINDINGS in result.content[0]["text"]
    assert ctx.tool_state.terminal_submission is None
    assert github.review_payloads == []


@pytest.mark.asyncio
async def test_publication_cannot_flip_recorded_request_changes_to_approve(
    tmp_path: Path,
) -> None:
    """A recorded ``request_changes`` must not publish as ``approved=True``."""
    github = _RecordingGitHub()
    ctx = _ctx(tmp_path)
    bind_github_client(ctx, github)
    primary_repo_state(ctx.tool_state).checkout_sha = "abc123"

    recorded = await _submit_verdict(
        ctx,
        {
            "verdict": "request_changes",
            "summary": "One critical finding stands.",
            "findings": [_agent_blocker().model_dump()],
        },
    )
    assert recorded.is_error is False
    assert ctx.tool_state.terminal_submission is not None
    assert ctx.tool_state.terminal_submission.verdict == "request_changes"

    published = await create_pull_request_review_tool(ctx).execute(
        {"pull_number": 7, "body": "Actually LGTM.", "approved": True},
    )
    assert published.is_error is True
    assert "does not match recorded terminal verdict" in published.content[0]["text"]
    assert github.review_payloads == []


@pytest.mark.asyncio
async def test_publication_revalidates_stale_approve_after_failed_gate(
    tmp_path: Path,
) -> None:
    """An earlier ``approve`` must not publish after a later failed required gate."""
    github = _RecordingGitHub()
    ctx = _ctx(
        tmp_path,
        static_checks=[StaticCheckConfig(name="lint", command="python -c 'raise SystemExit(1)'")],
        static_checks_enabled=True,
    )
    bind_github_client(ctx, github)
    primary_repo_state(ctx.tool_state).checkout_sha = "abc123"

    first = await _submit_verdict(ctx, _approve_payload())
    assert first.is_error is False
    checks = await run_static_checks_tool(ctx).execute({})
    assert checks.is_error is False
    assert any(row.get("status") == "failed" for row in ctx.tool_state.static_checks)

    published = await create_pull_request_review_tool(ctx).execute(
        {"pull_number": 7, "body": "Looks good.", "approved": True},
    )
    assert published.is_error is True
    assert _REASON_APPROVE_FAILED_GATE in published.content[0]["text"]
    assert github.review_payloads == []


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


# ---------------------------------------------------------------------------
# W14.5 / #263 — approve fails open on unverified blocking analyzer findings
# ---------------------------------------------------------------------------
#
# ``validate_submission``'s approve branch walks only
# ``_confirmed_findings_from_state``, which returns analyzer findings whose
# fingerprint is in ``verified_ids``. A Critical the analyzers found and the
# agent never dispatched a verifier for is therefore invisible to the gate,
# and ``approve`` is accepted. D12: reject when a blocking-severity finding
# exists in ``analyzer_run.findings`` that is neither verified nor withdrawn.
#
# Rejection-reason contract chosen for W19: reuse the existing
# ``REJECTION_APPROVE_CONFIRMED_BLOCKER`` ("approve_with_confirmed_blocker").
# The string is pinned above at ``_REASON_APPROVE_CONFIRMED_BLOCKER``, but
# only for the *verified* case; reusing it for the unverified case leaves
# every existing assertion intact, so the plan's stated preference for one
# reason holds. No new constant is required.

_UNVERIFIED_BLOCKER_FINGERPRINTS = {
    "Critical": "w14-unverified-critical",
    "Major": "w14-unverified-major",
}


def _unverified_blocker(severity: str) -> Finding:
    """A blocking-severity analyzer finding that no verifier ever confirmed."""
    return make_finding(
        tool="bandit",
        rule_id=f"B105-{severity.lower()}",
        category="Security & Privacy",
        severity=severity,
        confidence="certain",
        message="Hardcoded credential committed in the diff.",
        path="src/app.py",
        start_line=30,
        end_line=30,
        source="analyzer",
        evidence=["PASSWORD = 'hunter2'"],
        fingerprint=_UNVERIFIED_BLOCKER_FINGERPRINTS[severity],
        introduced_by_pr="true",
    )


def _nonblocking_analyzer_finding() -> Finding:
    return make_finding(
        tool="ruff",
        rule_id="E501",
        category="Maintainability & Code Quality",
        severity="Minor",
        confidence="likely",
        message="Line too long.",
        path="src/app.py",
        start_line=3,
        end_line=3,
        source="analyzer",
        fingerprint="w14-unverified-minor",
        introduced_by_pr="true",
    )


def _state_with_analyzer_findings(
    tool_state: Any,
    findings: list[Finding],
    *,
    verified: set[str] | None = None,
    withdrawn: frozenset[str] | None = None,
) -> Any:
    """Seed ``AnalyzerRunState`` and derive the validator's consultation object.

    ``confirmed_findings`` is deliberately left to the derivation in
    ``_confirmed_findings_from_state`` rather than injected, so an unverified
    finding really is absent from the confirmed set — injecting it would test
    the wrong seam.
    """
    tool_state.analyzer_run = AnalyzerRunState(
        ran=True,
        findings=[finding.model_dump() for finding in findings],
        verified_ids=set(verified or set()),
    )
    state = _validation_state(tool_state, withdrawn_fingerprints=withdrawn)
    state.confirmed_findings = _confirmed_findings(state)
    return state


def _confirmed_findings(state: Any) -> list[Any]:
    from mergecraft.mcp.verdict import _confirmed_findings_from_state

    return _confirmed_findings_from_state(state)


@pytest.mark.parametrize("severity", ["Critical", "Major"])
def test_approve_is_rejected_for_an_unverified_blocking_analyzer_finding(
    tmp_path: Path,
    severity: str,
) -> None:
    """#263 / D12 — an unverified blocker must reject ``approve``.

    The finding is in ``analyzer_run.findings`` with an empty ``verified_ids``,
    which is exactly the state a run reaches when the agent calls
    ``run_analyzers`` and then skips verification.
    """
    ctx = _ctx(tmp_path)
    blocker = _unverified_blocker(severity)
    state = _state_with_analyzer_findings(ctx.tool_state, [blocker])
    # Precondition: the finding is genuinely *not* in the confirmed set, so
    # the rejection cannot come from the pre-existing verified-blocker path.
    assert state.confirmed_findings == []

    validation = _validate(_approve_payload(), state=state)
    _assert_typed_rejection(validation, _REASON_APPROVE_CONFIRMED_BLOCKER)


@pytest.mark.asyncio
async def test_live_submit_approve_is_rejected_for_an_unverified_blocker(
    tmp_path: Path,
) -> None:
    """Consumer half: the tool — not just the validator — must fail closed.

    ``validation_state_from_tool_context`` is the only state builder the live
    ``submit_review_verdict`` path uses, and it hardcodes
    ``withdrawn_fingerprints=set()``. Driving the tool proves the fix reaches
    the surface the reviewing agent actually calls, and that no
    ``TerminalSubmission`` is recorded.
    """
    from mergecraft.mcp.verdict import (
        submit_review_verdict_tool,
        validation_state_from_tool_context,
    )

    ctx = _ctx(tmp_path)
    blocker = _unverified_blocker("Critical")
    ctx.tool_state.analyzer_run = AnalyzerRunState(
        ran=True,
        findings=[blocker.model_dump()],
        verified_ids=set(),
    )
    derived = validation_state_from_tool_context(ctx)
    assert derived.confirmed_findings == []

    _assert_typed_rejection(
        _validate(_approve_payload(), state=derived),
        _REASON_APPROVE_CONFIRMED_BLOCKER,
    )
    verdict = await submit_review_verdict_tool(ctx).execute(_approve_payload())
    assert verdict.is_error is True
    assert _REASON_APPROVE_CONFIRMED_BLOCKER in verdict.content[0]["text"]
    assert ctx.tool_state.terminal_submission is None


@pytest.mark.asyncio
async def test_approve_recorded_before_analyzers_becomes_unusable(tmp_path: Path) -> None:
    """An ``approve`` banked before ``run_analyzers`` must not survive the findings.

    Same shape as the failed-static-check revalidation above: the ordering
    the agent chooses must not decide whether the gate applies.
    """
    ctx = _ctx(tmp_path)
    first = await _submit_verdict(ctx, _approve_payload())
    assert first.is_error is False

    blocker = _unverified_blocker("Critical")
    ctx.tool_state.analyzer_run = AnalyzerRunState(
        ran=True,
        findings=[blocker.model_dump()],
        verified_ids=set(),
    )

    finalized = await finalize_agent_result(_run_ctx(ctx), AgentResult(success=True))
    assert finalized.terminal_submission_received is False
    assert finalized.diagnostics.get("rejection_reason") == _REASON_APPROVE_CONFIRMED_BLOCKER
    outcome, _reason = _classify(finalized, mode="Review")
    assert outcome is RunOutcome.inconclusive


def test_approve_survives_a_non_blocking_unverified_analyzer_finding(tmp_path: Path) -> None:
    """Green guard: D12 blocks on blocking severities only.

    Without this arm the fix could degrade into "approve is always rejected
    once the analyzers found anything", which would make every clean review
    inconclusive.
    """
    ctx = _ctx(tmp_path)
    state = _state_with_analyzer_findings(ctx.tool_state, [_nonblocking_analyzer_finding()])
    validation = _validate(_approve_payload(), state=state)

    assert isinstance(validation, _validation_type())
    assert validation.accepted is True
    assert validation.rejection_reason is None


def test_approve_survives_an_empty_analyzer_run(tmp_path: Path) -> None:
    """Green guard: analyzers ran and found nothing ⇒ approve is legitimate."""
    ctx = _ctx(tmp_path)
    state = _state_with_analyzer_findings(ctx.tool_state, [])
    validation = _validate(_approve_payload(), state=state)

    assert validation.accepted is True
    assert validation.rejection_reason is None


def test_approve_survives_a_withdrawn_blocking_finding(tmp_path: Path) -> None:
    """Green guard (D12's escape hatch): a withdrawn blocker must not block.

    Green today because the approve branch ignores ``analyzer_run.findings``
    entirely. After W19 it is load-bearing: the walk must honour
    ``state.withdrawn_fingerprints``, which is the seam the withdrawn-findings
    memory feeds.
    """
    ctx = _ctx(tmp_path)
    blocker = _unverified_blocker("Critical")
    state = _state_with_analyzer_findings(
        ctx.tool_state,
        [blocker],
        withdrawn=frozenset({blocker.fingerprint}),
    )
    assert blocker.fingerprint in state.withdrawn_fingerprints

    validation = _validate(_approve_payload(), state=state)
    assert validation.accepted is True
    assert validation.rejection_reason is None


def test_request_changes_is_unaffected_by_an_unverified_blocker(tmp_path: Path) -> None:
    """Green guard: the new walk belongs to the approve branch only."""
    ctx = _ctx(tmp_path)
    state = _state_with_analyzer_findings(ctx.tool_state, [_unverified_blocker("Critical")])
    validation = _validate(
        {
            "verdict": "request_changes",
            "summary": "One critical finding stands.",
            "findings": [_agent_blocker().model_dump()],
        },
        state=state,
    )

    assert validation.accepted is True
    assert validation.rejection_reason is None


def test_a_pre_existing_blocker_is_downgraded_before_the_gate(tmp_path: Path) -> None:
    """Green guard: ``apply_causality_policy`` runs first, as the verified path does.

    A Critical marked ``introduced_by_pr: "false"`` becomes ``Minor``, so it
    must not reject an approve. Skipping the policy in the new walk would
    make every pre-existing repo-wide Critical un-approvable.
    """
    from mergecraft.findings.causality import apply_causality_policy

    pre_existing = make_finding(
        tool="bandit",
        rule_id="B105-preexisting",
        category="Security & Privacy",
        severity="Critical",
        confidence="certain",
        message="Hardcoded credential outside the diff.",
        path="src/legacy.py",
        start_line=9,
        end_line=9,
        source="analyzer",
        fingerprint="w14-preexisting-critical",
        introduced_by_pr="false",
    )
    assert apply_causality_policy(pre_existing).severity == "Minor"

    ctx = _ctx(tmp_path)
    state = _state_with_analyzer_findings(ctx.tool_state, [pre_existing])
    validation = _validate(_approve_payload(), state=state)

    assert validation.accepted is True
    assert validation.rejection_reason is None


# ---------------------------------------------------------------------------
# C1 — approve must stay reachable under the default configuration
# ---------------------------------------------------------------------------
#
# Under the default ``base_comparison: "diff"`` no base run happens, so
# ``annotate_introduced_by_pr`` leaves every diff-scoped finding
# ``introduced_by_pr: "unknown"`` and ``apply_causality_policy`` (which only
# downgrades ``"false"``) leaves the severity alone. A single ruff ``error`` maps
# to Major, so the #263 unverified-blocker walk rejected every approve for the
# rest of the run. Two things must hold: an unattributed finding cannot block
# approve, and each release valve (drop, downgrade) actually clears a finding
# that *is* attributed.


def _default_config_ruff_major() -> Finding:
    """What a ruff ``error`` on a changed file looks like under default config."""
    return make_finding(
        tool="ruff",
        rule_id="F821",
        category="Maintainability & Code Quality",
        severity="Major",
        confidence="certain",
        message="Undefined name `widget`.",
        path="src/app.py",
        start_line=14,
        end_line=14,
        source="analyzer",
        fingerprint="c1-ruff-major-unknown",
    )


def test_the_default_config_ruff_major_has_unknown_provenance() -> None:
    """Evidence for the arm below: the row really is unattributed, not downgraded."""
    from mergecraft.findings.causality import apply_causality_policy

    finding = _default_config_ruff_major()
    assert finding.introduced_by_pr == "unknown"
    assert apply_causality_policy(finding).severity == "Major"


@pytest.mark.parametrize("severity", ["Critical", "Major"])
def test_approve_survives_a_blocker_not_attributed_to_the_pr(
    tmp_path: Path,
    severity: str,
) -> None:
    """An unverified blocker with unknown provenance must not reject approve.

    #263's intent is that a finding this PR introduced cannot be approved away
    unexamined. A finding nobody attributed to the PR is not that, and under
    default config every diff-scoped finding is in that state.
    """
    unattributed = make_finding(
        tool="bandit",
        rule_id=f"B105-{severity.lower()}-unknown",
        category="Security & Privacy",
        severity=severity,
        confidence="certain",
        message="Hardcoded credential.",
        path="src/app.py",
        start_line=30,
        end_line=30,
        source="analyzer",
        fingerprint=f"c1-unknown-{severity.lower()}",
    )
    assert unattributed.introduced_by_pr == "unknown"

    ctx = _ctx(tmp_path)
    state = _state_with_analyzer_findings(ctx.tool_state, [unattributed])
    validation = _validate(_approve_payload(), state=state)

    assert validation.accepted is True
    assert validation.rejection_reason is None


@pytest.mark.asyncio
async def test_a_single_ruff_major_does_not_lock_out_approve(tmp_path: Path) -> None:
    """The reported symptom, end to end at the tool surface."""
    from mergecraft.mcp.verdict import submit_review_verdict_tool

    ctx = _ctx(tmp_path)
    ctx.tool_state.analyzer_run = AnalyzerRunState(
        ran=True,
        findings=[_default_config_ruff_major().model_dump()],
        verified_ids=set(),
    )

    verdict = await submit_review_verdict_tool(ctx).execute(_approve_payload())

    assert verdict.is_error is False, verdict.content[0]["text"]
    assert ctx.tool_state.terminal_submission is not None


def test_a_finding_with_no_severity_blocks_approve(tmp_path: Path) -> None:
    """Fail closed on a row the gate cannot read.

    ``_coerce_confirmed_finding`` returns ``None`` for a row with no severity,
    and skipping it silently approves over a finding nobody could grade.
    """
    ctx = _ctx(tmp_path)
    ctx.tool_state.analyzer_run = AnalyzerRunState(
        ran=True,
        findings=[
            {"fingerprint": "c1-malformed", "path": "src/app.py", "introduced_by_pr": "true"}
        ],
        verified_ids=set(),
    )
    state = _validation_state(ctx.tool_state)

    _assert_typed_rejection(
        _validate(_approve_payload(), state=state),
        _REASON_APPROVE_CONFIRMED_BLOCKER,
    )


@pytest.mark.asyncio
async def test_a_dropped_blocker_releases_approve(tmp_path: Path) -> None:
    """Valve 1: ``record_finding_verdict(drop)`` must clear the analyzer row.

    The drop is written to the learnings file's withdrawn section, but the
    validation state hardcoded ``withdrawn_fingerprints=set()`` and never read
    it, so the row kept rejecting approve for the rest of the run.
    """
    from mergecraft.mcp.verdict import (
        submit_review_verdict_tool,
        validation_state_from_tool_context,
    )
    from mergecraft.mcp.verification import record_finding_verdict_tool

    ctx = _ctx(tmp_path)
    blocker = _unverified_blocker("Critical")
    ctx.tool_state.analyzer_run = AnalyzerRunState(
        ran=True,
        findings=[blocker.model_dump()],
        verified_ids=set(),
    )
    _assert_typed_rejection(
        _validate(_approve_payload(), state=validation_state_from_tool_context(ctx)),
        _REASON_APPROVE_CONFIRMED_BLOCKER,
    )

    dropped = await record_finding_verdict_tool(ctx).execute(
        {
            "fingerprint": blocker.fingerprint,
            "verdict": "drop",
            "reason": "The credential is a test fixture, not a live secret.",
        }
    )
    assert dropped.is_error is False, dropped.content[0]["text"]
    assert json.loads(dropped.content[0]["text"])["recordedWithdrawn"] is True

    derived = validation_state_from_tool_context(ctx)
    assert blocker.fingerprint in derived.withdrawn_fingerprints
    assert _validate(_approve_payload(), state=derived).accepted is True

    verdict = await submit_review_verdict_tool(ctx).execute(_approve_payload())
    assert verdict.is_error is False, verdict.content[0]["text"]


@pytest.mark.asyncio
async def test_a_downgraded_blocker_releases_approve(tmp_path: Path) -> None:
    """Valve 2: a downgrade to a non-blocking severity must rewrite the row.

    Discarding the fingerprint from ``verified_ids`` while leaving the original
    Critical in ``analyzer_run.findings`` made the downgrade actively worse than
    doing nothing — the row came back as an unverified blocker.
    """
    from mergecraft.mcp.verdict import (
        submit_review_verdict_tool,
        validation_state_from_tool_context,
    )
    from mergecraft.mcp.verification import record_finding_verdict_tool

    ctx = _ctx(tmp_path)
    blocker = _unverified_blocker("Critical")
    ctx.tool_state.analyzer_run = AnalyzerRunState(
        ran=True,
        findings=[blocker.model_dump()],
        verified_ids=set(),
    )

    downgraded = await record_finding_verdict_tool(ctx).execute(
        {
            "fingerprint": blocker.fingerprint,
            "verdict": "downgrade",
            "reason": "Reachable only from a test helper, so it is a Minor.",
            "new_severity": "Minor",
        }
    )
    assert downgraded.is_error is False, downgraded.content[0]["text"]

    rows = ctx.tool_state.analyzer_run.findings
    assert [row.get("severity") for row in rows] == ["Minor"]
    assert _validate(_approve_payload(), state=validation_state_from_tool_context(ctx)).accepted

    verdict = await submit_review_verdict_tool(ctx).execute(_approve_payload())
    assert verdict.is_error is False, verdict.content[0]["text"]


@pytest.mark.asyncio
async def test_an_attributed_unverified_blocker_still_blocks_approve(tmp_path: Path) -> None:
    """Green guard: #263's real intent survives every valve above."""
    from mergecraft.mcp.verdict import submit_review_verdict_tool

    ctx = _ctx(tmp_path)
    ctx.tool_state.analyzer_run = AnalyzerRunState(
        ran=True,
        findings=[_unverified_blocker("Major").model_dump()],
        verified_ids=set(),
    )

    verdict = await submit_review_verdict_tool(ctx).execute(_approve_payload())

    assert verdict.is_error is True
    assert _REASON_APPROVE_CONFIRMED_BLOCKER in verdict.content[0]["text"]
    assert ctx.tool_state.terminal_submission is None
