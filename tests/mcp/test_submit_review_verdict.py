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
    assert recorded.payload_hash == _canonical_payload_hash(payload)
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
