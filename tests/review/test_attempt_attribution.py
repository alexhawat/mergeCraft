"""VP3 attempt attribution — V7 verdict freshness.

Wave plan: ``.ignorelocal/01-review-integrity-wave-plan.md`` (VP3 File 3,
VP3.2 impl; xfail markers cleared after VP3.2).

**V7**: bind the terminal verdict to the attempt that produced it. Stamp
``attempt_id`` when the model chain starts an attempt (beside
``fallback_index`` in ``utils/agent_resolve.py``), record it on
``TerminalSubmission``, and refuse to treat a structural result whose
``attempt_id`` does not match the current attempt as satisfying it.

Pairs with HA2 ``stale_attempt``: a result from a previous attempt must
not be reused by a later one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.agents.post_run import finalize_agent_result
from mergecraft.agents.shared import AgentResult, AgentRunContext, ResolvedInstructions
from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.tool_state import TerminalSubmission, init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request", issue_number=7, is_pr=True),
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
        trust_tier="trusted",
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


def _approve_payload() -> dict[str, str | list[object]]:
    return {
        "verdict": "approve",
        "summary": "No blocking issues in the diff.",
        "findings": [],
    }


@pytest.mark.asyncio
async def test_verdict_is_bound_to_its_attempt(tmp_path: Path) -> None:
    """V7: ``TerminalSubmission.attempt_id`` is the id stamped when the attempt starts.

    ``stamp_attempt_id`` lives beside ``fallback_index`` in
    ``utils/agent_resolve.py``. The recorder must copy that stamp onto
    the submission — not invent a second id at submit time.
    """
    from mergecraft.mcp.verdict import submit_review_verdict_tool
    from mergecraft.utils.agent_resolve import stamp_attempt_id

    ctx = _ctx(tmp_path)
    stamp_attempt_id(ctx.tool_state, attempt_id=2, fallback_index=2)
    assert ctx.tool_state.attempt_id == 2
    assert ctx.tool_state.fallback_index == 2

    result = await submit_review_verdict_tool(ctx).execute(_approve_payload())
    assert result.is_error is False
    recorded = ctx.tool_state.terminal_submission
    assert recorded is not None
    assert isinstance(recorded, TerminalSubmission)
    assert recorded.attempt_id == 2

    finalized = await finalize_agent_result(_run_ctx(ctx), AgentResult(success=True))
    assert finalized.terminal_submission_received is True
    assert finalized.diagnostics.get("attempt_id") == 2


@pytest.mark.asyncio
async def test_stale_structural_result_is_not_reused(tmp_path: Path) -> None:
    """A result whose ``attempt_id`` does not match the current attempt does not satisfy it.

    Guard-deletion: if the freshness check is removed, ``finalize_agent_result``
    would still set ``terminal_submission_received=True`` for a leftover
    attempt-0 submission while the chain is on attempt 1. Pairs with HA2
    ``stale_attempt``.
    """
    from mergecraft.mcp.verdict import verdict_satisfies_attempt
    from mergecraft.utils.agent_resolve import stamp_attempt_id

    ctx = _ctx(tmp_path)
    stale = TerminalSubmission(
        id="attempt-0-submission",
        verdict="approve",
        summary="cached review from attempt 0",
        findings=[],
        payload_hash="abc",
        submitted_at="2026-08-16T00:00:00+00:00",
        attempt_id=0,
    )
    ctx.tool_state.terminal_submission = stale
    stamp_attempt_id(ctx.tool_state, attempt_id=1, fallback_index=1)

    assert verdict_satisfies_attempt(stale, current_attempt_id=1) is False
    assert verdict_satisfies_attempt(stale, current_attempt_id=0) is True

    finalized = await finalize_agent_result(_run_ctx(ctx), AgentResult(success=True))
    assert finalized.terminal_submission_received is False, (
        "stale TerminalSubmission must not satisfy the current attempt"
    )
    assert finalized.terminal_submission_id is None
    assert finalized.diagnostics.get("rejection_reason") == "stale_attempt"
    assert finalized.diagnostics.get("attempt_id") == 0


# ── the receipt is bound to the verdict it published ─────────────────────────
#
# A fallback attempt keeps the previous attempt's ``tool_state.review`` receipt
# (``_prepare_chain_attempt`` clears only the submission). The receipt binds
# ``(pull_number, commit_id, verdict, fingerprints)`` where ``fingerprints`` is
# the sorted set of ``mergecraft-finding:v1`` markers in the published inline
# comments and body, and
# ``payload_hash = sha256(verdict + "\n" + "\n".join(sorted(fingerprints)))``.
#
# Against the final submission: the same verdict short-circuits (no second
# POST, the failure flag clears) and lists any submission finding missing from
# GitHub's inline view as ``publicationIncomplete``; a different verdict posts
# nothing, sets ``terminal_publication_mismatch`` and reads inconclusive naming
# both verdicts. GitHub cannot un-publish, and a second review would duplicate
# every inline thread.


def _payload_hash(verdict: str, fingerprints: set[str]) -> str:
    import hashlib

    material = verdict + "\n" + "\n".join(sorted(fingerprints))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _published_fingerprints(payload: dict[str, Any]) -> set[str]:
    from mergecraft.review_resolution import finding_fingerprints_in

    found = set(finding_fingerprints_in(str(payload.get("body") or "")))
    for comment in payload.get("comments") or []:
        found |= finding_fingerprints_in(str(comment.get("body") or ""))
    return found


def _attempt(ctx: ToolContext, index: int) -> None:
    """Start chain attempt ``index`` exactly as ``run_with_model_chain`` does."""
    from mergecraft.utils.agent_resolve import _prepare_chain_attempt

    _prepare_chain_attempt(ctx.tool_state, index)


def test_review_record_new_fields_default_to_none() -> None:
    """Edge: a receipt built from only (id, node_id, sha) states no verdict and no hash."""
    from mergecraft.mcp.tool_state import ReviewRecord

    record = ReviewRecord(id=1, node_id="n1", reviewed_sha="abc123")
    assert getattr(record, "verdict", "absent") is None
    assert getattr(record, "payload_hash", "absent") is None


@pytest.mark.asyncio
async def test_receipt_binds_verdict_and_finding_fingerprints(tmp_path: Path) -> None:
    """Happy path: the stored receipt names the verdict and hashes the published markers."""
    from mergecraft.mcp.review import publish_pull_request_review
    from tests.support.publication import (
        HEAD_SHA,
        RecordingReviewGitHub,
        finding,
        publication_ctx,
        submit_verdict,
    )

    github = RecordingReviewGitHub()
    ctx = publication_ctx(tmp_path, github=github, trust_tier="trusted")
    await submit_verdict(ctx, "request_changes", [finding("Unchecked index.")])

    await publish_pull_request_review(ctx)

    receipt = ctx.tool_state.review
    assert receipt is not None
    assert receipt.reviewed_sha == HEAD_SHA
    assert receipt.verdict == "request_changes"
    published = _published_fingerprints(github.review_payloads[0])
    assert published, "the published review must carry the finding marker"
    assert receipt.payload_hash == _payload_hash("request_changes", published)


@pytest.mark.parametrize(
    "entrypoint", ["publish_pull_request_review", "create_pull_request_review", "_publish"]
)
@pytest.mark.asyncio
async def test_a_different_verdict_on_the_same_head_is_never_skipped_as_success(
    tmp_path: Path, entrypoint: str
) -> None:
    """Error: attempt 1 published ``request_changes``; attempt 2 recorded ``approve``.

    No entrypoint may POST a second review, none may report the stale receipt
    as a successful skip, and the mismatch flag is set.
    """
    from mergecraft.mcp.review import (
        _publish_github_review,
        create_pull_request_review_tool,
        publish_pull_request_review,
    )
    from tests.support.publication import (
        RecordingReviewGitHub,
        finding,
        publication_ctx,
        submit_verdict,
    )

    github = RecordingReviewGitHub()
    ctx = publication_ctx(tmp_path, github=github, trust_tier="trusted")
    await submit_verdict(ctx, "request_changes", [finding("Unchecked index.")])
    await publish_pull_request_review(ctx)
    assert len(github.review_payloads) == 1

    _attempt(ctx, 1)
    assert ctx.tool_state.review is not None, "the receipt survives the fallback"
    await submit_verdict(ctx, "approve")

    if entrypoint == "publish_pull_request_review":
        response: dict[str, Any] = await publish_pull_request_review(ctx)
        skipped_as_success = response.get("success") is True and response.get("skipped") is True
    elif entrypoint == "create_pull_request_review":
        submission = ctx.tool_state.terminal_submission
        assert submission is not None
        result = await create_pull_request_review_tool(ctx).execute(
            {"pull_number": 7, "body": submission.summary, "approved": True}
        )
        if result.is_error:
            skipped_as_success = False
        else:
            import json

            body = json.loads(result.content[0]["text"])
            skipped_as_success = body.get("success") is True and body.get("skipped") is True
    else:
        response = await _publish_github_review(ctx, {"pull_number": 7})
        skipped_as_success = response.get("success") is True and response.get("skipped") is True

    assert len(github.review_payloads) == 1, "a mismatched attempt must not POST a second review"
    assert skipped_as_success is False, "the stale receipt was reported as a successful skip"
    assert ctx.tool_state.terminal_publication_mismatch is True


@pytest.mark.asyncio
async def test_a_different_verdict_reads_inconclusive_naming_both_verdicts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end through Phase 4: GitHub shows attempt 1's verdict, the run says so."""
    from mergecraft.mcp.review import publish_pull_request_review
    from mergecraft.run_outcome import RunOutcome
    from tests.support.finalize_harness import run_finalize
    from tests.support.publication import (
        RecordingReviewGitHub,
        finding,
        publication_ctx,
        submit_verdict,
    )

    github = RecordingReviewGitHub()
    ctx = publication_ctx(tmp_path, github=github, trust_tier="trusted")
    await submit_verdict(ctx, "request_changes", [finding("Unchecked index.")])
    await publish_pull_request_review(ctx)
    _attempt(ctx, 1)
    await submit_verdict(ctx, "approve")

    record = await run_finalize(ctx, monkeypatch=monkeypatch)

    assert len(github.review_payloads) == 1
    assert ctx.tool_state.terminal_publication_mismatch is True
    assert record.outcome is RunOutcome.inconclusive
    reason = record.failure_reason or ""
    assert "request_changes" in reason
    assert "approve" in reason


@pytest.mark.asyncio
async def test_same_verdict_with_a_different_inline_set_short_circuits_and_lists_the_gap(
    tmp_path: Path,
) -> None:
    """Edge: same verdict, one more finding -> no second POST; the gap is named, not hidden."""
    from mergecraft.mcp.review import publish_pull_request_review
    from tests.support.publication import (
        RecordingReviewGitHub,
        finding,
        publication_ctx,
        submission_fingerprints,
        submit_verdict,
    )

    github = RecordingReviewGitHub()
    ctx = publication_ctx(tmp_path, github=github, trust_tier="trusted")
    await submit_verdict(ctx, "request_changes", [finding("Unchecked index.")])
    first = submission_fingerprints(ctx)
    await publish_pull_request_review(ctx)
    ctx.tool_state.terminal_publication_failed = True  # a later attempt's retryable failure

    _attempt(ctx, 1)
    await submit_verdict(
        ctx,
        "request_changes",
        [finding("Unchecked index."), finding("Missing timeout.", line=20)],
    )
    missing = sorted(submission_fingerprints(ctx) - first)
    assert len(missing) == 1

    response = await publish_pull_request_review(ctx)

    assert len(github.review_payloads) == 1
    assert ctx.tool_state.terminal_publication_failed is False
    assert ctx.tool_state.terminal_publication_mismatch is False
    assert response.get("publicationIncomplete") == missing
    assert list(ctx.tool_state.publication_incomplete) == missing


@pytest.mark.asyncio
async def test_matching_receipt_records_no_publication_gap(tmp_path: Path) -> None:
    """Edge: identical verdict and findings -> short-circuit with an empty gap."""
    from mergecraft.mcp.review import publish_pull_request_review
    from tests.support.publication import (
        RecordingReviewGitHub,
        finding,
        publication_ctx,
        submit_verdict,
    )

    github = RecordingReviewGitHub()
    ctx = publication_ctx(tmp_path, github=github, trust_tier="trusted")
    await submit_verdict(ctx, "request_changes", [finding("Unchecked index.")])
    await publish_pull_request_review(ctx)

    replay = await publish_pull_request_review(ctx)

    assert len(github.review_payloads) == 1
    assert replay.get("skipped") is True
    assert not replay.get("publicationIncomplete")
    assert ctx.tool_state.terminal_publication_mismatch is False
    assert list(ctx.tool_state.publication_incomplete) == []


@pytest.mark.parametrize("order", ["publish_then_submit", "submit_then_publish"])
@pytest.mark.asyncio
async def test_an_agent_published_review_with_the_same_verdict_is_not_a_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, order: str
) -> None:
    """The agent posted its own comment bodies; the recorded verdict is the same.

    Agent-built bodies never byte-equal a submission-derived rendering, which
    is why the receipt hashes verdict + fingerprints rather than payload bytes.
    No second POST, and the run is not inconclusive.
    """
    from mergecraft.mcp.review import create_pull_request_review_tool
    from mergecraft.run_outcome import RunOutcome
    from tests.support.finalize_harness import run_finalize
    from tests.support.publication import (
        RecordingReviewGitHub,
        finding,
        publication_ctx,
        submit_verdict,
    )

    github = RecordingReviewGitHub()
    ctx = publication_ctx(tmp_path, github=github, trust_tier="trusted")
    agent_comment = {
        "path": "src/app.py",
        "line": 12,
        "body": "Please guard this index — an empty list crashes the handler here.",
    }
    if order == "publish_then_submit":
        published = await create_pull_request_review_tool(ctx).execute(
            {
                "pull_number": 7,
                "body": "Requesting changes.",
                "request_changes": True,
                "comments": [agent_comment],
            }
        )
        assert published.is_error is False
        _attempt(ctx, 1)
        await submit_verdict(ctx, "request_changes", [finding("Unchecked index.")])
    else:
        await submit_verdict(ctx, "request_changes", [finding("Unchecked index.")])
        submission = ctx.tool_state.terminal_submission
        assert submission is not None
        published = await create_pull_request_review_tool(ctx).execute(
            {
                "pull_number": 7,
                "body": submission.summary,
                "request_changes": True,
                "comments": [agent_comment],
            }
        )
        assert published.is_error is False
    assert len(github.review_payloads) == 1

    record = await run_finalize(ctx, monkeypatch=monkeypatch)

    assert len(github.review_payloads) == 1
    assert ctx.tool_state.terminal_publication_mismatch is False
    assert record.outcome is RunOutcome.passed
