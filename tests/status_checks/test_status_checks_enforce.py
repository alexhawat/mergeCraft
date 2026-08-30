"""W8 GREEN suite for #75 — enforce-path tests (D13, D14).

These tests pin the *enforce* contract W8 satisfies:

- W7.3 (D13): a crashed / timed-out / no-findings run yields an
  ``mergecraft-approval`` conclusion that the hardened enforce step
  treats as blocking. The wire-shape is ``"neutral"`` — the W8 README
  copy replaces the current "neutral is non-blocking" framing.

- W7.4 (D14): a fork PR with ``prApproveEnabled=True`` cannot produce
  an ``APPROVE`` review event. The inert behaviour is asserted at
  *two* layers because the gate has two enforcement points:

  1. The decision function (``decide_approval``) — untrusted tier
     produces ``"failure"`` (or another non-``success`` shape) even
     when the agent's approval boolean is True.
  2. The MCP tool ``create_pull_request_review`` — untrusted tier
     never sends ``event="APPROVE"`` to GitHub regardless of
     ``pr_approve_enabled`` and the agent's boolean.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.analyzers.finding import Finding
from mergecraft.analyzers.trust import derive_trust_tier

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


# ---------------------------------------------------------------------------
# Module-availability helpers — same pattern as test_decide_approval.py.
# ---------------------------------------------------------------------------


def _decide_approval() -> Callable[..., Any]:
    """Return ``decide_approval`` from the W8 module it lives in."""
    from mergecraft.agents import gates as _gates

    fn = getattr(_gates, "decide_approval", None)
    if fn is None:  # pragma: no cover - W8 ships this
        msg = (
            "decide_approval is not defined in mergecraft.agents.gates "
            "(W8 deliverable — this fixture requires it)"
        )
        raise AttributeError(msg)
    return fn


def _status_checks_module() -> Any:
    """Return ``mergecraft.utils.status_checks`` for the enforce tests."""
    from mergecraft.utils import status_checks as _sc

    return _sc


def _context_class() -> Any:
    """Return ``ToolContext`` (lazy to keep collection lenient)."""
    from mergecraft.mcp.context import ToolContext

    return ToolContext


def _context_factory() -> Any:
    """Return the ``ToolContext`` constructor and event/payload types."""
    from mergecraft.mcp.context import (
        PayloadEvent,
        RepoIdentity,
        ResolvedPayload,
        ToolContext,
    )

    return ToolContext, PayloadEvent, RepoIdentity, ResolvedPayload


# ---------------------------------------------------------------------------
# W7.3 — crashed / timed-out run does not leave a permissive gate
# ---------------------------------------------------------------------------


def test_crashed_run_does_not_leave_permissive_gate() -> None:
    """A run that raises or times out yields a conclusion the hardened
    enforce step treats as blocking (D13).

    The decision function is invoked with ``run_succeeded=False`` and
    no findings. The result must be ``"neutral"`` — the wire-shape the
    enforced step (W8.4) treats as blocking. It must not be
    ``"success"`` because the run never completed.
    """
    decide = _decide_approval()
    _ = _status_checks_module()  # ensures the module is importable

    conclusion = decide(
        [],
        run_succeeded=False,
        tier="trusted",
    )

    assert conclusion == "neutral", (
        "a crashed run must not produce 'success' — the hardened enforce "
        "step treats 'neutral' as blocking (D13)"
    )
    # The conftest imports ensure this is in scope.
    assert conclusion in ("success", "failure", "neutral")
    assert conclusion is not None


def test_timed_out_run_with_findings_yields_failure() -> None:
    """A timed-out run that *did* record a blocker before timing out must
    still surface ``failure``. The decision is the monotone-OR of run
    state and findings: a failed run with blockers is ``failure``."""
    decide = _decide_approval()

    blocker = Finding.model_validate(
        {
            "tool": "w7-fixture",
            "rule_id": "W7-TIMEOUT",
            "category": "Security & Privacy",
            "severity": "Major",
            "confidence": "certain",
            "message": "Auth bypass present.",
            "path": "src/foo.py",
            "start_line": 1,
            "end_line": 10,
            "fingerprint": "w7-timeout-mjr",
            "evidence": ["line 1: ..."],
            "remediation": "Add the auth check.",
            "autofix": None,
            "introduced_by_pr": "true",
            "source": "agent",
            "cluster_id": None,
        }
    )

    conclusion = decide(
        [blocker],
        run_succeeded=False,
        tier="trusted",
    )

    assert conclusion == "failure", "a timed-out run with a blocker finding must surface 'failure'"


async def test_report_status_checks_surfaces_neutral_for_crashed_run(
    tmp_path: Path,
) -> None:
    """Wired through ``report_status_checks``: the approve check posts
    ``"neutral"`` when the run did not succeed, even if the agent
    previously recorded ``ApprovalRecord(would_approve=True)``.

    The hardened enforce step (W8.4) treats ``"neutral"`` as blocking.
    """
    import httpx

    from mergecraft.evidence.run_packet import prepare_run_packet
    from mergecraft.mcp.tool_state import ApprovalRecord, init_tool_state
    from mergecraft.modes import compute_modes
    from mergecraft.utils.github import GitHubClient

    sc = _status_checks_module()

    class _RecordingGitHub(GitHubClient):
        def __init__(self) -> None:
            super().__init__(token="test-token")
            self.check_runs: list[dict[str, Any]] = []
            self.review_payload: dict[str, Any] = {}

        async def get_pull(self, owner: str, repo: str, pull_number: int) -> dict[str, Any]:
            return {"head": {"sha": "deadbeef" * 5}}

        async def post(self, path: str, **kwargs: Any) -> Any:
            if path.endswith("/check-runs"):
                body = kwargs.get("json")
                if isinstance(body, dict):
                    self.check_runs.append(body)
            return {}

        async def create_review(
            self, owner: str, repo: str, pull_number: int, **payload: Any
        ) -> dict[str, Any]:
            self.review_payload = payload
            return {"id": 1, "node_id": "n1", "html_url": "https://x/1", "state": "COMMENTED"}

    ToolContext, PayloadEvent, RepoIdentity, ResolvedPayload = _context_factory()

    github = _RecordingGitHub()
    tool_state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    # Simulate the agent having called create_pull_request_review(approved=True)
    # before the run was killed.
    tool_state.approval = ApprovalRecord(would_approve=True, sha="deadbeef")
    ctx = ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request", issue_number=42, is_pr=True),
            status_checks=True,
        ),
        github=github,
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=tool_state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
    )

    # Even though the agent's stored boolean says "approved", the run
    # crashed — the post-W8 rewire must consult the decision function
    # and surface ``"neutral"`` for the mergecraft-approval check.
    await sc.report_status_checks(
        ctx,
        run_succeeded=False,
        packet=prepare_run_packet(ctx, run_succeeded=False),
    )

    approve_checks = [run for run in github.check_runs if run.get("name") == sc.APPROVAL_CHECK]
    assert len(approve_checks) == 1
    assert approve_checks[0]["conclusion"] == "neutral", (
        "a crashed run must not propagate ApprovalRecord.would_approve "
        "into a 'success' check — the structural gate is the source of "
        "truth (D13, D12)"
    )

    # Drop the unused import hint so ruff does not flag it.
    _ = httpx.__name__


# ---------------------------------------------------------------------------
# W7.4 — fork PR cannot self-approve (D14)
# ---------------------------------------------------------------------------


def test_fork_pr_cannot_self_approve_at_decision_layer(
    blocked_pr_event: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``derive_trust_tier()`` returns ``"untrusted"`` for a fork PR, and
    ``prApproveEnabled=true`` ⇒ no approval, regardless of config (D14).

    The decision function is the structural source of truth. With
    ``tier="untrusted"`` and a clean (no-blocker) finding list, the
    conclusion must not be ``"success"`` — it must be ``"failure"`` or
    ``"neutral"`` (the exact shape is W8's call; the contract is *not*
    success).
    """
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    tier = derive_trust_tier(blocked_pr_event)
    assert tier == "untrusted", (
        "sanity: a fork PR event must be tier='untrusted' before we assert the inert path"
    )

    decide = _decide_approval()
    conclusion = decide(
        [],
        run_succeeded=True,
        tier=tier,
    )

    assert conclusion != "success", (
        "an untrusted tier must never produce 'success' — even with "
        "no blockers and a successful run, the gate is inert for "
        "fork PRs and pull_request_target (D14)"
    )
    assert conclusion in ("failure", "neutral")


async def test_fork_pr_cannot_self_approve_at_tool_layer(
    tmp_path: Path,
) -> None:
    """Mirror of the above at the create_pull_request_review tool layer.

    With ``pr_approve_enabled=True`` *and* the agent's
    ``approved=True`` argument, the tool must NOT send
    ``event="APPROVE"`` to GitHub when the trust tier is ``untrusted``.
    The current behaviour (W7 source) sends ``event="APPROVE"`` —
    W8.5 makes the flag inert for untrusted runs.
    """
    import httpx

    from mergecraft.mcp.review import create_pull_request_review_tool
    from mergecraft.mcp.tool_state import init_tool_state
    from mergecraft.modes import compute_modes
    from mergecraft.utils.github import GitHubClient

    ToolContext, PayloadEvent, RepoIdentity, ResolvedPayload = _context_factory()

    class _RecordingGitHub(GitHubClient):
        def __init__(self) -> None:
            super().__init__(token="test-token")
            self.review_payloads: list[dict[str, Any]] = []

        async def create_review(
            self, owner: str, repo: str, pull_number: int, **payload: Any
        ) -> dict[str, Any]:
            self.review_payloads.append(payload)
            return {"id": 1, "node_id": "n1", "html_url": "https://x/1", "state": "COMMENTED"}

    github = _RecordingGitHub()
    ctx = ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request", issue_number=7, is_pr=True)
        ),
        github=github,
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_server_url="",
        tmpdir=str(tmp_path),
        pr_approve_enabled=True,
        trust_tier="untrusted",
    )

    spec = create_pull_request_review_tool(ctx)
    result = await spec.execute(
        {"pull_number": 7, "body": "Looks good.", "approved": True},
    )
    assert result.is_error is True
    assert any("authority trust" in block.get("text", "") for block in result.content)

    sent_events = [p.get("event") for p in github.review_payloads]
    assert "APPROVE" not in sent_events, (
        "create_pull_request_review must not send event='APPROVE' on "
        "untrusted runs, even with pr_approve_enabled=True and "
        "approved=True — D14 enforces one config knob, one inert path"
    )
    assert ctx.tool_state.approval is None

    _ = httpx.__name__


async def test_in_repo_pr_with_pr_approve_enabled_can_self_approve(
    tmp_path: Path,
) -> None:
    """Regression guard for D14: the inert path applies to *untrusted*
    only. An in-repo PR with ``pr_approve_enabled=True`` and
    ``approved=True`` must still send ``event="APPROVE"``.

    This is the pin-side of the test: D14 is "make untrusted inert",
    not "remove approval entirely".
    """
    from mergecraft.mcp.review import create_pull_request_review_tool
    from mergecraft.mcp.tool_state import init_tool_state
    from mergecraft.modes import compute_modes
    from mergecraft.utils.github import GitHubClient

    ToolContext, PayloadEvent, RepoIdentity, ResolvedPayload = _context_factory()

    class _RecordingGitHub(GitHubClient):
        def __init__(self) -> None:
            super().__init__(token="test-token")
            self.review_payloads: list[dict[str, Any]] = []

        async def create_review(
            self, owner: str, repo: str, pull_number: int, **payload: Any
        ) -> dict[str, Any]:
            self.review_payloads.append(payload)
            return {"id": 1, "node_id": "n1", "html_url": "https://x/1", "state": "COMMENTED"}

    github = _RecordingGitHub()
    ctx = ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request", issue_number=7, is_pr=True)
        ),
        github=github,
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

    spec = create_pull_request_review_tool(ctx)
    await spec.execute(
        {"pull_number": 7, "body": "Looks good.", "approved": True},
    )

    sent_events = [p.get("event") for p in github.review_payloads]
    assert sent_events == ["APPROVE"], (
        "regression guard: a trusted in-repo PR with pr_approve_enabled "
        "and approved=True must still post event='APPROVE' — D14 only "
        "inert on untrusted tier"
    )
