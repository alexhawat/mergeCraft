"""The final record write must not erase the ledger or the learnings delta.

Three writers share one base body. ``report_progress`` posts the agent body,
the ledger and the learnings delta; ``persist_finding_ledger_to_progress_comment``
re-merges the ledger; ``upsert_sticky_progress_comment`` (the deterministic
record) rebuilds the comment from ``last_progress_body``. When no writer stores
the body it actually posted, the last writer rebuilds from the agent's raw
prose and drops both the ledger markers and the learnings delta.

Both paths are pinned here: **path A** where the agent called
``report_progress``, and **path B** where it never did (``persist`` creates the
sticky). A second-run ``hydrate`` of the final body must recover every record.
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


class _FakeScm:
    """In-memory issue-comment store that records every write."""

    def __init__(self) -> None:
        self.comments: dict[int, dict[str, Any]] = {}
        self.creates = 0
        self.updates = 0
        self._next_id = 100

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
            "user": {"login": "github-actions[bot]", "type": "Bot"},
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


def _posted_body(scm: _FakeScm, ctx: ToolContext) -> str:
    progress = ctx.tool_state.progress_comment
    assert isinstance(progress, ProgressComment)
    return str(scm.comments[int(progress.id)]["body"])


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


@pytest.mark.xfail(
    reason="green after LG2: every writer stores the pre-footer body it posted",
    strict=False,
)
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

    await ledger.persist_finding_ledger_to_progress_comment(ctx)
    await publish_deterministic_record(
        pull_number=_PR_NUMBER,
        packet=_packet(),
        ctx=ctx,
    )

    body = _posted_body(scm, ctx)
    _assert_ledger_and_delta_survive(body, fingerprints)
    assert scm.creates == 1, "path A reuses the comment report_progress created"
    assert scm.updates >= 1

    recovered = await _hydrate_second_run(scm, tmp_path)
    assert set(recovered) == set(fingerprints)


@pytest.mark.xfail(
    reason="green after LG2: persist stores the pre-footer body it posted",
    strict=False,
)
@pytest.mark.asyncio
async def test_path_b_persist_creates_then_record_keeps_ledger(tmp_path: Path) -> None:
    """Agent never called ``report_progress``: ``persist`` creates the sticky."""
    scm = _FakeScm()
    ctx = _ctx(tmp_path, scm)
    fingerprints = _seed_records(ctx)
    _seed_learnings_delta(ctx, tmp_path)

    await ledger.persist_finding_ledger_to_progress_comment(ctx)
    assert isinstance(ctx.tool_state.progress_comment, ProgressComment)
    assert scm.creates == 1

    await publish_deterministic_record(
        pull_number=_PR_NUMBER,
        packet=_packet(),
        ctx=ctx,
    )

    body = _posted_body(scm, ctx)
    _assert_ledger_and_delta_survive(body, fingerprints)
    assert scm.creates == 1, "the record upsert must update the sticky, not post again"

    recovered = await _hydrate_second_run(scm, tmp_path)
    assert set(recovered) == set(fingerprints)


def test_ledger_markers_are_v2_shaped() -> None:
    """Guard: the fixture records render v2 markers the assertions key on."""
    book = ledger.FindingLedger()
    fingerprint = finding_fingerprint(path="src/one.py", body="Unrecorded change.")
    book.record(fingerprint, "open", source="inline", round_index=1)
    block = book.render_ledger_block()
    assert _LEDGER_V2_RE.search(block), block
