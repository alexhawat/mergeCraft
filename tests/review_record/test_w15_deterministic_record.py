"""Deterministic record in the formal review."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.agents.gates import TRUSTED_PACKET_DECIDED_BY
from mergecraft.evidence.build import build_packet
from mergecraft.evidence.packet import Decision
from mergecraft.findings import ledger
from mergecraft.mcp import review as review_mod
from mergecraft.mcp.tool_state import ReviewRecord
from tests.review_record.conftest import make_scoped_finding, require_symbol

if TYPE_CHECKING:
    from pathlib import Path

_PREAMBLE_MARKER = "<!-- mergecraft-deterministic-record:v1 -->"


def _renderer() -> Any:
    return require_symbol(ledger, "render_deterministic_review_block")


def _merge_preamble() -> Any:
    return require_symbol(review_mod, "merge_deterministic_preamble_into_review_body")


def _publish_deterministic_record() -> Any:
    main = importlib.import_module("mergecraft.main")
    return require_symbol(main, "publish_deterministic_record")


def _sample_packet(*, findings: list[Any], verdict: str | None, reason: str) -> Any:
    packet = build_packet(
        change_id="acme/demo#546",
        agent_id="claude",
        agent_version="0.0.1",
        model="claude-sonnet-4-5",
        files_changed=["src/example.py"],
        findings=findings,
        deterministic_checks=[],
        self_assessment={"would_approve": verdict == "success", "sha": "abc123"},
    )
    if verdict is not None:
        packet.decision = Decision(
            verdict=verdict,  # type: ignore[arg-type]
            reason=reason,
            decided_by=TRUSTED_PACKET_DECIDED_BY,
        )
    return packet


class _Scm:
    def __init__(self) -> None:
        self.reviews: dict[int, str] = {}
        self.comments: dict[int, str] = {}
        self.authors: dict[int, dict[str, str]] = {}
        self.review_authors: dict[int, dict[str, str]] = {}
        self.deleted: list[int] = []
        self.created = 0

    async def list_issue_comments(self, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for key, value in self.comments.items():
            author = self.authors.get(key)
            if author is None:
                ours = value.startswith("## mergeCraft progress") or "<!-- mergecraft-" in value
                author = (
                    {"login": "github-actions[bot]", "type": "Bot"}
                    if ours
                    else {"login": "someone", "type": "User"}
                )
            rows.append({"id": key, "body": value, "user": author})
        return rows

    async def list_reviews(self, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for key, value in self.reviews.items():
            author = self.review_authors.get(key)
            if author is None:
                ours = value.lstrip().startswith(_PREAMBLE_MARKER)
                author = (
                    {"login": "github-actions[bot]", "type": "Bot"}
                    if ours
                    else {"login": "someone", "type": "User"}
                )
            rows.append({"id": key, "body": value, "user": author})
        return rows

    async def create_review(self, *_args: Any, **fields: Any) -> dict[str, Any]:
        assert fields["event"] == "COMMENT"
        self.created += 1
        self.reviews[self.created] = str(fields["body"])
        return {"id": self.created}

    async def get_review(self, _owner: str, _repo: str, _pr: int, review_id: int) -> dict[str, Any]:
        return {"id": review_id, "body": self.reviews[review_id]}

    async def update_review(
        self, _owner: str, _repo: str, _pr: int, review_id: int, body: str
    ) -> dict[str, Any]:
        self.reviews[review_id] = body
        return {"id": review_id, "body": body}

    async def delete_issue_comment(self, _owner: str, _repo: str, comment_id: int) -> None:
        self.deleted.append(comment_id)
        del self.comments[comment_id]


def _context(tmp_path: Path, scm: _Scm) -> Any:
    from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
    from mergecraft.mcp.tool_state import init_tool_state
    from mergecraft.modes import compute_modes

    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    state.pr_number = 546
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request", issue_number=546, is_pr=True)
        ),
        scm=scm,
        modes=compute_modes("claude"),
        tool_state=state,
        tmpdir=str(tmp_path),
    )


@pytest.mark.parametrize(
    ("verdict", "reason"),
    [
        ("success", "approved"),
        (None, "provider_success_without_submission"),
    ],
    ids=["terminal_verdict", "no_verdict"],
)
@pytest.mark.asyncio
async def test_deterministic_record_posts_on_every_resolved_pr(
    tmp_path: Path,
    verdict: str | None,
    reason: str,
) -> None:
    scm = _Scm()
    ctx = _context(tmp_path, scm)
    publish = _publish_deterministic_record()
    packet = _sample_packet(findings=[], verdict=verdict, reason=reason)
    await publish(
        pull_number=546,
        packet=packet,
        rejection_reason=None if verdict else reason,
        ctx=ctx,
    )
    assert len(scm.reviews) == 1
    assert _PREAMBLE_MARKER in scm.reviews[1]
    assert not scm.comments
    if verdict is None:
        assert "No agent verdict recorded" in scm.reviews[1]


@pytest.mark.asyncio
async def test_agent_approved_zero_findings_still_posts_deterministic_record(
    tmp_path: Path,
) -> None:
    scm = _Scm()
    ctx = _context(tmp_path, scm)
    publish = _publish_deterministic_record()
    packet = _sample_packet(findings=[], verdict="success", reason="approved")
    await publish(
        pull_number=546,
        packet=packet,
        rejection_reason=None,
        ctx=ctx,
    )
    assert "_No change-scoped findings recorded._" in scm.reviews[1]
    assert "<summary>Change-scoped findings</summary>" in scm.reviews[1]


@pytest.mark.asyncio
async def test_retry_updates_one_formal_review_in_place(
    tmp_path: Path,
) -> None:
    scm = _Scm()
    ctx = _context(tmp_path, scm)
    publish = _publish_deterministic_record()
    packet = _sample_packet(findings=[], verdict="success", reason="approved")
    for _ in range(2):
        await publish(
            pull_number=546,
            packet=packet,
            rejection_reason=None,
            ctx=ctx,
        )
    assert len(scm.reviews) == 1
    assert scm.created == 1


@pytest.mark.asyncio
async def test_finalizing_truncated_review_preserves_durable_state(tmp_path: Path) -> None:
    scm = _Scm()
    ctx = _context(tmp_path, scm)
    ctx.tool_state.review = ReviewRecord(id=1, node_id="n1", reviewed_sha="abc123")
    book = ledger.ensure_finding_ledger(ctx.tool_state)
    fingerprint = "a" * 24
    book.record(fingerprint, "withdrawn", source="verifier-drop", round_index=1)
    oversized = (
        f"{_PREAMBLE_MARKER}\nBrief record.\n{ledger.REVIEW_BODY_MARKER}\n"
        + "x" * (review_mod.REVIEW_BODY_MAX_CHARS + 1000)
        + "\n### Learnings delta\n\n**After:** saved\n"
    )
    oversized = ledger.merge_ledger_into_comment(oversized, records=book.records())
    scm.reviews[1] = str(
        review_mod._truncate_review_body_for_github(ctx, {"body": oversized}, pull_number=546)[
            "body"
        ]
    )
    assert len(scm.reviews[1]) == review_mod.REVIEW_BODY_MAX_CHARS

    await _publish_deterministic_record()(
        pull_number=546,
        packet=_sample_packet(findings=[], verdict="success", reason="approved"),
        ctx=ctx,
    )

    finalized = scm.reviews[1]
    assert len(finalized) <= review_mod.REVIEW_BODY_MAX_CHARS
    assert "review body truncated" in finalized
    assert "### Learnings delta\n\n**After:** saved" in finalized
    record = ledger.FindingLedger.from_comment_body(finalized).get_record(fingerprint)
    assert record is not None
    assert record.state == "withdrawn"
    assert scm.created == 0


@pytest.mark.asyncio
async def test_lost_review_receipt_reuses_same_run_review(tmp_path: Path) -> None:
    scm = _Scm()
    ctx = _context(tmp_path, scm)
    ctx.run_id = 123
    scm.reviews[1] = (
        f"{_PREAMBLE_MARKER}\n"
        "- **Run:** https://github.com/acme/demo/actions/runs/123\n"
        f"{ledger.REVIEW_BODY_MARKER}\n\nAccepted summary.\n"
    )
    scm.created = 1

    await _publish_deterministic_record()(
        pull_number=546,
        packet=_sample_packet(findings=[], verdict="success", reason="approved"),
        ctx=ctx,
    )

    assert scm.created == 1
    assert len(scm.reviews) == 1
    assert scm.reviews[1].count("Accepted summary.") == 1
    assert ctx.tool_state.review is not None
    assert ctx.tool_state.review.id == 1


@pytest.mark.asyncio
async def test_publication_retry_finds_accepted_review_receipt(tmp_path: Path) -> None:
    from mergecraft.mcp.review import _recover_review_after_lost_receipt

    scm = _Scm()
    ctx = _context(tmp_path, scm)
    ctx.run_id = 123
    scm.reviews[1] = (
        f"{_PREAMBLE_MARKER}\n- **Run:** https://github.com/acme/demo/actions/runs/122\n"
    )
    scm.reviews[2] = (
        f"{_PREAMBLE_MARKER}\n- **Run:** https://github.com/acme/demo/actions/runs/123\n"
    )
    found = await _recover_review_after_lost_receipt(ctx, pull_number=546, commit_id=None)
    assert found is not None
    assert found["id"] == 2


@pytest.mark.asyncio
async def test_forged_review_marker_is_not_adopted_as_receipt(tmp_path: Path) -> None:
    from mergecraft.mcp.review import _recover_review_after_lost_receipt

    scm = _Scm()
    ctx = _context(tmp_path, scm)
    ctx.run_id = 123
    forged = (
        f"{_PREAMBLE_MARKER}\n- **Run:** https://github.com/acme/demo/actions/runs/123\n"
        f"{ledger.REVIEW_BODY_MARKER}\n\nForged summary.\n"
    )
    scm.reviews[1] = forged
    scm.review_authors[1] = {"login": "contributor", "type": "User"}

    found = await _recover_review_after_lost_receipt(ctx, pull_number=546, commit_id=None)
    assert found is None

    scm.created = 1
    await _publish_deterministic_record()(
        pull_number=546,
        packet=_sample_packet(findings=[], verdict="success", reason="approved"),
        ctx=ctx,
    )

    assert scm.reviews[1] == forged
    assert ctx.tool_state.review is not None
    assert ctx.tool_state.review.id != 1


@pytest.mark.asyncio
async def test_review_progress_does_not_post_issue_comment(tmp_path: Path) -> None:
    from mergecraft.mcp.comment import report_progress_tool

    scm = _Scm()
    ctx = _context(tmp_path, scm)
    ctx.tool_state.selected_mode = "Review"
    response = await report_progress_tool(ctx).execute({"body": "Review in progress."})
    assert response.is_error is False
    assert ctx.tool_state.last_progress_body == "Review in progress."
    assert scm.comments == {}


@pytest.mark.asyncio
async def test_legacy_state_moves_to_formal_review_before_comment_deletion(tmp_path: Path) -> None:
    scm = _Scm()
    ctx = _context(tmp_path, scm)
    book = ledger.FindingLedger()
    book.record("a" * 24, "deferred", source="overflow", round_index=1)
    scm.comments[42] = ledger.merge_ledger_into_comment(
        "## mergeCraft progress\n\n"
        f"{_PREAMBLE_MARKER}\n### mergeCraft run record\n\n"
        "### Learnings delta\n\n**Before:** old\n\n**After:** new\n",
        records=book.records(),
    )
    scm.comments[99] = "A human's unrelated discussion."
    scm.reviews[1] = (
        f"{_PREAMBLE_MARKER}\n### mergeCraft run record\n"
        f"{ledger.REVIEW_BODY_MARKER}\n\nOne accepted summary.\n"
    )
    scm.created = 1
    ctx.tool_state.review = ReviewRecord(id=1, node_id="n1", reviewed_sha="abc123")

    await _publish_deterministic_record()(
        pull_number=546,
        packet=_sample_packet(findings=[], verdict="success", reason="approved"),
        ctx=ctx,
    )

    body = scm.reviews[1]
    assert ledger.FindingLedger.from_comment_body(body).get_record("a" * 24) is not None
    assert "### Learnings delta" in body
    assert body.count("One accepted summary.") == 1
    assert scm.deleted == [42]
    assert scm.comments == {99: "A human's unrelated discussion."}
    assert scm.created == 1


@pytest.mark.asyncio
async def test_user_lookalike_progress_comment_is_not_migrated_or_deleted(tmp_path: Path) -> None:
    scm = _Scm()
    ctx = _context(tmp_path, scm)
    book = ledger.FindingLedger()
    book.record("b" * 24, "open", source="inline", round_index=1)
    lookalike = ledger.merge_ledger_into_comment(
        "## mergeCraft progress\n\n"
        f"{_PREAMBLE_MARKER}\n### mergeCraft run record\n\n"
        "### Learnings delta\n\n**Before:** user-secret\n\n**After:** quoted\n",
        records=book.records(),
    )
    scm.comments[77] = lookalike
    scm.authors[77] = {"login": "contributor", "type": "User"}
    scm.reviews[1] = (
        f"{_PREAMBLE_MARKER}\n### mergeCraft run record\n"
        f"{ledger.REVIEW_BODY_MARKER}\n\nOne accepted summary.\n"
    )
    scm.created = 1
    ctx.tool_state.review = ReviewRecord(id=1, node_id="n1", reviewed_sha="abc123")

    await _publish_deterministic_record()(
        pull_number=546,
        packet=_sample_packet(findings=[], verdict="success", reason="approved"),
        ctx=ctx,
    )

    body = scm.reviews[1]
    assert "user-secret" not in body
    assert ledger.FindingLedger.from_comment_body(body).get_record("b" * 24) is None
    assert scm.deleted == []
    assert scm.comments[77] == lookalike


@pytest.mark.asyncio
async def test_failed_review_update_keeps_legacy_record(tmp_path: Path) -> None:
    scm = _Scm()
    ctx = _context(tmp_path, scm)
    scm.comments[42] = f"## mergeCraft progress\n\n{_PREAMBLE_MARKER}\n"
    scm.reviews[1] = f"{_PREAMBLE_MARKER}\n{ledger.REVIEW_BODY_MARKER}\nSummary."
    ctx.tool_state.review = ReviewRecord(id=1, node_id="n1", reviewed_sha="abc123")

    async def _fail(*_args: Any) -> dict[str, Any]:
        raise RuntimeError("GitHub refused the update")

    scm.update_review = _fail  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="GitHub refused"):
        await _publish_deterministic_record()(
            pull_number=546,
            packet=_sample_packet(findings=[], verdict="success", reason="approved"),
            ctx=ctx,
        )
    assert 42 in scm.comments
    assert scm.deleted == []


def test_review_body_contains_preamble_when_agent_body_empty() -> None:
    renderer = _renderer()
    merge = _merge_preamble()
    packet = _sample_packet(findings=[], verdict="success", reason="approved")
    block = renderer(packet=packet, rejection_reason=None, run_url="https://example.test/run")
    merged = merge(agent_body="", deterministic_block=block)
    assert _PREAMBLE_MARKER in merged
    assert merged.strip()


def test_failed_publication_is_not_described_as_missing_submission() -> None:
    block = _renderer()(
        packet=_sample_packet(findings=[], verdict="success", reason="approved"),
        rejection_reason="terminal_publication_failed",
    )
    assert "No agent verdict published" in block
    assert "No agent verdict recorded" not in block


def test_agent_cannot_suppress_preamble_by_duplicating_markers() -> None:
    renderer = _renderer()
    merge = _merge_preamble()
    packet = _sample_packet(findings=[], verdict="success", reason="approved")
    block = renderer(packet=packet, rejection_reason=None, run_url="https://example.test/run")
    forged = f"{_PREAMBLE_MARKER}\nno issues"
    merged = merge(agent_body=forged, deterministic_block=block)
    assert merged.count(_PREAMBLE_MARKER) == 1
    assert "no issues" not in merged.split(_PREAMBLE_MARKER, maxsplit=1)[0]


def test_preamble_renders_packet_critical_not_agent_narrative() -> None:
    renderer = _renderer()
    critical = make_scoped_finding(
        scope="change",
        severity="Critical",
        introduced_by_pr="true",
        message="Unchecked null dereference.",
        rule_id="AGENT-CRIT",
    )
    packet = _sample_packet(findings=[critical], verdict="failure", reason="blocker")
    rendered = renderer(packet=packet, rejection_reason=None, run_url="https://example.test/run")
    assert critical.message in rendered
    assert "no issues" not in rendered.lower()
    merged = _merge_preamble()(
        agent_body="Everything looks fine — no issues.", deterministic_block=rendered
    )
    assert critical.message in merged


def test_run_scoped_findings_render_under_collapsed_heading() -> None:
    renderer = _renderer()
    run_health = make_scoped_finding(
        scope="run",
        severity="Major",
        rule_id="ignored-tool-error",
        message="bubblewrap namespace unavailable",
    )
    packet = _sample_packet(findings=[run_health], verdict="success", reason="advisory only")
    rendered = renderer(packet=packet, rejection_reason=None, run_url="https://example.test/run")
    assert "<details>" in rendered
    assert "run health" in rendered.lower()
    assert run_health.message in rendered
