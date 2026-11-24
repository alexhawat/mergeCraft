"""``review_event: comment`` — an advisory reviewer can neither block nor unblock a merge.

Contracts:

- every verdict is published as a ``COMMENT`` review (never ``REQUEST_CHANGES``
  or ``APPROVE``), while the recorded verdict still binds the run's receipt;
- the run resolves no review threads: the automatic retirement of fixed
  findings after the review is skipped (the agent's ``resolve_review_thread``
  tool is already default-denied in every review mode);
- the default (unset, or ``verdict``) keeps today's event selection;
- an unknown value is a ``configuration_error`` before the agent starts, so a
  misspelt ``comment`` cannot quietly publish a blocking review.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import pytest
from tests.support.publication import (
    RecordingReviewGitHub,
    finding,
    publication_ctx,
    review_thread,
    submit_verdict,
    unified_diff,
)
from tests.support.run_main_harness import FakeAgent, run_main_for_test

import mergecraft.main as main_mod
from mergecraft.action.inputs import resolve_review_event
from mergecraft.config.settings import RepoSettings
from mergecraft.mcp.review import create_pull_request_review_tool
from mergecraft.mcp.tool_state import primary_repo_state
from mergecraft.review_taxonomy import stamp_finding_fingerprint
from mergecraft.run_outcome import RunOutcome

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext

_APP_BOT = "mergecraft-app[bot]"
_OLD = stamp_finding_fingerprint(path="src/app.py", body="Old finding.")
_BODY = "Verified Major: the retry loop never backs off."


def _ctx(
    tmp_path: Path,
    *,
    comment_only: bool,
    pr_approve_enabled: bool = False,
    threads: list[dict[str, Any]] | None = None,
) -> tuple[ToolContext, RecordingReviewGitHub]:
    github = RecordingReviewGitHub(threads=threads, reviewer_login=_APP_BOT)
    ctx = publication_ctx(
        tmp_path,
        github=github,
        trust_tier="trusted",
        mode="IncrementalReview" if threads is not None else "Review",
        pr_approve_enabled=pr_approve_enabled,
    )
    ctx.comment_only_review = comment_only
    return ctx, github


async def _publish(ctx: ToolContext) -> Any:
    return await create_pull_request_review_tool(ctx).execute(
        {"pull_number": 7, "body": "review", "comments": []}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("verdict", ["request_changes", "approve"])
async def test_comment_only_publishes_every_verdict_as_a_comment(
    tmp_path: Path, verdict: Literal["approve", "request_changes"]
) -> None:
    ctx, github = _ctx(tmp_path, comment_only=True, pr_approve_enabled=True)
    findings = [finding(_BODY)] if verdict == "request_changes" else []
    await submit_verdict(ctx, verdict, findings)

    await _publish(ctx)

    assert [payload["event"] for payload in github.review_payloads] == ["COMMENT"]
    receipt = ctx.tool_state.review
    assert receipt is not None
    assert receipt.verdict == verdict, "the recorded verdict must still bind the receipt"


@pytest.mark.asyncio
async def test_verdict_mode_still_requests_changes(tmp_path: Path) -> None:
    """Green guard: without the advisory mode the event follows the verdict."""
    ctx, github = _ctx(tmp_path, comment_only=False)
    await submit_verdict(ctx, "request_changes", [finding(_BODY)])

    await _publish(ctx)

    assert [payload["event"] for payload in github.review_payloads] == ["REQUEST_CHANGES"]


def _incremental(ctx: ToolContext, tmp_path: Path) -> None:
    primary = primary_repo_state(ctx.tool_state)
    primary.incremental_changed_paths = ["src/app.py"]
    incremental_path = tmp_path / "incremental.patch"
    incremental_path.write_text(unified_diff("src/app.py", start=40, count=5), encoding="utf-8")
    primary.incremental_diff_path = str(incremental_path)
    ctx.publisher_logins = frozenset({_APP_BOT})


@pytest.mark.asyncio
@pytest.mark.parametrize(("comment_only", "expected"), [(True, []), (False, ["T-line42"])])
async def test_comment_only_resolves_no_fixed_finding_threads(
    tmp_path: Path, comment_only: bool, expected: list[str]
) -> None:
    """The finding's line changed and it is gone; only the verdict mode retires it."""
    threads = [review_thread(thread_id="T-line42", body=_OLD, author=_APP_BOT, line=42)]
    ctx, github = _ctx(tmp_path, comment_only=comment_only, threads=threads)
    _incremental(ctx, tmp_path)

    await create_pull_request_review_tool(ctx).execute(
        {
            "pull_number": 7,
            "body": "re-review",
            "comments": [{"path": "src/app.py", "line": 12, "body": "A different finding."}],
        }
    )

    assert github.resolved == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, "verdict"), ("", "verdict"), ("verdict", "verdict"), (" Comment ", "comment")],
)
def test_review_event_resolution(
    monkeypatch: pytest.MonkeyPatch, raw: str | None, expected: str
) -> None:
    if raw is None:
        monkeypatch.delenv("INPUT_REVIEW_EVENT", raising=False)
    else:
        monkeypatch.setenv("INPUT_REVIEW_EVENT", raw)
    assert resolve_review_event() == expected


def test_unknown_review_event_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INPUT_REVIEW_EVENT", "coment")
    with pytest.raises(ValueError, match="unknown review_event"):
        resolve_review_event()


async def _run_main(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, review_event: str
) -> tuple[Any, FakeAgent]:
    # The privilege drop needs the action image's ``mergecraft`` user; it is not
    # what this contract is about, so it is stubbed (root developer machines
    # and containers would otherwise stop the run before input validation).
    monkeypatch.setattr(main_mod, "prepare_workspace_for_agent", lambda _workspace: None)
    agent = FakeAgent()
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=RepoSettings(),
        env={
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "INPUT_REVIEW_EVENT": review_event,
            "MERGECRAFT_ALLOW_ROOT": "1",
        },
        event_name="workflow_dispatch",
        event_payload={"action": "workflow_dispatch"},
        agent=agent,
    )
    assert rec.result is not None
    return rec, agent


async def test_unknown_review_event_fails_closed_before_the_agent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rec, _agent = await _run_main(monkeypatch, tmp_path, "coment")

    assert rec.result.outcome is RunOutcome.configuration_error
    assert "unknown review_event: 'coment'" in str(rec.result.error or ""), rec.result.error
    assert rec.agent_runs == [], "the agent must not start under an unknown review_event"


async def test_comment_review_event_runs_the_agent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Green guard: the harness reaches the agent when the value is valid."""
    rec, _agent = await _run_main(monkeypatch, tmp_path, "comment")

    assert rec.agent_runs, f"a valid review_event must not stop the run: {rec.result.error!r}"
