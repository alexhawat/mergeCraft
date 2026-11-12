"""The formal review stays publishable on very large PRs and long-lived ledgers.

GitHub rejects a review body over 65,536 characters. The deterministic record
lists the reviewed files and the change findings, and the ledger keeps a row per
fingerprint across rounds, so either can outgrow the cap on its own. Both are
budgeted where the body is assembled, and the final truncation never raises.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.agents.gates import TRUSTED_PACKET_DECIDED_BY
from mergecraft.evidence.build import build_packet
from mergecraft.evidence.packet import Decision
from mergecraft.findings import ledger
from mergecraft.main import publish_deterministic_record
from mergecraft.mcp import review as review_mod
from mergecraft.review_taxonomy import finding_fingerprint

if TYPE_CHECKING:
    from pathlib import Path

_PUBLISHER = "mergecraft[bot]"
_LIMIT = review_mod.REVIEW_BODY_MAX_CHARS


@pytest.fixture(autouse=True)
def _reviewer_app_publisher(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MERGECRAFT_REVIEWER_BOT_LOGIN", _PUBLISHER)


class _Scm:
    """Formal-review store that refuses an over-cap body, as GitHub does (422)."""

    def __init__(self) -> None:
        self.reviews: dict[int, str] = {}

    async def list_issue_comments(self, *_a: object, **_k: object) -> list[dict[str, Any]]:
        return []

    async def list_reviews(self, *_a: object, **_k: object) -> list[dict[str, Any]]:
        return [
            {"id": key, "body": body, "user": {"login": _PUBLISHER, "type": "Bot"}}
            for key, body in self.reviews.items()
        ]

    async def create_review(self, *_a: object, **fields: Any) -> dict[str, Any]:
        body = str(fields["body"])
        assert len(body) <= _LIMIT, f"GitHub would reject a {len(body)}-character body"
        review_id = len(self.reviews) + 1
        self.reviews[review_id] = body
        return {"id": review_id}

    async def update_review(
        self, _owner: str, _repo: str, _pr: int, review_id: int, body: str
    ) -> dict[str, Any]:
        assert len(body) <= _LIMIT, f"GitHub would reject a {len(body)}-character body"
        self.reviews[review_id] = body
        return {"id": review_id, "body": body}


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
        trust_tier="trusted",
    )


def _packet(*, files: list[str]) -> Any:
    packet = build_packet(
        change_id="acme/demo#546",
        agent_id="claude",
        agent_version="0.0.1",
        model="claude-sonnet-4-5",
        files_changed=files,
        findings=[],
        deterministic_checks=[],
        self_assessment={"would_approve": True, "sha": "abc123"},
    )
    packet.decision = Decision(
        verdict="success", reason="approved", decided_by=TRUSTED_PACKET_DECIDED_BY
    )
    return packet


async def test_a_2500_file_pr_still_publishes_its_review(tmp_path: Path) -> None:
    files = [f"vendor/generated/package_{index:04d}/module_{index:04d}.py" for index in range(2500)]
    scm = _Scm()

    await publish_deterministic_record(
        pull_number=546, packet=_packet(files=files), ctx=_context(tmp_path, scm)
    )

    body = scm.reviews[1]
    assert len(body) <= _LIMIT
    assert ledger.DETERMINISTIC_RECORD_MARKER in body
    assert f"`{files[0]}`" in body
    assert f"`{files[-1]}`" not in body
    assert "and 2400 more" in body


async def test_a_300_row_ledger_still_publishes_and_keeps_the_newest_rows(
    tmp_path: Path,
) -> None:
    scm = _Scm()
    ctx = _context(tmp_path, scm)
    book = ledger.ensure_finding_ledger(ctx.tool_state)
    fingerprints: list[str] = []
    for index in range(300):
        fingerprint = finding_fingerprint(path=f"src/f{index}.py", body=f"Overflow {index}.")
        fingerprints.append(fingerprint)
        book.record(
            fingerprint,
            "deferred",
            source="analyzer-overflow",
            round_index=1 + index // 100,
            reason="analyzer overflow beyond the inline budget: " + "x" * 120,
            recorded_at=f"2026-08-{1 + index // 24:02d}T{index % 24:02d}:00:00+00:00",
        )

    await publish_deterministic_record(pull_number=546, packet=_packet(files=["a.py"]), ctx=ctx)

    body = scm.reviews[1]
    assert len(body) <= _LIMIT
    kept = {record.fingerprint for record in ledger.FindingLedger.from_comment_body(body).records()}
    assert fingerprints[-1] in kept, "the newest row must survive the budget"
    assert fingerprints[0] not in kept, "the oldest row is the one left out"
    assert "older finding-ledger rows omitted" in body


def test_merge_ledger_into_comment_does_not_accumulate_the_omission_note() -> None:
    book = ledger.FindingLedger()
    for index in range(400):
        book.record(
            finding_fingerprint(path=f"src/g{index}.py", body=f"Row {index}."),
            "deferred",
            source="analyzer-overflow",
            round_index=1,
            reason="y" * 150,
            recorded_at=f"2026-08-01T00:{index // 60:02d}:{index % 60:02d}+00:00",
        )

    once = ledger.merge_ledger_into_comment("Body.", records=book.records())
    twice = ledger.merge_ledger_into_comment(once, records=book.records())

    assert once.count("older finding-ledger rows omitted") == 1
    assert twice == once


def test_truncation_never_raises_when_durable_state_alone_is_over_the_cap(
    tmp_path: Path,
) -> None:
    marker = f"{ledger.DETERMINISTIC_RECORD_MARKER}\n"
    oversized = (
        marker
        + "- **Note:** "
        + ("z" * 80 + "\n") * 900
        + f"{ledger.REVIEW_BODY_MARKER}\n\nprose\n"
        + "\n".join(f"<!-- mergecraft-ledger:v1:{index:024x}:deferred -->" for index in range(400))
    )
    assert len(oversized) > _LIMIT

    payload = review_mod._truncate_review_body_for_github(
        _context(tmp_path, _Scm()), {"body": oversized}, pull_number=546
    )

    body = str(payload["body"])
    assert len(body) <= _LIMIT
    assert body.startswith(marker)
    assert "review body truncated" in body
