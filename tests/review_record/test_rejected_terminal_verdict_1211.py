"""A refused terminal verdict leaves an honest record, not a silent success (#1211).

On #1209 Codex's approvals were both refused with
``approve_with_confirmed_blocker``. The rung never selected a mode, so
``selected_mode`` stayed ``None`` and every Review-mode gate read false:
``_publish`` skipped the deterministic record, the classifier read the
provider's 0 exit as ``passed``, and the trajectory recorded both refused calls
as ``ok=True`` completion claims. The PR got a failing approval check and no
review explaining it.

These tests reproduce that combination — a blocked approval, no accepted
terminal verdict, a provider that exited 0, and the terminal cascade position
(the decision is ``failure``, so no fallback rung replaces it) — and assert
that each surface tells the same story.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.agents.shared import AgentResult
from mergecraft.evidence.shadow import predict_verdict_protocol
from mergecraft.evidence.trajectory import build_trajectory_record
from mergecraft.main_outcome import _classify_outcome, _verdict_protocol_publish
from mergecraft.mcp.rpc import dispatch_mcp_rpc
from mergecraft.mcp.verdict import (
    REJECTION_APPROVE_CONFIRMED_BLOCKER,
    REJECTION_REQUEST_CHANGES_NO_FINDINGS,
    REJECTION_SCOPE_UNAVAILABLE,
    TerminalSubmissionRejectedError,
    submit_review_verdict_tool,
)
from mergecraft.run_outcome import RunOutcome
from tests.review_record.test_w15_deterministic_record import (
    _PREAMBLE_MARKER,
    _context,
    _sample_packet,
    _Scm,
)

if TYPE_CHECKING:
    from pathlib import Path

_APPROVE = {"verdict": "approve", "summary": "No blocking issues.", "findings": []}


def _blocker() -> Any:
    from mergecraft.analyzers.finding import make_finding

    return make_finding(
        tool="actionlint",
        rule_id="syntax-check",
        category="Security & Privacy",
        severity="Major",
        confidence="possible",
        message='"jobs" section is missing in workflow',
        path=".github/actions/bootstrap/action.yml",
        start_line=3,
        end_line=3,
        source="analyzer",
        evidence=['missing "on" and "jobs"'],
        fingerprint="issue-1211-blocker",
        introduced_by_pr="unknown",
    )


def _blocked_modeless_context(tmp_path: Path, scm: _Scm) -> Any:
    """A modeless run whose analyzer state carries one unverified Major blocker."""
    from mergecraft.mcp.tool_state import AnalyzerRunState

    ctx = _context(tmp_path, scm)
    ctx.run_id = 42211929360
    ctx.tool_state.analyzer_run = AnalyzerRunState(
        ran=True,
        findings=[_blocker().model_dump()],
        verified_ids=set(),
    )
    assert ctx.tool_state.selected_mode is None
    return ctx


async def _call(ctx: Any, spec: Any, arguments: dict[str, Any]) -> dict[str, Any]:
    return await dispatch_mcp_rpc(
        1,
        "tools/call",
        {"name": spec.name, "arguments": arguments},
        tools=[spec],
        by_name={spec.name: spec},
        tool_ctx=ctx,
        validators={},
    )


@pytest.mark.asyncio
async def test_rejected_terminal_call_is_refused_and_never_a_completion_claim(
    tmp_path: Path,
) -> None:
    ctx = _blocked_modeless_context(tmp_path, _Scm())
    spec = submit_review_verdict_tool(ctx)

    for _attempt in range(2):
        response = await _call(ctx, spec, dict(_APPROVE))
        # The agent still sees an ordinary tool error naming the rejection.
        assert response["result"]["isError"] is True
        assert REJECTION_APPROVE_CONFIRMED_BLOCKER in response["result"]["content"][0]["text"]

    rows = [call for call in ctx.tool_state.tool_calls if call.tool == "submit_review_verdict"]
    assert len(rows) == 2
    for row in rows:
        assert row.ok is False
        assert row.failure_class == "refused"
        assert REJECTION_APPROVE_CONFIRMED_BLOCKER in (row.error or "")

    record = build_trajectory_record(ctx.tool_state)
    assert record.completion_claims == []
    assert ctx.tool_state.terminal_submission is None
    assert ctx.tool_state.last_terminal_rejection == REJECTION_APPROVE_CONFIRMED_BLOCKER


@pytest.mark.asyncio
async def test_rejection_is_a_typed_refusal_that_still_reads_as_a_value_error(
    tmp_path: Path,
) -> None:
    from mergecraft.mcp.verdict import record_validated_terminal_submission

    ctx = _blocked_modeless_context(tmp_path, _Scm())
    with pytest.raises(TerminalSubmissionRejectedError, match=REJECTION_APPROVE_CONFIRMED_BLOCKER):
        record_validated_terminal_submission(ctx, dict(_APPROVE))
    assert issubclass(TerminalSubmissionRejectedError, ValueError)


@pytest.mark.parametrize("verdict_protocol", ["enforce", "shadow"])
@pytest.mark.parametrize("mode", [None, "Review"])
def test_provider_success_after_a_refused_verdict_is_not_a_passed_run(
    verdict_protocol: Any, mode: str | None
) -> None:
    outcome, reason = _classify_outcome(
        result=AgentResult(success=True, terminal_submission_received=False),
        setup_reason="",
        setup_policy="warn",
        prep_reason=None,
        mode=mode,
        verdict_protocol=verdict_protocol,
        terminal_rejection=REJECTION_APPROVE_CONFIRMED_BLOCKER,
    )

    assert outcome is RunOutcome.inconclusive
    assert reason is not None
    assert REJECTION_APPROVE_CONFIRMED_BLOCKER in reason
    assert "no model verdict was accepted" in reason


def test_a_rejection_followed_by_an_accepted_verdict_classifies_by_the_verdict() -> None:
    outcome, reason = _classify_outcome(
        result=AgentResult(success=True, terminal_submission_received=True),
        setup_reason="",
        setup_policy="warn",
        prep_reason=None,
        mode="Review",
        verdict_protocol="enforce",
        terminal_publication_receipt=True,
        terminal_rejection=REJECTION_APPROVE_CONFIRMED_BLOCKER,
    )

    assert (outcome, reason) == (RunOutcome.passed, None)


def test_a_modeless_run_with_no_terminal_attempt_is_unchanged() -> None:
    outcome, reason = _classify_outcome(
        result=AgentResult(success=True),
        setup_reason="",
        setup_policy="warn",
        prep_reason=None,
        mode=None,
        verdict_protocol="enforce",
    )

    assert (outcome, reason) == (RunOutcome.passed, None)


@pytest.mark.parametrize("mode", ["", "Review"])
def test_prediction_agrees_with_the_classifier_after_a_refused_verdict(mode: str) -> None:
    """The verdict diagnostic and the shadow comparison must not read ``approved``."""
    result = AgentResult(success=True, terminal_submission_received=False)
    prediction = predict_verdict_protocol(
        result, mode=mode, terminal_rejection=REJECTION_APPROVE_CONFIRMED_BLOCKER
    )
    actual, _reason = _classify_outcome(
        result=result,
        setup_reason="",
        setup_policy="warn",
        prep_reason=None,
        mode=mode or None,
        verdict_protocol="shadow",
        terminal_rejection=REJECTION_APPROVE_CONFIRMED_BLOCKER,
    )

    assert prediction.outcome is RunOutcome.inconclusive
    assert prediction.diagnostic == "provider_success_without_submission"
    # Shadow compares these two: equal means no false disagreement row.
    assert prediction.outcome is actual


def test_prediction_keeps_the_incremental_final_summary_exemption() -> None:
    prediction = predict_verdict_protocol(
        AgentResult(success=True),
        mode="IncrementalReview",
        final_summary_written=True,
        terminal_rejection=REJECTION_APPROVE_CONFIRMED_BLOCKER,
    )

    assert prediction.outcome is RunOutcome.passed


@pytest.mark.asyncio
async def test_scope_refused_terminal_call_is_refused_and_never_a_completion_claim(
    tmp_path: Path,
) -> None:
    ctx = _context(tmp_path, _Scm())
    ctx.tool_state.selected_mode = "Review"
    assert ctx.tool_state.terminal_submission is None

    response = await _call(ctx, submit_review_verdict_tool(ctx), dict(_APPROVE))

    assert response["result"]["isError"] is True
    (row,) = [call for call in ctx.tool_state.tool_calls if call.tool == "submit_review_verdict"]
    assert row.ok is False
    assert row.failure_class == "refused"
    assert "requires review scope" in (row.error or "")
    assert build_trajectory_record(ctx.tool_state).completion_claims == []
    assert ctx.tool_state.last_terminal_rejection == REJECTION_SCOPE_UNAVAILABLE


async def _publish_once(
    ctx: Any, packet: Any, monkeypatch: pytest.MonkeyPatch
) -> list[dict[str, Any]]:
    import mergecraft.main as main_mod
    import mergecraft.utils.step_summary as step_summary_mod

    checks: list[dict[str, Any]] = []

    async def _noop(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def _capture_checks(_ctx: Any, **kwargs: Any) -> None:
        checks.append(kwargs)

    monkeypatch.setattr(main_mod, "persist_learnings", _noop)
    monkeypatch.setattr(main_mod, "report_status_checks", _capture_checks)
    monkeypatch.setattr(main_mod, "resolve_prepared_run_packet", lambda *_a, **_k: packet)
    monkeypatch.setattr(step_summary_mod, "append_step_summary", lambda _body: None)

    result = AgentResult(success=True)
    outcome, reason = _classify_outcome(
        result=result,
        setup_reason="",
        setup_policy="warn",
        prep_reason=None,
        mode=ctx.tool_state.selected_mode,
        verdict_protocol="enforce",
        terminal_rejection=ctx.tool_state.last_terminal_rejection,
    )
    diagnostic = _verdict_protocol_publish(
        result=result,
        mode=ctx.tool_state.selected_mode,
        setup_reason="",
        setup_policy="warn",
        prep_reason=None,
        final_summary_written=False,
        terminal_verdict="enforce",
        terminal_rejection=ctx.tool_state.last_terminal_rejection,
    ).diagnostic
    await main_mod._publish(
        main_mod.RunContext(tool_context=ctx),
        outcome=outcome,
        failure_reason=reason,
        verdict_diagnostic=diagnostic,
        emit=False,
    )
    return checks


@pytest.mark.asyncio
async def test_modeless_rejected_run_publishes_an_explanatory_record_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MERGECRAFT_STICKY_ONLY_NEUTRAL", raising=False)
    scm = _Scm()
    ctx = _blocked_modeless_context(tmp_path, scm)
    spec = submit_review_verdict_tool(ctx)
    await _call(ctx, spec, dict(_APPROVE))
    await _call(ctx, spec, dict(_APPROVE))
    # Terminal cascade position: a ``failure`` decision is never handed on.
    packet = _sample_packet(
        findings=[_blocker()],
        verdict="failure",
        reason="1 blocking change finding",
    )

    checks = await _publish_once(ctx, packet, monkeypatch)

    assert len(scm.reviews) == 1
    body = scm.reviews[1]
    assert body.lstrip().startswith(_PREAMBLE_MARKER)
    assert f"**No agent verdict recorded — reason:** `{REJECTION_APPROVE_CONFIRMED_BLOCKER}`" in (
        body
    )
    assert "- **Decision:** `failure` — 1 blocking change finding" in body
    assert ".github/actions/bootstrap/action.yml:3" in body
    assert "- **Outcome:** `inconclusive`" in body
    assert "- **Verdict diagnostic:** `provider_success_without_submission`" in body
    # The completion check agrees: not a successful review.
    assert len(checks) == 1
    assert checks[0]["run_succeeded"] is False
    assert checks[0]["conclusion"] == "neutral"
    assert REJECTION_APPROVE_CONFIRMED_BLOCKER in str(checks[0]["failure_reason"])

    # A retry of the same Actions run updates that record; it never posts a second one.
    retry_ctx = _context(tmp_path, scm)
    retry_ctx.run_id = ctx.run_id
    retry_ctx.tool_state.last_terminal_rejection = REJECTION_APPROVE_CONFIRMED_BLOCKER
    await _publish_once(retry_ctx, packet, monkeypatch)

    assert scm.created == 1
    assert len(scm.reviews) == 1


@pytest.mark.asyncio
async def test_non_terminal_neutral_rung_stays_sticky_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#1078 is preserved: a neutral rung a fallback replaces posts no formal review."""
    monkeypatch.setenv("MERGECRAFT_STICKY_ONLY_NEUTRAL", "true")
    scm = _Scm()
    ctx = _blocked_modeless_context(tmp_path, scm)
    await _call(ctx, submit_review_verdict_tool(ctx), dict(_APPROVE))
    packet = _sample_packet(findings=[], verdict="neutral", reason="no verdict")

    await _publish_once(ctx, packet, monkeypatch)

    assert scm.created == 0
    assert not scm.reviews


@pytest.mark.asyncio
async def test_record_never_shows_approved_beside_a_refused_verdict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refused verdict on a clean diff: the decision is not a failure, so nothing
    else demotes the diagnostic; it must still not read ``approved``."""
    monkeypatch.delenv("MERGECRAFT_STICKY_ONLY_NEUTRAL", raising=False)
    scm = _Scm()
    ctx = _context(tmp_path, scm)
    ctx.run_id = 42211929360
    response = await _call(
        ctx,
        submit_review_verdict_tool(ctx),
        {"verdict": "request_changes", "summary": "Nits.", "findings": []},
    )
    assert response["result"]["isError"] is True
    assert ctx.tool_state.last_terminal_rejection == REJECTION_REQUEST_CHANGES_NO_FINDINGS
    packet = _sample_packet(findings=[], verdict="success", reason="approved")

    await _publish_once(ctx, packet, monkeypatch)

    body = scm.reviews[1]
    assert "- **Outcome:** `inconclusive`" in body
    assert "- **Verdict diagnostic:** `provider_success_without_submission`" in body
    assert "`approved`" not in body.split("- **Decision:**", 1)[0]
