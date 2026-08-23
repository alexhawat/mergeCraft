"""VP4 publication split — ``create_pull_request_review`` delegates; publisher is internal.

Wave plan: ``.ignorelocal/01-review-integrity-wave-plan.md`` (VP4.1 RED,
VP4.2 impl; xfail markers cleared after VP4.2 / VP4.3 / VP4.4).

Pinned contracts (W0):
    D7 — ``create_pull_request_review`` is adapted, not deleted; thin delegate
         to ``validate_submission`` + the same recorder as ``submit_review_verdict``.
    D8 — a rejected attempt leaves ``terminal_submission`` unset.
    V6 — GitHub posting moves to an internal publisher that is not a ``ToolSpec``.
    VP4.4 — a hash-matching replay must re-validate before any GitHub post;
         a later confirmed blocker must not GitHub-APPROVE. D4 (identical
         retry is idempotent) still applies to ``submit_review_verdict`` when
         state has not changed.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.analyzers.finding import make_finding
from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.review import create_pull_request_review_tool
from mergecraft.mcp.server import build_common_tools, build_orchestrator_tools
from mergecraft.mcp.shared import ToolResult, ToolSpec
from mergecraft.mcp.tool_state import AnalyzerRunState, init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path

_TOOL_NAME = "create_pull_request_review"
_PUBLISHER_NAME = "publish_pull_request_review"


class _RecordingGitHub(GitHubClient):
    """GitHub client that captures review payloads instead of sending them."""

    def __init__(self) -> None:
        super().__init__(token="test-token")
        self.review_payloads: list[dict[str, Any]] = []

    async def create_review(
        self, owner: str, repo: str, pull_number: int, **payload: Any
    ) -> dict[str, Any]:
        del owner, repo, pull_number
        self.review_payloads.append(payload)
        return {"id": 1, "node_id": "n1", "html_url": "https://x/1", "state": "COMMENTED"}


def _ctx(tmp_path: Path, *, github: GitHubClient | None = None) -> ToolContext:
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request", issue_number=7, is_pr=True),
            shell="restricted",
        ),
        github=github or _RecordingGitHub(),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_server_url="",
        tmpdir=str(tmp_path),
        pr_approve_enabled=True,
        trust_tier="trusted",
    )


def _blocker() -> Any:
    return make_finding(
        tool="vp4-fixture",
        rule_id="VP4-BLOCKER",
        category="Security & Privacy",
        severity="Critical",
        confidence="certain",
        message="Secret written to logs.",
        path="src/app.py",
        start_line=12,
        end_line=12,
        source="agent",
        evidence=["logger.info(api_key)"],
        fingerprint="vp4-blocker-cr",
    )


def _error_text(result: ToolResult) -> str:
    return result.content[0]["text"]


def _tool_names(ctx: ToolContext) -> set[str]:
    """Union of every ``build_*_tools`` name set on the MCP server module."""
    import mergecraft.mcp.server as server_mod

    names: set[str] = set()
    for attr in dir(server_mod):
        if not (attr.startswith("build_") and attr.endswith("_tools")):
            continue
        builder = getattr(server_mod, attr)
        if not callable(builder):
            continue
        specs = builder(ctx)
        names.update(spec.name for spec in specs)
    return names


@pytest.mark.asyncio
async def test_create_pull_request_review_delegates_to_recorder(tmp_path: Path) -> None:
    """D7: the live legacy tool records through ``validate_submission``.

    Guard-deletion: posting ``approved=True`` with a payload that would fail
    ``validate_submission`` (approve + confirmed blocker) must error and leave
    ``terminal_submission`` unset (D8). Writing ``ApprovalRecord.would_approve``
    without that validation is the V6 bypass this PR closes.
    """
    from mergecraft.mcp.verdict import (
        record_validated_terminal_submission,
        validate_submission,
        validation_state_from_tool_context,
    )

    assert callable(record_validated_terminal_submission)

    github = _RecordingGitHub()
    ctx = _ctx(tmp_path, github=github)
    blocker = _blocker()
    ctx.tool_state.analyzer_run = AnalyzerRunState(
        ran=True,
        findings=[blocker.model_dump()],
        verified_ids={blocker.fingerprint},
    )

    mapped = {
        "verdict": "approve",
        "summary": "Looks good.",
        "findings": [],
    }
    validation = validate_submission(mapped, state=validation_state_from_tool_context(ctx))
    assert validation.accepted is False, (
        "fixture error: mapped approve + confirmed blocker must fail validate_submission"
    )

    spec = create_pull_request_review_tool(ctx)
    result = await spec.execute(
        {"pull_number": 7, "body": "Looks good.", "approved": True},
    )
    assert result.is_error is True, (
        "create_pull_request_review must not write an ApprovalRecord that bypasses "
        f"validate_submission; got success: {_error_text(result) if result.is_error else result.content}"
    )
    assert getattr(ctx.tool_state, "terminal_submission", None) is None
    assert ctx.tool_state.approval is None, (
        "legacy tool must not write ApprovalRecord.would_approve when validation rejects"
    )
    assert github.review_payloads == [], (
        "rejected submission must not post a GitHub review (publisher is a separate act)"
    )


def test_legacy_tool_still_registered(tmp_path: Path) -> None:
    """Compatibility pin: ``create_pull_request_review`` stays in the visible registry."""
    ctx = _ctx(tmp_path)
    orchestrator = {spec.name: spec for spec in build_orchestrator_tools(ctx)}
    common_names = {spec.name for spec in build_common_tools(ctx)}

    assert _TOOL_NAME in orchestrator
    assert _TOOL_NAME in common_names
    assert orchestrator[_TOOL_NAME].name == _TOOL_NAME


@pytest.mark.asyncio
async def test_publication_requires_a_validated_submission(tmp_path: Path) -> None:
    """Publishing without a validated terminal submission is an error."""
    from mergecraft.mcp.review import publish_pull_request_review

    github = _RecordingGitHub()
    ctx = _ctx(tmp_path, github=github)
    assert getattr(ctx.tool_state, "terminal_submission", None) is None
    assert ctx.tool_state.pending_review_publication is None

    caught: BaseException | None = None
    outcome: object | None = None
    try:
        outcome = publish_pull_request_review(ctx)
        if inspect.isawaitable(outcome):
            outcome = await outcome
    except Exception as exc:
        caught = exc

    if caught is not None:
        message = str(caught).lower()
        assert "submission" in message or "validat" in message, (
            f"publisher error must name the missing validated submission, got {caught!r}"
        )
        assert getattr(ctx.tool_state, "terminal_submission", None) is None
        assert github.review_payloads == []
        return

    assert isinstance(outcome, ToolResult)
    assert outcome.is_error is True
    text = _error_text(outcome).lower()
    assert "submission" in text or "validat" in text
    assert getattr(ctx.tool_state, "terminal_submission", None) is None
    assert github.review_payloads == []


@pytest.mark.asyncio
async def test_body_only_unapproved_legacy_review_does_not_github_approve(
    tmp_path: Path,
) -> None:
    """Body-only ``approved: false`` must not GitHub-APPROVE (security-review).

    Guard-deletion: a fallthrough ``return {"verdict": "approve", ...}`` in
    ``_legacy_params_to_submission`` must fail this test. Rejecting the
    attempt (D8 ``terminal_submission`` unset + empty ``review_payloads``)
    is also a pass.
    """
    from mergecraft.mcp.review import _legacy_params_to_submission

    params = {
        "pull_number": 7,
        "body": "> [!IMPORTANT]\n> Please fix the tests.",
        "approved": False,
    }
    mapped = _legacy_params_to_submission(params)
    assert mapped["verdict"] != "approve", (
        "body-only approved=false must not fall through to verdict=approve"
    )

    github = _RecordingGitHub()
    ctx = _ctx(tmp_path, github=github)
    await create_pull_request_review_tool(ctx).execute(params)

    assert not any(payload.get("event") == "APPROVE" for payload in github.review_payloads), (
        f"body-only approved=false must not GitHub-APPROVE, got {github.review_payloads!r}"
    )
    submission = getattr(ctx.tool_state, "terminal_submission", None)
    if submission is not None:
        assert submission.verdict != "approve"


@pytest.mark.asyncio
async def test_stale_approve_replay_does_not_github_approve_after_blocker(
    tmp_path: Path,
) -> None:
    """Replay + publish after state changed must not GitHub-APPROVE (VP4.4).

    Guard-deletion: ``record_validated_terminal_submission`` returning the
    stored ``approve`` on a matching ``payload_hash`` without calling
    ``validate_submission``, then ``create_pull_request_review`` posting
    GitHub ``APPROVE``, must fail this test.

    Fresh approve+blocker already fails closed
    (``test_create_pull_request_review_delegates_to_recorder``). This pin is
    publication-time re-validation when a confirmed blocker appears *after*
    a valid submit. D4 still applies to ``submit_review_verdict`` when state
    has not changed. D8 (wipe ``terminal_submission``) is for a rejected
    first attempt; a prior valid submit may remain.
    """
    from mergecraft.mcp.verdict import (
        ReviewPhase,
        submit_review_verdict_tool,
        validate_submission,
        validation_state_from_tool_context,
    )

    github = _RecordingGitHub()
    ctx = _ctx(tmp_path, github=github)
    ctx.tool_state.selected_mode = "Review"
    ctx.tool_state.review_phase = ReviewPhase.ESTABLISH_SCOPE.value
    assert ctx.tool_state.analyzer_run is None
    assert ctx.pr_approve_enabled is True
    assert ctx.trust_tier == "trusted"

    submit_params = {
        "verdict": "approve",
        "summary": "Looks good.",
        "findings": [],
    }
    recorded = await submit_review_verdict_tool(ctx).execute(submit_params)
    assert recorded.is_error is False, (
        f"fixture error: approve with empty analyzer state must record; got {_error_text(recorded)}"
    )
    assert getattr(ctx.tool_state, "terminal_submission", None) is not None

    blocker = _blocker()
    ctx.tool_state.analyzer_run = AnalyzerRunState(
        ran=True,
        findings=[blocker.model_dump()],
        verified_ids={blocker.fingerprint},
    )
    mapped = {
        "verdict": "approve",
        "summary": "Looks good.",
        "findings": [],
    }
    validation = validate_submission(mapped, state=validation_state_from_tool_context(ctx))
    assert validation.accepted is False, (
        "fixture error: mapped approve + confirmed blocker must fail validate_submission"
    )

    result = await create_pull_request_review_tool(ctx).execute(
        {"pull_number": 7, "body": "Looks good.", "approved": True},
    )

    assert not any(payload.get("event") == "APPROVE" for payload in github.review_payloads), (
        "stale approve replay must not GitHub-APPROVE after a confirmed blocker, "
        f"got {github.review_payloads!r}"
    )
    if not result.is_error:
        text = _error_text(result).lower()
        assert "skip" in text or "reject" in text, (
            "create_pull_request_review must error or skip/reject publication "
            "when a confirmed blocker now stands; "
            f"got success: {result.content!r}"
        )
    approval = ctx.tool_state.approval
    assert approval is None or approval.would_approve is False, (
        "second call must not record a successful GitHub approve on ApprovalRecord; "
        f"got {approval!r}"
    )


def test_publisher_is_not_an_mcp_tool(tmp_path: Path) -> None:
    """The internal publisher exists as a function and is not in any toolset."""
    from mergecraft.mcp.review import publish_pull_request_review

    assert callable(publish_pull_request_review)
    assert not isinstance(publish_pull_request_review, ToolSpec)
    assert getattr(publish_pull_request_review, "name", None) != _PUBLISHER_NAME

    ctx = _ctx(tmp_path)
    names = _tool_names(ctx)
    assert _PUBLISHER_NAME not in names
    assert publish_pull_request_review.__name__ not in names
    for spec in (*build_common_tools(ctx), *build_orchestrator_tools(ctx)):
        assert spec.execute is not publish_pull_request_review


def test_legacy_inline_comments_map_to_fingerprinted_findings() -> None:
    """Legacy publish path must stamp fingerprints for recall draft matching."""
    from mergecraft.mcp.review import _comments_to_findings
    from mergecraft.review_taxonomy import finding_fingerprint

    body = "Unchecked null before return."
    path = "src/util.py"
    findings = _comments_to_findings([{"path": path, "line": 4, "body": body}])
    assert findings[0]["fingerprint"] == finding_fingerprint(path=path, body=body)
