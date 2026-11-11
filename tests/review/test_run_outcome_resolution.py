"""Run-level gates are resolved before the formal review is published.

Every case drives the real ``mergecraft.main._finalize`` with a driver-shaped
result (what ``claude`` / ``codex`` / ``opencode`` return: already passed
through ``finalize_agent_result``), the real publisher and the recording GitHub
fake; only ``_publish`` (sticky record, packet emission, status checks) and the
sink scan are replaced, unless a case says otherwise. The offline cases drive
the real ``run_offline_agent_review`` with a stub harness.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

import mergecraft.main as main_mod
from mergecraft.agents.post_run import finalize_agent_result
from mergecraft.agents.shared import AgentResult
from mergecraft.analyzers.finding import make_finding
from mergecraft.config.settings import RepoSettings
from mergecraft.mcp.tool_state import record_reviewer_dispatch_run
from mergecraft.review.roster_execution import RosterExecutionSummary, apply_roster_failure
from mergecraft.run_outcome import RunOutcome, cli_exit_code_for_review
from mergecraft.utils.run_bounds import BudgetExhausted, BudgetTracker, resolve_run_bounds
from tests.support.publication import (
    RecordingReviewGitHub,
    inline_fingerprints,
    publication_ctx,
    run_ctx_for,
    submit_verdict,
)

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext


async def _driver_result(ctx: ToolContext, **overrides: Any) -> AgentResult:
    """Return what a real driver hands ``_finalize``: an already-finalized result."""
    result = await finalize_agent_result(run_ctx_for(ctx), AgentResult(success=True, output="ok"))
    return replace(result, **overrides) if overrides else result


def _approving_ctx(tmp_path: Path, github: RecordingReviewGitHub) -> ToolContext:
    ctx = publication_ctx(tmp_path, github=github, trust_tier="trusted")
    ctx.pr_approve_enabled = True
    ctx.authority_trust = "trusted"
    return ctx


async def _finalize(
    ctx: ToolContext,
    result: AgentResult,
    monkeypatch: pytest.MonkeyPatch,
    *,
    budget_exhaustion: BudgetExhausted | None = None,
    budget_tracker: BudgetTracker | None = None,
    sink: str | None = None,
    structured_output_error: str | None = None,
) -> main_mod.MainResult:
    async def _record(_ctx: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(main_mod, "_publish", _record)
    monkeypatch.setattr(main_mod, "_scan_sinks_after_run", lambda *_a, **_k: sink)
    run = main_mod.RunContext(
        settings=RepoSettings(),
        tool_context=ctx,
        tool_state=ctx.tool_state,
        run_ctx=run_ctx_for(ctx),
        tmpdir=ctx.tmpdir,
    )
    run.budget_exhaustion = budget_exhaustion
    run.budget_tracker = budget_tracker
    run.structured_output_error = structured_output_error
    return await main_mod._finalize(run, result)


def _events(github: RecordingReviewGitHub) -> list[str]:
    return [str(payload.get("event")) for payload in github.review_payloads]


def _tool_call_tracker() -> BudgetTracker:
    tracker = BudgetTracker(resolve_run_bounds(env={}))
    tracker.last_exhausted = BudgetExhausted("tool_call", "tool-call budget exhausted")
    return tracker


async def _raise(*_args: Any, **_kwargs: Any) -> Any:
    msg = "terminal fields could not be read"
    raise RuntimeError(msg)


_GATES = ("token_budget", "tool_call_budget", "prep", "coverage", "sink", "roster", "finalize")


async def _run_gate(
    gate: str, ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
) -> main_mod.MainResult:
    result = await _driver_result(ctx)
    kwargs: dict[str, Any] = {}
    if gate == "token_budget":
        kwargs["budget_exhaustion"] = BudgetExhausted("token", "token budget exhausted")
    elif gate == "tool_call_budget":
        kwargs["budget_tracker"] = _tool_call_tracker()
    elif gate == "prep":

        async def _prep(_tool_context: Any) -> str:
            return "dependency installation failed: npm ci exited 1"

        monkeypatch.setattr(main_mod, "_prep_failure_reason", _prep)
    elif gate == "coverage":
        monkeypatch.setattr(
            main_mod, "_coverage_gate_reason", lambda *_a: "changed-line coverage incomplete"
        )
    elif gate == "sink":
        kwargs["sink"] = "credential material found in local sink(s) after the run: x"
    elif gate == "roster":
        result = apply_roster_failure(
            result,
            RosterExecutionSummary(
                hard_error="secondary reviewer 'reviewer2' timed out after 900.0s",
                dispatched_agent_ids=(),
            ),
        )
    elif gate == "finalize":
        monkeypatch.setattr(main_mod, "finalize_agent_result", _raise)
    return await _finalize(ctx, result, monkeypatch, **kwargs)


@pytest.mark.parametrize("gate", _GATES)
@pytest.mark.parametrize("verdict", ["approve", "request_changes"])
async def test_a_run_that_does_not_pass_never_posts_an_approval(
    gate: str, verdict: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    github = RecordingReviewGitHub()
    ctx = _approving_ctx(tmp_path, github)
    findings = (
        [{"path": "src/app.py", "line": 3, "severity": "Major", "body": "Unchecked index."}]
        if verdict == "request_changes"
        else []
    )
    await submit_verdict(ctx, verdict, findings)  # type: ignore[arg-type]

    outcome = await _run_gate(gate, ctx, monkeypatch)

    assert outcome.outcome is not RunOutcome.passed
    assert "APPROVE" not in _events(github)
    assert github.dismissals == []


async def test_a_passing_approve_is_posted_as_an_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    github = RecordingReviewGitHub()
    ctx = _approving_ctx(tmp_path, github)
    await submit_verdict(ctx, "approve", [])

    outcome = await _finalize(ctx, await _driver_result(ctx), monkeypatch)

    assert outcome.outcome is RunOutcome.passed
    assert _events(github) == ["APPROVE"]


async def test_the_withheld_approval_is_named_in_the_run_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.support.finalize_harness import run_finalize

    github = RecordingReviewGitHub()
    ctx = _approving_ctx(tmp_path, github)
    await submit_verdict(ctx, "approve", [])
    monkeypatch.setattr(
        main_mod, "_coverage_gate_reason", lambda *_a: "changed-line coverage incomplete"
    )

    record = await run_finalize(
        ctx, monkeypatch=monkeypatch, agent_result=await _driver_result(ctx), real_publish=True
    )

    assert record.outcome is RunOutcome.inconclusive
    assert _events(github) == ["COMMENT"]
    assert "**Approval withheld:**" in "\n".join(github.review_bodies.values())


async def test_an_approval_posted_mid_run_is_dismissed_when_the_run_does_not_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.mcp.review import publish_pull_request_review

    github = RecordingReviewGitHub()
    ctx = _approving_ctx(tmp_path, github)
    await submit_verdict(ctx, "approve", [])
    await publish_pull_request_review(ctx)
    assert _events(github) == ["APPROVE"]

    outcome = await _finalize(
        ctx,
        await _driver_result(ctx),
        monkeypatch,
        budget_exhaustion=BudgetExhausted("token", "token budget exhausted"),
    )

    assert outcome.outcome is RunOutcome.inconclusive
    assert _events(github) == ["APPROVE"]
    assert len(github.dismissals) == 1
    path, kwargs = github.dismissals[0]
    assert path.endswith("/pulls/7/reviews/1/dismissals")
    assert "token budget exhausted" in kwargs["json"]["message"]


# --------------------------------------------------------------------- finalize failure


async def test_a_finalize_failure_with_a_driver_result_is_inconclusive_and_posts_no_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    github = RecordingReviewGitHub()
    ctx = _approving_ctx(tmp_path, github)
    await submit_verdict(ctx, "approve", [])
    result = await _driver_result(ctx)
    assert result.terminal_submission_received is True
    monkeypatch.setattr(main_mod, "finalize_agent_result", _raise)

    outcome = await _finalize(ctx, result, monkeypatch)

    assert outcome.outcome is RunOutcome.inconclusive
    assert outcome.error is not None
    assert "finalize_failed: RuntimeError" in outcome.error
    assert github.review_payloads == []


# ---------------------------------------------------------------- secondary findings


def _secondary_row(severity: str) -> dict[str, Any]:
    finding = make_finding(
        tool="agent",
        rule_id="agent:draft",
        category="Functional Correctness",
        severity=severity,
        confidence="likely",
        message="Unescaped input reaches the query builder.",
        path="src/app.py",
        start_line=3,
        end_line=3,
        source="agent",
    )
    return finding.model_dump(mode="json")


def _record_secondary(ctx: ToolContext, severity: str) -> dict[str, Any]:
    """Leave what ``_dispatch_reviewer`` leaves for a secondary that finished."""
    row = _secondary_row(severity)
    ctx.tool_state.agent_findings.append(row)
    record_reviewer_dispatch_run(
        ctx.tool_state, agent_id="reviewer2", findings=[row], model_slug="codex/gpt-5.6"
    )
    return row


async def test_a_blocking_secondary_finding_turns_the_review_into_request_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.evidence.run_packet import resolve_prepared_run_packet

    github = RecordingReviewGitHub()
    ctx = _approving_ctx(tmp_path, github)
    await submit_verdict(ctx, "approve", [])
    result = await _driver_result(ctx)
    row = _record_secondary(ctx, "Critical")

    outcome = await _finalize(ctx, result, monkeypatch)

    assert _events(github) == ["REQUEST_CHANGES"]
    assert row["fingerprint"] in inline_fingerprints(github.review_payloads[0])
    assert outcome.outcome is RunOutcome.passed
    packet = resolve_prepared_run_packet(ctx, run_succeeded=True)
    assert packet is not None
    assert packet.decision is not None
    assert packet.decision.verdict == "failure"


async def test_a_minor_secondary_finding_is_published_inline_beside_the_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    github = RecordingReviewGitHub()
    ctx = _approving_ctx(tmp_path, github)
    await submit_verdict(ctx, "approve", [])
    result = await _driver_result(ctx)
    row = _record_secondary(ctx, "Minor")

    await _finalize(ctx, result, monkeypatch)

    assert _events(github) == ["APPROVE"]
    assert row["fingerprint"] in inline_fingerprints(github.review_payloads[0])


# ------------------------------------------------------------------- roster policy


@pytest.mark.parametrize(
    ("infra", "expected"),
    [(False, RunOutcome.inconclusive), (True, RunOutcome.infra_error)],
)
async def test_a_required_reviewer_failure_outranks_an_accepted_primary_verdict(
    infra: bool, expected: RunOutcome, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    github = RecordingReviewGitHub()
    ctx = _approving_ctx(tmp_path, github)
    await submit_verdict(ctx, "approve", [])
    result = apply_roster_failure(
        await _driver_result(ctx),
        RosterExecutionSummary(
            hard_error="secondary reviewer 'reviewer2' timed out after 900.0s",
            dispatched_agent_ids=(),
            infra_reason="codex login expired" if infra else None,
        ),
    )

    outcome = await _finalize(ctx, result, monkeypatch)

    assert outcome.outcome is expected
    assert "APPROVE" not in _events(github)


# ------------------------------------------------------------------ offline parity


PRIMARY = "anthropic/claude-sonnet"


@pytest.fixture
def offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    from mergecraft.analyzers.finding import FindingsPayload
    from mergecraft.review import offline_agent
    from mergecraft.utils.agent_resolve import CredentialStatus
    from mergecraft.utils.offline_diff import DiffMaterialization

    seen: dict[str, Any] = {"result": AgentResult(success=True), "secondary": None}
    monkeypatch.delenv("MERGECRAFT_MODEL", raising=False)
    monkeypatch.setattr(
        offline_agent, "load_repo_settings", lambda **_: RepoSettings(models=[PRIMARY])
    )
    monkeypatch.setattr(
        offline_agent,
        "start_mcp_http_server",
        lambda *a, **kw: ("http://localhost:1/mcp", lambda: None),
    )
    monkeypatch.setattr(offline_agent, "install_bundled_skills", lambda **_: None)
    monkeypatch.setattr(offline_agent, "_emit_offline_packet", lambda *a, **kw: None)
    monkeypatch.setattr(
        offline_agent,
        "credential_status_for_slug",
        lambda *a, **kw: CredentialStatus(available=True, source=None, looked_for=()),
    )
    real_tracker = offline_agent.BudgetTracker

    def _tracker(bounds: Any) -> BudgetTracker:
        seen["tracker"] = real_tracker(bounds)
        return seen["tracker"]

    monkeypatch.setattr(offline_agent, "BudgetTracker", _tracker)

    class Agent:
        name = "claude"

        async def install(self) -> None:
            return None

        async def run(self, ctx: Any) -> AgentResult:
            ctx.tool_state.output = seen.get(
                "output", FindingsPayload(findings=[]).model_dump_json()
            )
            if seen.get("exhaust"):
                # The MCP ``tools/call`` handler records this and answers with an error.
                seen["tracker"].last_exhausted = BudgetExhausted(
                    "tool_call", "tool-call budget exhausted"
                )
            return seen["result"]

    monkeypatch.setattr(offline_agent, "resolve_runtime_agent", lambda **_: Agent())

    async def _roster(**kwargs: Any) -> RosterExecutionSummary:
        tool_state = kwargs["tool_context"].tool_state
        if seen["secondary"] is not None:
            tool_state.agent_findings.append(seen["secondary"])
            record_reviewer_dispatch_run(
                tool_state, agent_id="reviewer2", findings=[seen["secondary"]]
            )
        return seen.get("roster") or RosterExecutionSummary(
            hard_error=None, dispatched_agent_ids=()
        )

    monkeypatch.setattr("mergecraft.review.roster_execution.run_pending_roster_reviewers", _roster)
    patch = tmp_path / "diff.patch"
    patch.write_text("diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -1 +1 @@\n-a\n+b\n")
    seen["materialization"] = DiffMaterialization(
        path=patch, base_ref="HEAD", line_count=6, empty=False
    )
    return seen


async def _run_offline(offline: dict[str, Any], tmp_path: Path) -> Any:
    from mergecraft.analyzers.finding import findings_output_schema
    from mergecraft.review import offline_agent

    return await offline_agent.run_offline_agent_review(
        cwd=tmp_path,
        materialization=offline["materialization"],
        prompt="review",
        model=None,
        tmpdir=tmp_path,
        # What ``mergecraft review`` always passes: the findings schema.
        output_schema=findings_output_schema(),
    )


_TIMEOUT = "secondary reviewer 'reviewer2' timed out after 900.0s"
_PARITY_CASES: dict[str, dict[str, Any]] = {
    "clean": {},
    "tool_call_budget": {"exhaust": True},
    "roster_timeout": {
        "roster": RosterExecutionSummary(hard_error=_TIMEOUT, dispatched_agent_ids=())
    },
    "roster_infra": {
        "roster": RosterExecutionSummary(
            hard_error=_TIMEOUT, dispatched_agent_ids=(), infra_reason="codex login expired"
        )
    },
    "driver_failed": {"failed": True},
    # The model finished without calling ``set_output`` (#1293).
    "missing_output": {"output": None},
}


@pytest.mark.parametrize("case", sorted(_PARITY_CASES))
async def test_the_same_inputs_resolve_to_the_same_outcome_online_and_offline(
    case: str, offline: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _PARITY_CASES[case]
    failed = AgentResult(success=False, error="provider exited 1", metadata={"retryable": False})

    # Offline: the stub harness either submits (received) or fails.
    offline["exhaust"] = spec.get("exhaust", False)
    offline["roster"] = spec.get("roster")
    if "output" in spec:
        offline["output"] = spec["output"]
    offline["result"] = (
        failed
        if spec.get("failed")
        else AgentResult(success=True, terminal_submission_received=True)
    )
    (tmp_path / "offline").mkdir()
    offline_out = await _run_offline(offline, tmp_path / "offline")

    # Action: the same state through ``_finalize``.
    github = RecordingReviewGitHub()
    (tmp_path / "online").mkdir()
    ctx = _approving_ctx(tmp_path / "online", github)
    if spec.get("failed"):
        result = await finalize_agent_result(run_ctx_for(ctx), failed)
    else:
        await submit_verdict(ctx, "approve", [])
        result = await _driver_result(ctx)
    if spec.get("roster") is not None:
        result = apply_roster_failure(result, spec["roster"])
    if "output" in spec:
        # The Action's own schema check, on the same missing payload.
        run = main_mod.RunContext(
            tool_state=ctx.tool_state, tool_context=ctx, output_schema={"type": "object"}
        )
        ctx.tool_state.output = spec["output"]
        result = main_mod._promote_and_finalize_agent_result(run, None, result)
    else:
        run = None
    online_out = await _finalize(
        ctx,
        result,
        monkeypatch,
        budget_tracker=_tool_call_tracker() if spec.get("exhaust") else None,
        structured_output_error=run.structured_output_error if run is not None else None,
    )

    assert offline_out.outcome is online_out.outcome
    if case == "clean":
        assert online_out.outcome is RunOutcome.passed
    else:
        assert online_out.outcome is not RunOutcome.passed
    if case == "missing_output":
        assert online_out.outcome is RunOutcome.inconclusive


@pytest.mark.parametrize("output", [None, "not json", '{"findings": [{"bogus": 1}]}'])
async def test_an_offline_missing_or_invalid_set_output_is_inconclusive_not_a_config_error(
    output: str | None, offline: dict[str, Any], tmp_path: Path
) -> None:
    """#1293: the model not producing its findings is not a setup error (exit 20, not 30)."""
    from mergecraft.offline_review import (
        _finish_offline_result,
        findings_from_analyzer_run,
        merge_analyzer_findings_into_result,
        parse_offline_review_findings,
    )

    offline["result"] = AgentResult(success=True, terminal_submission_received=True)
    offline["output"] = output

    reviewed = await _run_offline(offline, tmp_path)
    # The rest of the CLI lifecycle: analyzer fold, then the JSON finalize step.
    merged = merge_analyzer_findings_into_result(reviewed, findings_from_analyzer_run(None))
    finished = _finish_offline_result(
        merged, json_path=tmp_path / "findings.json", scope_reduction=None, cache_key=None
    )

    assert finished.outcome is RunOutcome.inconclusive
    assert finished.success is False
    assert cli_exit_code_for_review(finished.outcome, parse_offline_review_findings(finished)) == 20


async def test_an_offline_blocking_secondary_finding_reaches_the_json_and_exit_code(
    offline: dict[str, Any], tmp_path: Path
) -> None:
    from mergecraft.offline_review import parse_offline_review_findings

    offline["result"] = AgentResult(success=True, terminal_submission_received=True)
    offline["secondary"] = _secondary_row("Major")

    result = await _run_offline(offline, tmp_path)

    findings = parse_offline_review_findings(result)
    assert offline["secondary"]["fingerprint"] in {row.fingerprint for row in findings}
    assert cli_exit_code_for_review(result.outcome, findings) == 11


@pytest.mark.parametrize(
    "outcome", [RunOutcome.infra_error, RunOutcome.timed_out, RunOutcome.inconclusive]
)
def test_a_blocker_does_not_mask_an_outcome_the_review_did_not_reach(outcome: RunOutcome) -> None:
    blocker = make_finding(
        tool="ruff",
        rule_id="S608",
        category="Security & Privacy",
        severity="Major",
        confidence="likely",
        message="x",
        path="a.py",
        start_line=1,
        end_line=1,
        source="analyzer",
    )
    assert (
        cli_exit_code_for_review(outcome, [blocker])
        == {
            RunOutcome.infra_error: 40,
            RunOutcome.timed_out: 50,
            RunOutcome.inconclusive: 20,
        }[outcome]
    )
