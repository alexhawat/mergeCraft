"""Final review publication preserves the ledger and any reported learnings delta.

The report-progress path retains its posted body in the formal review. A run
without progress still publishes its ledger directly, and the next run hydrates
that evidence from the review history.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.agents.gates import TRUSTED_PACKET_DECIDED_BY
from mergecraft.evidence.build import build_packet
from mergecraft.evidence.packet import Decision
from mergecraft.findings import ledger
from mergecraft.main import publish_deterministic_record
from mergecraft.mcp.comment import report_progress_tool
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import ProgressComment, init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.review_taxonomy import finding_fingerprint

if TYPE_CHECKING:
    from pathlib import Path

_PR_NUMBER = 7
_RAW_BODY = "Reviewing the diff before the terminal verdict."
_LEARNINGS_DELTA = "### Learnings delta"
_MODEL = "openai/gpt-5.6-terra"
_LEDGER_V2_RE = re.compile(r"<!-- mergecraft-ledger:v2:([0-9a-f]+):")
# Review history is folded in only from an expected publisher (the reviewer
# App's bot here); the shared ``github-actions[bot]`` login is never trusted.
_PUBLISHER = "mergecraft[bot]"


@pytest.fixture(autouse=True)
def _reviewer_app_publisher(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MERGECRAFT_REVIEWER_BOT_LOGIN", _PUBLISHER)


class _FakeScm:
    """In-memory issue-comment store that records every write."""

    def __init__(self) -> None:
        self.comments: dict[int, dict[str, Any]] = {}
        self.reviews: dict[int, dict[str, Any]] = {}
        self.creates = 0
        self.updates = 0
        self._next_id = 100
        self._next_review_id = 500

    async def list_issue_comments(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        *,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        page = int((params or {}).get("page", 1))
        if page != 1:
            return []
        return [dict(row) for row in self.comments.values()]

    async def get_issue_comment(self, owner: str, repo: str, comment_id: int) -> dict[str, Any]:
        return dict(self.comments[int(comment_id)])

    async def create_issue_comment(
        self, owner: str, repo: str, issue_number: int, body: str
    ) -> dict[str, Any]:
        self._next_id += 1
        self.creates += 1
        row = {
            "id": self._next_id,
            "body": body,
            "user": {"login": _PUBLISHER, "type": "Bot"},
        }
        self.comments[self._next_id] = row
        return dict(row)

    async def update_issue_comment(
        self, owner: str, repo: str, comment_id: int, body: str
    ) -> dict[str, Any]:
        self.updates += 1
        row = self.comments[int(comment_id)]
        row["body"] = body
        return dict(row)

    async def delete_issue_comment(self, owner: str, repo: str, comment_id: int) -> None:
        self.comments.pop(int(comment_id), None)

    async def list_reviews(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        *,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        page = int((params or {}).get("page", 1))
        if page != 1:
            return []
        return [dict(row) for row in self.reviews.values()]

    async def get_review(
        self, owner: str, repo: str, pull_number: int, review_id: int
    ) -> dict[str, Any]:
        return dict(self.reviews[int(review_id)])

    async def create_review(
        self, owner: str, repo: str, pull_number: int, **kwargs: Any
    ) -> dict[str, Any]:
        self._next_review_id += 1
        row = {
            "id": self._next_review_id,
            "node_id": f"R_{self._next_review_id}",
            "commit_id": "",
            "body": str(kwargs.get("body") or ""),
            "user": {"login": _PUBLISHER, "type": "Bot"},
        }
        self.reviews[self._next_review_id] = row
        return dict(row)

    async def update_review(
        self, owner: str, repo: str, pull_number: int, review_id: int, body: str
    ) -> dict[str, Any]:
        row = self.reviews[int(review_id)]
        row["body"] = body
        return dict(row)


def _ctx(tmp_path: Path, scm: _FakeScm) -> ToolContext:
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    state.pr_number = _PR_NUMBER
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request", issue_number=_PR_NUMBER, is_pr=True),
        ),
        scm=scm,
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
        trust_tier="trusted",
    )


def _seed_records(ctx: ToolContext) -> list[str]:
    book = ledger.ensure_finding_ledger(ctx.tool_state)
    fingerprints: list[str] = []
    rows = (
        ("src/one.py", "Unchecked null dereference in handler."),
        ("src/two.py", "Missing timeout on the retry loop."),
    )
    for path, body in rows:
        fingerprint = finding_fingerprint(path=path, body=body)
        book.record(fingerprint, "open", source="inline", round_index=1)
        fingerprints.append(fingerprint)
    return fingerprints


def _seed_learnings_delta(ctx: ToolContext, tmp_path: Path) -> None:
    path = tmp_path / "mergecraft-learnings.md"
    path.write_text(
        "# Learnings\n\n- Pin the action SHA before reviewing.\n",
        encoding="utf-8",
    )
    ctx.tool_state.learnings_file_path = str(path)
    ctx.tool_state.learnings_seed = "# Learnings\n"


def _packet() -> Any:
    packet = build_packet(
        change_id="acme/demo#7",
        agent_id="claude",
        agent_version="0.0.1",
        model=_MODEL,
        files_changed=["src/one.py"],
        findings=[],
        deterministic_checks=[],
        self_assessment={"would_approve": False, "sha": "abc123"},
        agent_terminal_verdict="request_changes",
    )
    packet.decision = Decision(
        verdict="neutral",
        reason="agent terminal verdict request_changes; no structural blocker attested",
        decided_by=TRUSTED_PACKET_DECIDED_BY,
    )
    return packet


def _posted_body(scm: _FakeScm) -> str:
    assert scm.reviews, "the final record must be the formal review"
    return str(next(iter(scm.reviews.values()))["body"])


async def _hydrate_second_run(scm: _FakeScm, tmp_path: Path) -> list[str]:
    fresh = _ctx(tmp_path, scm)
    loaded = await ledger.hydrate_finding_ledger_from_progress_comment(fresh)
    return [record.fingerprint for record in loaded.records()]


def _assert_ledger_and_delta_survive(body: str, fingerprints: list[str]) -> None:
    assert ledger.DETERMINISTIC_RECORD_MARKER in body, body
    for fingerprint in fingerprints:
        assert f"<!-- mergecraft-ledger:v2:{fingerprint}:" in body, body
    assert _LEARNINGS_DELTA in body, body
    assert ledger.FindingLedger.from_comment_body(body).records(), body


@pytest.mark.asyncio
async def test_path_a_report_progress_then_record_keeps_ledger(tmp_path: Path) -> None:
    """Agent called ``report_progress``: the final record must keep the ledger."""
    scm = _FakeScm()
    ctx = _ctx(tmp_path, scm)
    fingerprints = _seed_records(ctx)
    _seed_learnings_delta(ctx, tmp_path)

    progress = await report_progress_tool(ctx).execute({"body": _RAW_BODY})
    assert progress.is_error is False
    assert isinstance(ctx.tool_state.progress_comment, ProgressComment)

    await publish_deterministic_record(
        pull_number=_PR_NUMBER,
        packet=_packet(),
        ctx=ctx,
    )

    body = _posted_body(scm)
    _assert_ledger_and_delta_survive(body, fingerprints)
    assert scm.creates == 1, "path A reuses the comment report_progress created"
    assert len(scm.reviews) == 1

    recovered = await _hydrate_second_run(scm, tmp_path)
    assert set(recovered) == set(fingerprints)


@pytest.mark.asyncio
async def test_path_b_record_without_progress_keeps_ledger(tmp_path: Path) -> None:
    """Publication retains the ledger even without an earlier progress call."""
    scm = _FakeScm()
    ctx = _ctx(tmp_path, scm)
    fingerprints = _seed_records(ctx)

    await publish_deterministic_record(
        pull_number=_PR_NUMBER,
        packet=_packet(),
        ctx=ctx,
    )

    body = _posted_body(scm)
    assert ledger.DETERMINISTIC_RECORD_MARKER in body
    assert {
        record.fingerprint for record in ledger.FindingLedger.from_comment_body(body).records()
    } == set(fingerprints)
    assert scm.creates == 0, "direct final publication does not need a progress comment"
    assert len(scm.reviews) == 1

    recovered = await _hydrate_second_run(scm, tmp_path)
    assert set(recovered) == set(fingerprints)


@pytest.mark.asyncio
async def test_sticky_only_neutral_records_in_the_sticky_not_a_review(tmp_path: Path) -> None:
    """#1078 — a non-terminal neutral rung leaves the formal review to the terminal rung.

    The publish seam already skipped the formal review; finalize must write the
    same deterministic record into the sticky instead of creating the review
    the seam deliberately did not post.
    """
    scm = _FakeScm()
    ctx = _ctx(tmp_path, scm)
    ctx.tool_state.review_publication_sticky_only = True

    await report_progress_tool(ctx).execute({"body": _RAW_BODY})
    await publish_deterministic_record(
        pull_number=_PR_NUMBER,
        packet=_packet(),
        ctx=ctx,
    )

    assert scm.reviews == {}, "a non-terminal neutral rung must not create a formal review"
    assert scm.comments, "the run record must still be visible in the sticky comment"
    body = str(next(iter(scm.comments.values()))["body"])
    assert ledger.DETERMINISTIC_RECORD_MARKER in body, body


def test_ledger_markers_are_v2_shaped() -> None:
    """Guard: the fixture records render v2 markers the assertions key on."""
    book = ledger.FindingLedger()
    fingerprint = finding_fingerprint(path="src/one.py", body="Unrecorded change.")
    book.record(fingerprint, "open", source="inline", round_index=1)
    block = book.render_ledger_block()
    assert _LEDGER_V2_RE.search(block), block
