"""Suite for ``submit_review_verdict`` — the typed terminal review operation (VP1).

Wave plan: ``.ignorelocal/01-review-integrity-wave-plan.md`` (VP1.1 RED, VP1.2
impl). xfail markers were removed after VP1.2.

Pinned contracts (W0):
    D3 — submission findings are ``AgentFinding``, not a parallel type.
    D4 — identical resubmit is idempotent; a conflicting payload rejects the
         attempt and sets ``terminal_submission_conflict``.
    extra="forbid" on the params model.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import ValidationError

from mergecraft.agents.gates import (
    TERMINAL_PROTOCOL_DENIED_TOOL_NAMES,
    subagent_denied_tool_names,
)
from mergecraft.agents.verifier import AgentFinding, verifier_denied_tool_names
from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.server import build_common_tools, build_orchestrator_tools
from mergecraft.mcp.shared import ToolResult
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path

_TOOL_NAME = "submit_review_verdict"
_UNEXPECTED_FIELD = "unexpected_field"


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request"),
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
    )


def _valid_payload() -> dict[str, Any]:
    return {
        "verdict": "approve",
        "summary": "No blocking issues in the diff.",
        "findings": [],
    }


def _canonical_payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _params_model() -> type[Any]:
    """Pinned name: the plan did not lock a class, the suite does."""
    from mergecraft.mcp.verdict import SubmitReviewVerdictParams

    return SubmitReviewVerdictParams


async def _submit(ctx: ToolContext, payload: dict[str, Any]) -> ToolResult:
    from mergecraft.mcp.verdict import submit_review_verdict_tool

    return await submit_review_verdict_tool(ctx).execute(payload)


def _error_text(result: ToolResult) -> str:
    return result.content[0]["text"]


@pytest.mark.asyncio
async def test_valid_submission_is_recorded(tmp_path: Path) -> None:
    """A well-formed submission lands a ``TerminalSubmission`` on ``ToolState`` with an id."""
    from mergecraft.mcp.tool_state import TerminalSubmission

    ctx = _ctx(tmp_path)
    payload = _valid_payload()
    result = await _submit(ctx, payload)

    assert result.is_error is False
    recorded = ctx.tool_state.terminal_submission
    assert recorded is not None
    assert isinstance(recorded, TerminalSubmission)
    assert isinstance(recorded.id, str)
    assert recorded.id
    assert recorded.verdict == "approve"
    assert recorded.summary == payload["summary"]
    assert recorded.findings == []
    assert recorded.payload_hash == _canonical_payload_hash(
        _params_model().model_validate(payload).model_dump(mode="json")
    )
    assert recorded.submitted_at
    assert hasattr(recorded, "attempt_id")


@pytest.mark.asyncio
async def test_unknown_field_is_rejected(tmp_path: Path) -> None:
    """``extra="forbid"``: an unrecognized key is a validation error, not a silent drop."""
    params_cls = _params_model()
    assert params_cls.model_config.get("extra") == "forbid"

    payload = {**_valid_payload(), _UNEXPECTED_FIELD: "nope"}
    with pytest.raises(ValidationError) as excinfo:
        params_cls.model_validate(payload)
    assert _UNEXPECTED_FIELD in str(excinfo.value)

    ctx = _ctx(tmp_path)
    result = await _submit(ctx, payload)
    assert result.is_error is True
    assert _UNEXPECTED_FIELD in _error_text(result)
    assert getattr(ctx.tool_state, "terminal_submission", None) is None


@pytest.mark.asyncio
async def test_invalid_verdict_enum_is_rejected(tmp_path: Path) -> None:
    """``\"lgtm\"`` is not a verdict — only ``approve`` / ``request_changes``."""
    payload = {**_valid_payload(), "verdict": "lgtm"}
    with pytest.raises(ValidationError) as excinfo:
        _params_model().model_validate(payload)
    message = str(excinfo.value)
    assert "lgtm" in message
    assert "verdict" in message.lower()

    ctx = _ctx(tmp_path)
    result = await _submit(ctx, payload)
    assert result.is_error is True
    assert "lgtm" in _error_text(result)
    assert getattr(ctx.tool_state, "terminal_submission", None) is None


@pytest.mark.asyncio
async def test_missing_required_field_is_rejected(tmp_path: Path) -> None:
    """Absent ``summary`` / ``verdict`` is a validation error, not a defaulted record."""
    params_cls = _params_model()
    for omit in ("summary", "verdict"):
        payload = _valid_payload()
        del payload[omit]
        with pytest.raises(ValidationError) as excinfo:
            params_cls.model_validate(payload)
        assert omit in str(excinfo.value)

        ctx = _ctx(tmp_path)
        result = await _submit(ctx, payload)
        assert result.is_error is True
        assert omit in _error_text(result).lower()
        assert getattr(ctx.tool_state, "terminal_submission", None) is None


@pytest.mark.asyncio
async def test_findings_use_agent_finding_shape(tmp_path: Path) -> None:
    """D3: a submission finding round-trips through ``AgentFinding`` (fingerprint + identity)."""
    finding = AgentFinding(
        path="src/app.py",
        body="token logged in plaintext",
        severity="Critical",
        line=12,
        fingerprint="fp-explicit-identity",
    )
    ctx = _ctx(tmp_path)
    result = await _submit(
        ctx,
        {
            "verdict": "request_changes",
            "summary": "One critical finding stands.",
            "findings": [finding.model_dump()],
        },
    )
    assert result.is_error is False
    recorded = ctx.tool_state.terminal_submission
    assert recorded is not None
    assert len(recorded.findings) == 1
    round_tripped = recorded.findings[0]
    assert isinstance(round_tripped, AgentFinding)
    assert round_tripped.fingerprint == finding.fingerprint
    assert round_tripped.identity() == finding.identity()
    assert round_tripped.path == finding.path
    assert round_tripped.body == finding.body
    assert round_tripped.severity == finding.severity
    assert round_tripped.line == finding.line


def test_unknown_finding_severity_is_rejected() -> None:
    """Terminal findings must use the closed taxonomy, not a free-form string."""
    payload = {
        "verdict": "request_changes",
        "summary": "One finding stands.",
        "findings": [
            {
                "path": "src/app.py",
                "body": "token logged in plaintext",
                "severity": "Blocker",
            }
        ],
    }
    with pytest.raises(ValidationError) as excinfo:
        _params_model().model_validate(payload)
    message = str(excinfo.value)
    assert "Blocker" in message
    assert "severity" in message.lower()


@pytest.mark.asyncio
async def test_unknown_finding_severity_is_rejected_at_the_tool(tmp_path: Path) -> None:
    """MCP dispatch does not schema-validate arguments — the tool must still reject."""
    ctx = _ctx(tmp_path)
    result = await _submit(
        ctx,
        {
            "verdict": "request_changes",
            "summary": "One finding stands.",
            "findings": [
                {
                    "path": "src/app.py",
                    "body": "token logged in plaintext",
                    "severity": "Blocker",
                }
            ],
        },
    )
    assert result.is_error is True
    assert "blocker" in _error_text(result).lower()
    assert getattr(ctx.tool_state, "terminal_submission", None) is None


@pytest.mark.asyncio
async def test_second_identical_submission_is_idempotent(tmp_path: Path) -> None:
    """D4: the same payload hash returns the original id; no second record."""
    ctx = _ctx(tmp_path)
    payload = _valid_payload()
    first = await _submit(ctx, payload)
    assert first.is_error is False
    original = ctx.tool_state.terminal_submission
    assert original is not None
    original_id = original.id
    original_hash = original.payload_hash

    second = await _submit(ctx, payload)
    assert second.is_error is False
    replayed = ctx.tool_state.terminal_submission
    assert replayed is not None
    assert replayed.id == original_id
    assert replayed.payload_hash == original_hash
    assert replayed is original
    assert ctx.tool_state.terminal_submission_conflict is False


@pytest.mark.asyncio
async def test_second_conflicting_submission_is_rejected(tmp_path: Path) -> None:
    """D4: a differing payload is an error and marks the attempt unusable."""
    ctx = _ctx(tmp_path)
    first = await _submit(ctx, _valid_payload())
    assert first.is_error is False
    original_id = ctx.tool_state.terminal_submission.id  # type: ignore[union-attr]

    conflicting = {**_valid_payload(), "summary": "Actually this needs changes."}
    second = await _submit(ctx, conflicting)
    assert second.is_error is True
    assert "conflict" in _error_text(second).lower()
    assert ctx.tool_state.terminal_submission_conflict is True
    assert ctx.tool_state.terminal_submission is not None
    assert ctx.tool_state.terminal_submission.id == original_id


@pytest.mark.asyncio
async def test_conflict_flag_stays_set_after_identical_replay(tmp_path: Path) -> None:
    """A → conflict B → A must leave the attempt marked unusable for VP2."""
    ctx = _ctx(tmp_path)
    first = await _submit(ctx, _valid_payload())
    assert first.is_error is False
    original_id = ctx.tool_state.terminal_submission.id  # type: ignore[union-attr]

    conflicting = {**_valid_payload(), "summary": "Actually this needs changes."}
    second = await _submit(ctx, conflicting)
    assert second.is_error is True
    assert ctx.tool_state.terminal_submission_conflict is True

    third = await _submit(ctx, _valid_payload())
    assert third.is_error is False
    replayed = ctx.tool_state.terminal_submission
    assert replayed is not None
    assert replayed.id == original_id
    assert ctx.tool_state.terminal_submission_conflict is True


def test_tool_is_registered_for_orchestrator_only(tmp_path: Path) -> None:
    """Present on the orchestrator toolset; absent from the read-only common set."""
    ctx = _ctx(tmp_path)
    orchestrator = {spec.name: spec for spec in build_orchestrator_tools(ctx)}
    common_names = {spec.name for spec in build_common_tools(ctx)}

    assert _TOOL_NAME in orchestrator
    assert orchestrator[_TOOL_NAME].mutates is False
    assert _TOOL_NAME not in common_names


def test_tool_is_in_subagent_deny_list(tmp_path: Path) -> None:
    """Terminal-protocol tools are denied to subagents and the verifier even when mutates=False."""
    ctx = _ctx(tmp_path)
    assert _TOOL_NAME in TERMINAL_PROTOCOL_DENIED_TOOL_NAMES
    assert _TOOL_NAME in subagent_denied_tool_names(ctx)
    assert _TOOL_NAME in verifier_denied_tool_names(ctx)


@pytest.mark.parametrize("value", [{}, False, 0, "", None])
def test_non_list_findings_are_rejected(value: object) -> None:
    """Malformed falsy findings must not canonicalize to an empty list."""
    payload = {**_valid_payload(), "findings": value}
    with pytest.raises(ValidationError) as excinfo:
        _params_model().model_validate(payload)
    assert "findings" in str(excinfo.value).lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [{}, False, 0, "", None])
async def test_non_list_findings_are_rejected_at_the_tool(tmp_path: Path, value: object) -> None:
    """MCP dispatch does not schema-validate arguments — the tool must still reject."""
    ctx = _ctx(tmp_path)
    result = await _submit(ctx, {**_valid_payload(), "findings": value})
    assert result.is_error is True
    assert "findings" in _error_text(result).lower()
    assert getattr(ctx.tool_state, "terminal_submission", None) is None


@pytest.mark.asyncio
async def test_omitted_findings_matches_empty_list_idempotency(tmp_path: Path) -> None:
    """D4: omitting ``findings`` and sending ``findings: []`` are the same payload."""
    ctx = _ctx(tmp_path)
    omitted = {"verdict": "approve", "summary": "No blocking issues in the diff."}
    first = await _submit(ctx, omitted)
    assert first.is_error is False
    original_id = ctx.tool_state.terminal_submission.id  # type: ignore[union-attr]

    second = await _submit(ctx, {**omitted, "findings": []})
    assert second.is_error is False
    replayed = ctx.tool_state.terminal_submission
    assert replayed is not None
    assert replayed.id == original_id
    assert ctx.tool_state.terminal_submission_conflict is False


@pytest.mark.asyncio
async def test_model_chain_resets_terminal_submission_on_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A retryable first attempt's submit must not conflict-reject the fallback."""
    from mergecraft.agents.shared import AgentResult
    from mergecraft.config.settings import RepoSettings
    from mergecraft.utils.agent_resolve import run_with_model_chain

    monkeypatch.setenv("CODEX_AUTH_JSON", '{"access_token":"test-token"}')
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.setattr(
        "mergecraft.utils.agent_resolve._agent_binary_available",
        lambda _slug: True,
    )

    ctx = _ctx(tmp_path)
    seen_indexes: list[int] = []

    async def run_once(slug: str) -> AgentResult:
        seen_indexes.append(ctx.tool_state.fallback_index)
        if slug.startswith("openai/"):
            recorded = await _submit(ctx, _valid_payload())
            assert recorded.is_error is False
            assert ctx.tool_state.fallback_index == 0
            return AgentResult(
                success=False,
                error="provider rate limited",
                metadata={"retryable": True},
            )
        assert ctx.tool_state.fallback_index == 1
        assert ctx.tool_state.terminal_submission is None
        assert ctx.tool_state.terminal_submission_conflict is False
        recorded = await _submit(
            ctx,
            {**_valid_payload(), "summary": "Fallback model recorded the verdict."},
        )
        assert recorded.is_error is False
        return AgentResult(success=True, output="review complete")

    settings = RepoSettings.model_validate(
        {"models": ["openai/gpt-5.3-codex", "google/gemini-3.1-pro-preview"]}
    )
    winning_slug, result = await run_with_model_chain(
        settings=settings,
        run_once=run_once,
        tool_state=ctx.tool_state,
    )

    assert seen_indexes == [0, 1]
    assert winning_slug == "google/gemini-3.1-pro-preview"
    assert result.success is True
    recorded = ctx.tool_state.terminal_submission
    assert recorded is not None
    assert recorded.attempt_id == 1
    assert recorded.summary == "Fallback model recorded the verdict."
    assert ctx.tool_state.terminal_submission_conflict is False


@pytest.mark.asyncio
async def test_model_chain_advances_when_first_success_has_no_terminal_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A process-successful first slug with no submit must not win the chain."""
    from mergecraft.agents.shared import AgentResult
    from mergecraft.config.settings import RepoSettings
    from mergecraft.mcp.verdict import ReviewPhase
    from mergecraft.utils.agent_resolve import run_with_model_chain

    monkeypatch.setenv("CODEX_AUTH_JSON", '{"access_token":"test-token"}')
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.setattr(
        "mergecraft.utils.agent_resolve._agent_binary_available",
        lambda _slug: True,
    )

    ctx = _ctx(tmp_path)
    ctx.tool_state.selected_mode = "Review"
    ctx.tool_state.review_phase = ReviewPhase.ESTABLISH_SCOPE.value
    calls: list[str] = []

    async def run_once(slug: str) -> AgentResult:
        calls.append(slug)
        if slug.startswith("openai/"):
            return AgentResult(success=True, output="LGTM — looks good to me.")
        recorded = await _submit(ctx, _valid_payload())
        assert recorded.is_error is False
        submission = ctx.tool_state.terminal_submission
        assert submission is not None
        return AgentResult(
            success=True,
            output="review complete",
            terminal_submission_received=True,
            terminal_submission_id=submission.id,
        )

    settings = RepoSettings.model_validate(
        {"models": ["openai/gpt-5.3-codex", "google/gemini-3.1-pro-preview"]}
    )
    winning_slug, result = await run_with_model_chain(
        settings=settings,
        run_once=run_once,
        tool_state=ctx.tool_state,
    )

    assert calls == ["openai/gpt-5.3-codex", "google/gemini-3.1-pro-preview"]
    assert winning_slug == "google/gemini-3.1-pro-preview"
    assert result.success is True
    assert result.terminal_submission_received is True
    recorded = ctx.tool_state.terminal_submission
    assert recorded is not None
    assert recorded.attempt_id == 1


@pytest.mark.asyncio
async def test_model_chain_does_not_advance_after_incremental_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """IncrementalReview ``report_progress`` is a complete result; do not fallback."""
    from mergecraft.agents.shared import AgentResult
    from mergecraft.config.settings import RepoSettings
    from mergecraft.utils.agent_resolve import run_with_model_chain

    monkeypatch.setenv("CODEX_AUTH_JSON", '{"access_token":"test-token"}')
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.setattr(
        "mergecraft.utils.agent_resolve._agent_binary_available",
        lambda _slug: True,
    )

    ctx = _ctx(tmp_path)
    ctx.tool_state.selected_mode = "IncrementalReview"
    calls: list[str] = []

    async def run_once(slug: str) -> AgentResult:
        calls.append(slug)
        if not slug.startswith("openai/"):
            raise AssertionError(f"fallback model {slug} must not run")
        ctx.tool_state.final_summary_written = True
        return AgentResult(success=True, output="no new findings")

    settings = RepoSettings.model_validate(
        {"models": ["openai/gpt-5.3-codex", "google/gemini-3.1-pro-preview"]}
    )
    winning_slug, result = await run_with_model_chain(
        settings=settings,
        run_once=run_once,
        tool_state=ctx.tool_state,
    )

    assert calls == ["openai/gpt-5.3-codex"]
    assert winning_slug == "openai/gpt-5.3-codex"
    assert result.success is True
    assert ctx.tool_state.final_summary_written is True
    assert ctx.tool_state.terminal_submission is None


# ---------------------------------------------------------------------------
# W14.5 / #263 — the tool surface must fail closed on unverified blockers
# ---------------------------------------------------------------------------
#
# Live anchors: ``mcp/verdict.py:276-313`` (``_confirmed_findings_from_state``)
# and ``:395-413`` (the approve branch). Wave text W19.1 says "~377", which is
# stale — the approve branch begins at ``:395``.
#
# D12: reject ``approve`` when a blocking-severity finding exists in
# ``analyzer_run.findings`` that is neither verified nor withdrawn. The
# rejection reason reuses the existing ``approve_with_confirmed_blocker``
# (see the note in ``tests/review/test_terminal_verdict_policy.py``).

_REASON_APPROVE_CONFIRMED_BLOCKER = "approve_with_confirmed_blocker"


def _analyzer_blocker(severity: str = "Critical") -> Any:
    from mergecraft.analyzers.finding import make_finding

    return make_finding(
        tool="bandit",
        rule_id="B105-w14",
        category="Security & Privacy",
        severity=severity,
        confidence="certain",
        message="Hardcoded credential committed in the diff.",
        path="src/app.py",
        start_line=30,
        end_line=30,
        source="analyzer",
        evidence=["PASSWORD = 'hunter2'"],
        fingerprint=f"w14-mcp-unverified-{severity.lower()}",
        introduced_by_pr="true",
    )


def _seed_analyzer_run(ctx: ToolContext, findings: list[Any], *, verified: set[str]) -> None:
    from mergecraft.mcp.tool_state import AnalyzerRunState

    ctx.tool_state.analyzer_run = AnalyzerRunState(
        ran=True,
        findings=[finding.model_dump() for finding in findings],
        verified_ids=set(verified),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("severity", ["Critical", "Major"])
async def test_approve_is_rejected_when_a_blocker_was_never_verified(
    tmp_path: Path,
    severity: str,
) -> None:
    """#263 / D12 — the terminal tool must not bank an approve over an unverified blocker."""
    ctx = _ctx(tmp_path)
    _seed_analyzer_run(ctx, [_analyzer_blocker(severity)], verified=set())

    result = await _submit(ctx, _valid_payload())

    assert result.is_error is True
    assert _REASON_APPROVE_CONFIRMED_BLOCKER in _error_text(result)
    assert ctx.tool_state.terminal_submission is None


@pytest.mark.asyncio
async def test_approve_is_recorded_when_the_analyzer_findings_are_non_blocking(
    tmp_path: Path,
) -> None:
    """Green guard: a Minor analyzer finding must still allow an approve.

    The legitimate-approve arm at the tool surface. Without it, W19 could
    reject every approve made after ``run_analyzers`` reported anything.
    """
    ctx = _ctx(tmp_path)
    _seed_analyzer_run(ctx, [_analyzer_blocker("Minor")], verified=set())

    result = await _submit(ctx, _valid_payload())

    assert result.is_error is False
    recorded = ctx.tool_state.terminal_submission
    assert recorded is not None
    assert recorded.verdict == "approve"


@pytest.mark.asyncio
async def test_approve_is_recorded_when_no_analyzer_run_happened(tmp_path: Path) -> None:
    """Green guard: no analyzer state at all must not become a blanket rejection."""
    ctx = _ctx(tmp_path)
    result = await _submit(ctx, _valid_payload())

    assert result.is_error is False
    assert ctx.tool_state.terminal_submission is not None


@pytest.mark.asyncio
async def test_terminal_finding_backfills_into_agent_findings_for_the_packet(
    tmp_path: Path,
) -> None:
    """#619 — a finding that only ever reaches the terminal payload must still

    surface through ``load_run_findings``, the one loader ``decide_approval``
    and the merge-evidence packet both read. Before this back-fill, a finding
    submitted here but never drafted via ``verify_agent_findings`` was
    invisible to the gate no matter how blocking it was.
    """
    from mergecraft.evidence.findings import load_run_findings

    ctx = _ctx(tmp_path)
    finding = AgentFinding(
        path="src/auth.py",
        body="Session token is logged in plaintext on every request.",
        severity="Critical",
        line=42,
    )
    result = await _submit(
        ctx,
        {
            "verdict": "request_changes",
            "summary": "One critical security finding stands.",
            "findings": [finding.model_dump()],
        },
    )

    assert result.is_error is False
    fingerprint = finding.identity()
    stored_fingerprints = {
        row.get("fingerprint") for row in ctx.tool_state.agent_findings if isinstance(row, dict)
    }
    assert fingerprint in stored_fingerprints

    loaded = load_run_findings(ctx)
    matching = [item for item in loaded if item.fingerprint == fingerprint]
    assert len(matching) == 1
    assert matching[0].severity == "Critical"


@pytest.mark.asyncio
async def test_backfill_does_not_clobber_a_prior_downgrade(tmp_path: Path) -> None:
    """A ``record_finding_verdict`` downgrade must win over a stale draft (#619).

    ``agent_findings`` already carries a row for this fingerprint at a
    downgraded (non-blocking) severity — the terminal payload re-submitting
    the same fingerprint at ``Critical`` must not overwrite that stored row.
    """
    from mergecraft.analyzers.finding import make_finding

    ctx = _ctx(tmp_path)
    fingerprint = "fp-already-downgraded"
    downgraded = make_finding(
        tool="agent",
        rule_id="agent:draft",
        category="Maintainability & Code Quality",
        severity="Minor",
        confidence="likely",
        message="Session token is logged in plaintext on every request.",
        path="src/auth.py",
        start_line=42,
        end_line=42,
        source="agent",
        fingerprint=fingerprint,
    )
    ctx.tool_state.agent_findings = [downgraded.model_dump(mode="json")]

    finding = AgentFinding(
        path="src/auth.py",
        body="Session token is logged in plaintext on every request.",
        severity="Critical",
        line=42,
        fingerprint=fingerprint,
    )
    result = await _submit(
        ctx,
        {
            "verdict": "request_changes",
            "summary": "One finding stands.",
            "findings": [finding.model_dump()],
        },
    )

    assert result.is_error is False
    stored = [
        row
        for row in ctx.tool_state.agent_findings
        if isinstance(row, dict) and row.get("fingerprint") == fingerprint
    ]
    assert len(stored) == 1
    assert stored[0]["severity"] == "Minor"
