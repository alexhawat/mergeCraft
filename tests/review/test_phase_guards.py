"""VP4 phase guards — ``ReviewPhase`` StrEnum + submit-before-scope (D10).

Wave plan: ``.ignorelocal/01-review-integrity-wave-plan.md`` (VP4.1 RED,
VP4.2 impl; xfail markers cleared after VP4.2).

Pinned ``ReviewPhase`` members (name == value), in order:
    INIT → ESTABLISH_SCOPE → COLLECT_EVIDENCE → REVIEW → NORMALIZE →
    VERIFY_BLOCKERS → SUBMIT → POLICY → PUBLISH → COMPLETE

No new framework, no new package — guard clauses on existing tools.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from mergecraft.mcp.checkout import checkout_pr_tool
from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient
from tests.support.tool_context import bind_github_client

_PHASES: tuple[str, ...] = (
    "INIT",
    "ESTABLISH_SCOPE",
    "COLLECT_EVIDENCE",
    "REVIEW",
    "NORMALIZE",
    "VERIFY_BLOCKERS",
    "SUBMIT",
    "POLICY",
    "PUBLISH",
    "COMPLETE",
)

_SPAN_PHASE_KEYS: tuple[str, ...] = ("review.phase", "mergecraft.review.phase")


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


class _StubGitHub(GitHubClient):
    """Serves one PR without touching the network."""

    def __init__(self, *, head_sha: str) -> None:
        super().__init__(token="test-token")
        self._head_sha = head_sha

    async def get_pull(self, owner: str, repo: str, pull_number: int) -> dict[str, Any]:
        del pull_number
        repo_ref = {"full_name": f"{owner}/{repo}"}
        return {
            "head": {"ref": "feature", "sha": self._head_sha, "repo": repo_ref},
            "base": {"ref": "base", "repo": repo_ref},
            "title": "A pull request",
            "html_url": "https://x/1",
        }

    async def list_reviews(
        self, owner: str, repo: str, pull_number: int, **kwargs: Any
    ) -> list[dict[str, Any]]:
        del owner, repo, pull_number, kwargs
        return []


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _pr_clone(tmp_path: Path) -> tuple[Path, str]:
    """Origin serving ``refs/pull/1/head``; return ``(clone, head_sha)``."""
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init")
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "Test")
    (work / "README.md").write_text("base\n", encoding="utf-8")
    _git(work, "add", "README.md")
    _git(work, "commit", "-m", "base")
    _git(work, "branch", "-M", "base")
    _git(work, "checkout", "-b", "feature")
    (work / "app.py").write_text("x = 1\n", encoding="utf-8")
    _git(work, "add", "app.py")
    _git(work, "commit", "-m", "feature")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=work, text=True).strip()
    _git(work, "clone", "--bare", str(work), str(origin))
    _git(work, "push", str(origin), "feature:refs/pull/1/head")
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", str(origin), str(clone))
    return clone, head


def _ctx(tmp_path: Path, *, repo_dir: Path | None = None) -> ToolContext:
    root = repo_dir if repo_dir is not None else tmp_path
    state = init_tool_state(owner="acme", name="demo", dir=str(root))
    state.selected_mode = "Review"
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request", issue_number=1, is_pr=True),
            shell="restricted",
        ),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(artifacts),
    )


def _valid_payload() -> dict[str, Any]:
    return {
        "verdict": "approve",
        "summary": "No blocking issues in the diff.",
        "findings": [],
    }


def _error_text(result: Any) -> str:
    return str(result.content[0]["text"])


def _phase_on_events(events: list[Any], expected: str) -> bool:
    for event in events:
        attrs = getattr(event, "attrs", {}) or {}
        values = {str(value) for value in attrs.values()}
        if expected in values:
            return True
        for key in _SPAN_PHASE_KEYS:
            if str(attrs.get(key, "")) == expected:
                return True
    return False


@pytest.mark.asyncio
async def test_submit_before_scope_is_rejected(tmp_path: Path) -> None:
    """D10: ``submit_review_verdict`` before ``checkout_pr`` established scope errors."""
    from mergecraft.mcp.verdict import submit_review_verdict_tool

    ctx = _ctx(tmp_path)
    result = await submit_review_verdict_tool(ctx).execute(_valid_payload())
    assert result.is_error is True
    text = _error_text(result).lower()
    assert "scope" in text or "phase" in text or "checkout" in text, (
        f"rejection must name the missing scope/phase, got {text!r}"
    )
    assert getattr(ctx.tool_state, "terminal_submission", None) is None


@pytest.mark.asyncio
async def test_create_pull_request_review_before_scope_is_rejected(tmp_path: Path) -> None:
    """D10: the legacy tool must not record or publish before ``checkout_pr``."""
    from mergecraft.mcp.review import create_pull_request_review_tool
    from mergecraft.mcp.verdict import ensure_review_scope_for_terminal

    assert callable(ensure_review_scope_for_terminal)

    github = _RecordingGitHub()
    ctx = _ctx(tmp_path)
    bind_github_client(ctx, github)
    assert ctx.tool_state.selected_mode == "Review"
    assert str(getattr(ctx.tool_state, "review_phase", "INIT")) == "INIT"

    result = await create_pull_request_review_tool(ctx).execute(
        {"pull_number": 1, "body": "Looks good.", "approved": True},
    )
    assert result.is_error is True
    text = _error_text(result).lower()
    assert "scope" in text or "phase" in text or "checkout" in text, (
        f"rejection must name the missing scope/phase, got {text!r}"
    )
    assert getattr(ctx.tool_state, "terminal_submission", None) is None
    assert ctx.tool_state.approval is None
    assert github.review_payloads == []


@pytest.mark.asyncio
async def test_phase_reaches_the_trace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``ReviewPhase`` appears on a span attr after a real tool advances it."""
    from mergecraft.mcp.verdict import ReviewPhase, stamp_review_phase_on_active_span
    from mergecraft.tracing import MemorySink, Tracer

    assert callable(stamp_review_phase_on_active_span)

    members = tuple(member.name for member in ReviewPhase)
    assert members == _PHASES, (
        f"ReviewPhase members must match the locked sequence, got {members!r}"
    )
    assert tuple(member.value for member in ReviewPhase) == _PHASES

    monkeypatch.delenv("MERGECRAFT_TEMP_DIR", raising=False)
    clone, head = _pr_clone(tmp_path)
    ctx = _ctx(tmp_path, repo_dir=clone)
    bind_github_client(ctx, _StubGitHub(head_sha=head))

    sink = MemorySink()
    tracer = Tracer(sink=sink, session_id="vp4-phase", run_id="vp4-phase-run")
    monkeypatch.setattr(
        "mergecraft.tracing.tracer.get_tracer_from_settings",
        lambda _settings: tracer,
    )

    with tracer.start_span("tool.call", attrs_source=lambda: {"tool.name": "checkout_pr"}):
        result = await checkout_pr_tool(ctx).execute({"pull_number": 1})
    assert result.is_error is False, _error_text(result)

    phase = getattr(ctx.tool_state, "review_phase", None)
    assert (
        phase is ReviewPhase.ESTABLISH_SCOPE or str(phase) == ReviewPhase.ESTABLISH_SCOPE.value
    ), f"checkout_pr must advance ReviewPhase to ESTABLISH_SCOPE, got {phase!r}"
    assert _phase_on_events(sink.events, ReviewPhase.ESTABLISH_SCOPE.value), (
        f"review.phase missing from span attrs after checkout_pr; events="
        f"{[getattr(e, 'attrs', None) for e in sink.events]!r}"
    )


@pytest.mark.asyncio
async def test_offline_scope_lets_the_terminal_verdict_be_recorded(tmp_path: Path) -> None:
    """#470: an offline run has no PR, so its diff is what establishes scope."""
    from mergecraft.mcp.tool_state import primary_repo_state
    from mergecraft.mcp.verdict import (
        ReviewPhase,
        establish_offline_review_scope,
        submit_review_verdict_tool,
    )

    ctx = _ctx(tmp_path)
    diff_path = tmp_path / "review.diff"
    diff_path.write_text("diff --git a/a.py b/a.py\n", encoding="utf-8")

    establish_offline_review_scope(ctx.tool_state, diff_path=str(diff_path))

    assert ctx.tool_state.review_phase == ReviewPhase.ESTABLISH_SCOPE.value
    assert primary_repo_state(ctx.tool_state).diff_path == str(diff_path)

    result = await submit_review_verdict_tool(ctx).execute(_valid_payload())
    assert result.is_error is not True, _error_text(result)
    assert ctx.tool_state.terminal_submission is not None


def test_scope_gate_accepts_a_materialized_diff_without_a_phase_transition(
    tmp_path: Path,
) -> None:
    """The gate's requirement is scope, not ``checkout_pr`` specifically (#470)."""
    from mergecraft.mcp.tool_state import primary_repo_state
    from mergecraft.mcp.verdict import ensure_review_scope_for_terminal

    ctx = _ctx(tmp_path)
    assert ctx.tool_state.review_phase == "INIT"
    with pytest.raises(ValueError, match="review scope"):
        ensure_review_scope_for_terminal(ctx.tool_state, "submit_review_verdict")

    primary_repo_state(ctx.tool_state).diff_path = str(tmp_path / "review.diff")
    ensure_review_scope_for_terminal(ctx.tool_state, "submit_review_verdict")
