"""A review recovered after its create response was lost is bound from GitHub's state.

When a publish attempt's response is lost, the run recovers the review GitHub
accepted (a trusted bot review carrying the deterministic-record marker and this
run's URL). What this run *sent* is not proof of what GitHub *accepted*, so the
recovered receipt is bound from what GitHub shows:

* ``verdict`` from the review state: ``APPROVED`` -> ``approve``,
  ``CHANGES_REQUESTED`` -> ``request_changes``; anything else proves no verdict;
* ``inline_fingerprints`` from the review's listed inline comments, or ``None``
  when that list cannot be read in full (unknown is not "none inline");
* ``payload_hash`` only when both the verdict and the inline set are known;
* ``reviewed_sha`` from the review's ``commit_id``, else the head searched for.

A verdict-less receipt on the head is not a receipt for the recorded verdict:
the run is ``inconclusive`` with its own "unproven" reason, and the record says
so. No path posts a second review.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest

from mergecraft.agents.shared import AgentResult
from mergecraft.findings.ledger import DETERMINISTIC_RECORD_MARKER, REVIEW_BODY_MARKER
from mergecraft.main_outcome import (
    _NO_RECEIPT_TERMINAL_VERDICT_REASON,
    _UNPROVEN_RECEIPT_TERMINAL_VERDICT_REASON,
    _classify_outcome,
    _publication_outcome_inputs,
    _publication_unproven,
)
from mergecraft.mcp.review import (
    _recovered_receipt,
    _recovered_review_inline_comments,
    _recovered_review_verdict,
    publish_pull_request_review,
)
from mergecraft.mcp.tool_state import ReviewRecord, TerminalSubmission, init_tool_state
from mergecraft.review_taxonomy import stamp_finding_fingerprint
from mergecraft.run_outcome import RunOutcome
from mergecraft.utils.github import GITHUB_LIST_MAX_PAGES
from mergecraft.utils.status_checks import _run_url
from tests.support.finalize_harness import run_finalize
from tests.support.publication import (
    HEAD_SHA,
    RecordingReviewGitHub,
    finding,
    publication_ctx,
    submit_verdict,
)
from tests.support.tool_context import make_tool_context

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.mcp.context import ToolContext
    from mergecraft.scm.protocol import ScmProvider

_RECOVERED_ID = 99
_RUN_ID = 42
_MARKED_A = stamp_finding_fingerprint(path="src/app.py", body="Unchecked index.")
_MARKED_B = stamp_finding_fingerprint(path="src/app.py", body="Missing timeout.")


def _fingerprint(stamped: str) -> str:
    from mergecraft.review_resolution import finding_fingerprints_in

    return next(iter(finding_fingerprints_in(stamped)))


def _hash(verdict: str, fingerprints: set[str]) -> str:
    material = verdict + "\n" + "\n".join(sorted(fingerprints))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


# ── the review state proves the verdict ───────────────────────────────────────


@pytest.mark.parametrize(
    ("state", "verdict"),
    [
        ("APPROVED", "approve"),
        ("CHANGES_REQUESTED", "request_changes"),
        ("approved", "approve"),
        ("  changes_requested \n", "request_changes"),
        ("COMMENTED", None),
        ("DISMISSED", None),
        ("PENDING", None),
        ("", None),
        (None, None),
    ],
)
def test_recovered_review_state_maps_to_the_verdict_it_proves(
    state: str | None, verdict: str | None
) -> None:
    assert _recovered_review_verdict({"id": 1, "state": state}) == verdict


def test_a_recovered_review_without_a_state_proves_no_verdict() -> None:
    assert _recovered_review_verdict({"id": 1}) is None


# ── the inline comments GitHub shows, or unknown ──────────────────────────────


class _CommentsScm:
    """Answers the recovered review's inline-comment listing as scripted."""

    def __init__(self, pages: Any) -> None:
        self._pages = pages
        self.requests: list[tuple[str, dict[str, Any]]] = []

    async def get(self, path: str, *, params: dict[str, Any] | None = None, **_: Any) -> Any:
        self.requests.append((path, dict(params or {})))
        if isinstance(self._pages, BaseException):
            raise self._pages
        if callable(self._pages):
            return self._pages(dict(params or {}))
        return self._pages


def _comments_ctx(tmp_path: Path, pages: Any) -> tuple[ToolContext, _CommentsScm]:
    scm = _CommentsScm(pages)
    ctx = make_tool_context(tmp_path, trust_tier="trusted", scm=cast("ScmProvider", scm))
    return ctx, scm


def _full_page(params: dict[str, Any]) -> list[dict[str, Any]]:
    per_page = int(params.get("per_page", 30))
    return [{"id": n, "body": "x"} for n in range(per_page)]


async def test_recovered_inline_comments_are_listed_from_the_review_endpoint(
    tmp_path: Path,
) -> None:
    comments = [{"id": 1, "body": _MARKED_A}, {"id": 2, "body": "plain"}]
    ctx, scm = _comments_ctx(tmp_path, comments)

    listed = await _recovered_review_inline_comments(ctx, pull_number=7, review_id=_RECOVERED_ID)

    assert listed == comments
    assert scm.requests[0][0] == f"/repos/acme/demo/pulls/7/reviews/{_RECOVERED_ID}/comments"


async def test_a_readable_empty_listing_is_an_empty_list_not_unknown(tmp_path: Path) -> None:
    ctx, _scm = _comments_ctx(tmp_path, [])
    assert await _recovered_review_inline_comments(ctx, pull_number=7, review_id=1) == []


@pytest.mark.parametrize(
    "pages",
    [
        pytest.param(RuntimeError("boom"), id="scm_raises"),
        pytest.param(
            httpx.HTTPStatusError(
                "502",
                request=httpx.Request("GET", "https://api.github.com/x"),
                response=httpx.Response(502, request=httpx.Request("GET", "https://x")),
            ),
            id="http_error",
        ),
        pytest.param({"message": "Not Found"}, id="object_page"),
        pytest.param("garbage", id="string_page"),
        pytest.param(_full_page, id="page_cap"),
    ],
)
async def test_an_unreadable_inline_listing_is_unknown_never_empty(
    tmp_path: Path, pages: Any
) -> None:
    ctx, scm = _comments_ctx(tmp_path, pages)

    listed = await _recovered_review_inline_comments(ctx, pull_number=7, review_id=1)

    assert listed is None
    if pages is _full_page:
        assert len(scm.requests) == GITHUB_LIST_MAX_PAGES


# ── the recovered receipt ─────────────────────────────────────────────────────


def _recovered(state: str, *, commit_id: str | None = HEAD_SHA, body: str = "") -> dict[str, Any]:
    review: dict[str, Any] = {
        "id": _RECOVERED_ID,
        "node_id": f"n{_RECOVERED_ID}",
        "state": state,
        "body": body,
    }
    if commit_id is not None:
        review["commit_id"] = commit_id
    return review


async def test_a_recovered_approval_binds_verdict_inline_set_and_hash(tmp_path: Path) -> None:
    body_marker = stamp_finding_fingerprint(path="src/app.py", body="Body-only finding.")
    ctx, _scm = _comments_ctx(tmp_path, [{"body": _MARKED_A}, {"body": _MARKED_B}])

    receipt = await _recovered_receipt(
        ctx, _recovered("APPROVED", body=body_marker), pull_number=7, commit_id="searched"
    )

    inline = {_fingerprint(_MARKED_A), _fingerprint(_MARKED_B)}
    assert receipt.id == _RECOVERED_ID
    assert receipt.node_id == f"n{_RECOVERED_ID}"
    assert receipt.verdict == "approve"
    assert receipt.reviewed_sha == HEAD_SHA
    assert receipt.inline_fingerprints == tuple(sorted(inline))
    # The hash binds the body markers too; the inline set lists only inline ones.
    assert receipt.payload_hash == _hash("approve", inline | {_fingerprint(body_marker)})


async def test_a_recovered_comment_review_proves_no_verdict_and_has_no_hash(
    tmp_path: Path,
) -> None:
    ctx, _scm = _comments_ctx(tmp_path, [{"body": _MARKED_A}])

    receipt = await _recovered_receipt(ctx, _recovered("COMMENTED"), pull_number=7, commit_id=None)

    assert receipt.verdict is None
    assert receipt.payload_hash is None
    assert receipt.inline_fingerprints == (_fingerprint(_MARKED_A),)
    assert receipt.reviewed_sha == HEAD_SHA


async def test_an_unreadable_inline_set_leaves_fingerprints_and_hash_unknown(
    tmp_path: Path,
) -> None:
    ctx, _scm = _comments_ctx(tmp_path, RuntimeError("boom"))

    receipt = await _recovered_receipt(
        ctx, _recovered("CHANGES_REQUESTED"), pull_number=7, commit_id=HEAD_SHA
    )

    assert receipt.verdict == "request_changes"
    assert receipt.inline_fingerprints is None
    assert receipt.payload_hash is None


@pytest.mark.parametrize("commit_id", [None, ""], ids=["missing", "empty"])
async def test_reviewed_sha_falls_back_to_the_searched_head(
    tmp_path: Path, commit_id: str | None
) -> None:
    ctx, _scm = _comments_ctx(tmp_path, [])

    receipt = await _recovered_receipt(
        ctx, _recovered("APPROVED", commit_id=commit_id), pull_number=7, commit_id="searched-head"
    )

    assert receipt.reviewed_sha == "searched-head"


def test_review_record_inline_fingerprints_default_empty_and_may_be_unknown() -> None:
    assert ReviewRecord(id=1, node_id="n1", reviewed_sha="abc").inline_fingerprints == ()
    unknown = ReviewRecord(id=1, node_id="n1", reviewed_sha="abc", inline_fingerprints=None)
    assert unknown.inline_fingerprints is None


# ── what counts as a receipt ──────────────────────────────────────────────────


def _review_state(tmp_path: Path, review: ReviewRecord | None, *, mode: str = "Review") -> Any:
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    state.selected_mode = mode
    state.review = review
    state.terminal_submission = TerminalSubmission(
        id="s1",
        verdict="approve",
        summary="Looks good.",
        findings=[],
        payload_hash="h",
        submitted_at="2026-09-27T00:00:00+00:00",
        attempt_id=0,
    )
    return state


def _received() -> AgentResult:
    return AgentResult(success=True, terminal_submission_received=True)


@pytest.mark.parametrize(
    ("review", "receipt"),
    [
        (ReviewRecord(id=1, node_id="n", reviewed_sha=HEAD_SHA, verdict="approve"), True),
        (ReviewRecord(id=1, node_id="n", reviewed_sha=HEAD_SHA, verdict=None), False),
        (ReviewRecord(id=1, node_id="n", reviewed_sha=None, verdict=None), False),
        (None, False),
    ],
    ids=["verdict_bound", "verdict_less_on_head", "diagnostic_record", "none"],
)
def test_only_a_verdict_bound_review_counts_as_a_receipt(
    tmp_path: Path, review: ReviewRecord | None, receipt: bool
) -> None:
    state = _review_state(tmp_path, review)
    assert _publication_outcome_inputs(state, result=_received(), verdict_protocol="enforce") == (
        receipt,
        None,
    )


def test_receipt_inputs_are_not_applicable_outside_the_enforced_review_path(
    tmp_path: Path,
) -> None:
    review = ReviewRecord(id=1, node_id="n", reviewed_sha=HEAD_SHA, verdict=None)
    shadow = _review_state(tmp_path, review)
    assert _publication_outcome_inputs(shadow, result=_received(), verdict_protocol="shadow") == (
        None,
        None,
    )
    other_mode = _review_state(tmp_path, review, mode="Plan")
    assert _publication_outcome_inputs(
        other_mode, result=_received(), verdict_protocol="enforce"
    ) == (None, None)


@pytest.mark.parametrize(
    ("review", "unproven"),
    [
        (ReviewRecord(id=1, node_id="n", reviewed_sha=HEAD_SHA, verdict=None), True),
        (ReviewRecord(id=1, node_id="n", reviewed_sha=HEAD_SHA, verdict="approve"), False),
        (ReviewRecord(id=1, node_id="n", reviewed_sha=None, verdict=None), False),
        (None, False),
    ],
    ids=["verdict_less_on_head", "verdict_bound", "no_sha", "none"],
)
def test_publication_is_unproven_exactly_for_a_verdict_less_review_on_a_head(
    tmp_path: Path, review: ReviewRecord | None, unproven: bool
) -> None:
    assert _publication_unproven(_review_state(tmp_path, review)) is unproven


@pytest.mark.parametrize(
    ("unproven", "reason"),
    [
        (True, _UNPROVEN_RECEIPT_TERMINAL_VERDICT_REASON),
        (False, _NO_RECEIPT_TERMINAL_VERDICT_REASON),
    ],
)
def test_an_unproven_receipt_has_its_own_inconclusive_reason(unproven: bool, reason: str) -> None:
    outcome, got = _classify_outcome(
        result=_received(),
        setup_reason="",
        setup_policy="warn",
        prep_reason=None,
        mode="Review",
        verdict_protocol="enforce",
        terminal_publication_receipt=False,
        terminal_publication_unproven=unproven,
    )
    assert outcome is RunOutcome.inconclusive
    assert got == reason
    assert _UNPROVEN_RECEIPT_TERMINAL_VERDICT_REASON != _NO_RECEIPT_TERMINAL_VERDICT_REASON


def test_the_record_says_the_publication_is_unproven(tmp_path: Path) -> None:
    import mergecraft.main as main_mod

    review = ReviewRecord(id=1, node_id="n", reviewed_sha=HEAD_SHA, verdict=None)
    lines = main_mod._publication_record_lines(_review_state(tmp_path, review))

    unproven = [line for line in lines if line.startswith("**Publication unproven:**")]
    assert len(unproven) == 1
    assert "`approve`" in unproven[0]


def test_a_verdict_bound_receipt_adds_no_unproven_line(tmp_path: Path) -> None:
    import mergecraft.main as main_mod

    review = ReviewRecord(id=1, node_id="n", reviewed_sha=HEAD_SHA, verdict="approve")
    lines = main_mod._publication_record_lines(_review_state(tmp_path, review))
    assert not any("Publication unproven" in line for line in lines)


# ── end to end: a lost create response, recovered on the next publish ─────────


class _RecoveringGitHub(RecordingReviewGitHub):
    """GitHub already holds this run's review; its create response was lost."""

    def __init__(self, *, state: str, inline: Any, run_url: str) -> None:
        super().__init__()
        self._state = state
        self._inline = inline
        self._run_url = run_url

    async def list_reviews(
        self, owner: str, repo: str, pull_number: int, **kwargs: Any
    ) -> list[dict[str, Any]]:
        del owner, repo, pull_number, kwargs
        return [
            {
                "id": _RECOVERED_ID,
                "node_id": f"n{_RECOVERED_ID}",
                "state": self._state,
                "commit_id": HEAD_SHA,
                "user": {"login": "github-actions[bot]", "type": "Bot"},
                "body": f"{DETERMINISTIC_RECORD_MARKER}\n- **Run:** {self._run_url}\n",
            }
        ]

    async def get(self, path: str, **kwargs: Any) -> Any:
        del kwargs
        if path.endswith(f"/reviews/{_RECOVERED_ID}/comments"):
            if isinstance(self._inline, BaseException):
                raise self._inline
            return self._inline
        return {}


def _recovering_ctx(tmp_path: Path, *, state: str, inline: Any) -> tuple[Any, _RecoveringGitHub]:
    probe = publication_ctx(tmp_path, github=RecordingReviewGitHub(), trust_tier="trusted")
    probe.run_id = _RUN_ID
    run_url = _run_url(probe)
    assert run_url, "fixture error: the recovery needs this run's URL"
    github = _RecoveringGitHub(state=state, inline=inline, run_url=run_url)
    ctx = publication_ctx(tmp_path, github=github, trust_tier="trusted")
    ctx.run_id = _RUN_ID
    return ctx, github


def _record_block(github: RecordingReviewGitHub) -> str:
    assert github.review_updates, "the record must be upserted onto the recovered review"
    review_id, body = github.review_updates[-1]
    assert review_id == _RECOVERED_ID
    return body.split(REVIEW_BODY_MARKER, 1)[0]


async def test_a_recovered_approval_for_a_recorded_approve_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, github = _recovering_ctx(tmp_path, state="APPROVED", inline=[{"body": _MARKED_A}])
    await submit_verdict(ctx, "approve")
    ctx.tool_state.terminal_publication_failed = True

    record = await run_finalize(ctx, monkeypatch=monkeypatch, real_publish=True)

    assert github.review_payloads == [], "a recovered review is never posted again"
    receipt = ctx.tool_state.review
    assert receipt is not None
    assert receipt.id == _RECOVERED_ID
    assert receipt.verdict == "approve"
    assert receipt.inline_fingerprints == (_fingerprint(_MARKED_A),)
    assert receipt.payload_hash == _hash("approve", {_fingerprint(_MARKED_A)})
    assert ctx.tool_state.terminal_publication_failed is False
    assert ctx.tool_state.terminal_publication_mismatch is False
    assert record.outcome is RunOutcome.passed
    assert record.failure_reason is None


async def test_a_recovered_change_request_for_a_recorded_approve_is_a_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, github = _recovering_ctx(tmp_path, state="CHANGES_REQUESTED", inline=[])
    await submit_verdict(ctx, "approve")
    ctx.tool_state.terminal_publication_failed = True

    record = await run_finalize(ctx, monkeypatch=monkeypatch, real_publish=True)

    assert github.review_payloads == []
    receipt = ctx.tool_state.review
    assert receipt is not None
    assert receipt.verdict == "request_changes"
    assert ctx.tool_state.terminal_publication_mismatch is True
    assert record.outcome is RunOutcome.inconclusive
    reason = record.failure_reason or ""
    assert "request_changes" in reason
    assert "approve" in reason
    block = _record_block(github)
    assert "**Publication mismatch:**" in block
    assert "`request_changes`" in block
    assert "`approve`" in block


async def test_a_recovered_comment_review_leaves_the_verdict_unproven(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The approve fell back to a COMMENT: GitHub shows no verdict, so none is proven."""
    ctx, github = _recovering_ctx(tmp_path, state="COMMENTED", inline=[])
    await submit_verdict(ctx, "approve")
    ctx.tool_state.terminal_publication_failed = True

    record = await run_finalize(ctx, monkeypatch=monkeypatch, real_publish=True)

    assert github.review_payloads == []
    receipt = ctx.tool_state.review
    assert receipt is not None
    assert receipt.verdict is None
    assert receipt.reviewed_sha == HEAD_SHA
    assert ctx.tool_state.terminal_publication_mismatch is False
    assert record.outcome is RunOutcome.inconclusive
    assert record.failure_reason == _UNPROVEN_RECEIPT_TERMINAL_VERDICT_REASON
    block = _record_block(github)
    assert "**Publication unproven:**" in block
    assert "**Publication mismatch:**" not in block


async def test_an_unreadable_recovered_inline_set_claims_no_publication_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, github = _recovering_ctx(
        tmp_path, state="CHANGES_REQUESTED", inline=RuntimeError("comments unavailable")
    )
    await submit_verdict(ctx, "request_changes", [finding("A real bug here.")])
    ctx.tool_state.terminal_publication_failed = True

    record = await run_finalize(ctx, monkeypatch=monkeypatch, real_publish=True)

    assert github.review_payloads == []
    receipt = ctx.tool_state.review
    assert receipt is not None
    assert receipt.verdict == "request_changes"
    assert receipt.inline_fingerprints is None
    assert receipt.payload_hash is None
    assert list(ctx.tool_state.publication_incomplete) == []
    assert ctx.tool_state.terminal_publication_mismatch is False
    assert record.outcome is RunOutcome.passed
    assert "**Publication incomplete:**" not in _record_block(github)


# ── guard: a normal approve fallback still binds the recorded approve ─────────


class _ApproveRejectedGitHub(RecordingReviewGitHub):
    """GitHub refuses APPROVE with a 422; the COMMENT retry is accepted."""

    async def create_review(
        self, owner: str, repo: str, pull_number: int, **payload: Any
    ) -> dict[str, Any]:
        if payload.get("event") == "APPROVE":
            self.review_payloads.append(dict(payload))
            request = httpx.Request("POST", "https://api.github.com/repos/acme/demo/pulls/7")
            response = httpx.Response(422, request=request, json={"message": "Unprocessable"})
            raise httpx.HTTPStatusError("422", request=request, response=response)
        return await super().create_review(owner, repo, pull_number, **payload)


async def test_the_live_approve_fallback_still_binds_the_recorded_approve(
    tmp_path: Path,
) -> None:
    github = _ApproveRejectedGitHub()
    ctx = publication_ctx(tmp_path, github=github, trust_tier="trusted", pr_approve_enabled=True)
    await submit_verdict(ctx, "approve")

    response = await publish_pull_request_review(ctx)

    assert [payload["event"] for payload in github.review_payloads] == ["APPROVE", "COMMENT"]
    assert response["success"] is True
    assert response.get("approveFallbackDueTo422") is True
    receipt = ctx.tool_state.review
    assert receipt is not None
    assert receipt.verdict == "approve"
    assert receipt.payload_hash == _hash("approve", set())
    assert ctx.tool_state.terminal_publication_failed is False
    assert ctx.tool_state.terminal_publication_mismatch is False
