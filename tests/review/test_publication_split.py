"""VP4 publication split — ``create_pull_request_review`` delegates; publisher is internal.

Wave plan: ``.ignorelocal/01-review-integrity-wave-plan.md`` (VP4.1 RED, VP4.2 impl).

Pinned contracts (W0):
    D7 — ``create_pull_request_review`` is adapted, not deleted; thin delegate
         to ``validate_submission`` + the same recorder as ``submit_review_verdict``.
    D8 — a rejected attempt leaves ``terminal_submission`` unset.
    V6 — GitHub posting moves to an internal publisher that is not a ``ToolSpec``.
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
_VP42_DELEGATE = pytest.mark.xfail(
    reason="green after VP4.2: create_pull_request_review delegates through validate_submission",
    strict=False,
)
_VP42_PUBLISH = pytest.mark.xfail(
    reason="green after VP4.2: publication requires a validated terminal submission",
    strict=False,
)
_VP42_INTERNAL = pytest.mark.xfail(
    reason="green after VP4.2: publisher is not an MCP tool",
    strict=False,
)


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


@_VP42_DELEGATE
@pytest.mark.asyncio
async def test_create_pull_request_review_delegates_to_recorder(tmp_path: Path) -> None:
    """D7: the live legacy tool records through ``validate_submission``.

    Guard-deletion: posting ``approved=True`` with a payload that would fail
    ``validate_submission`` (approve + confirmed blocker) must error and leave
    ``terminal_submission`` unset (D8). Writing ``ApprovalRecord.would_approve``
    without that validation is the V6 bypass this PR closes.
    """
    from mergecraft.mcp.verdict import validate_submission, validation_state_from_tool_context

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


@_VP42_PUBLISH
@pytest.mark.asyncio
async def test_publication_requires_a_validated_submission(tmp_path: Path) -> None:
    """Publishing without a validated terminal submission is an error."""
    from mergecraft.mcp.review import publish_pull_request_review

    github = _RecordingGitHub()
    ctx = _ctx(tmp_path, github=github)
    assert getattr(ctx.tool_state, "terminal_submission", None) is None

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


@_VP42_INTERNAL
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
