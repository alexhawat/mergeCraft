"""Cross-round finding ledger (RC4, RC5, D4-D6) - W3.1 RED suite."""

from __future__ import annotations

import asyncio
import importlib
import re
from typing import TYPE_CHECKING, Any, get_args

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

from mergecraft.review_taxonomy import finding_fingerprint

_PATH = "src/app.py"
_PUBLISHED_BODY = "Missing timeout on the retry loop."
_DEFERRED_BODY = "Unchecked null dereference in handler."
_DROPPED_BODY = "False positive race claim."
_UNPUBLISHED_BODY = "Over-budget critical blocker."

_PUBLISHED_FP = finding_fingerprint(path=_PATH, body=_PUBLISHED_BODY)
_DEFERRED_FP = finding_fingerprint(path="src/deferred.py", body=_DEFERRED_BODY)
_DROPPED_FP = finding_fingerprint(path="src/dropped.py", body=_DROPPED_BODY)
_UNPUBLISHED_FP = finding_fingerprint(path="src/unpub.py", body=_UNPUBLISHED_BODY)

_LEDGER_MARKER_RE = re.compile(
    r"<!-- mergecraft-ledger:v[12]:([0-9a-f]+):([a-z-]+)(?::([^>]*?))? -->"
)


def _ledger_mod() -> Any:
    return importlib.import_module("mergecraft.findings.ledger")


def _lifecycle_mod() -> Any:
    return importlib.import_module("mergecraft.findings.lifecycle")


def _progress_comment_with_ledger(*, ledger_block: str) -> str:
    return f"## mergeCraft progress\n\nReview in progress.\n\n{ledger_block}\n"


def test_published_deferred_and_dropped_findings_all_enter_the_ledger() -> None:
    ledger = _ledger_mod()
    lifecycle = _lifecycle_mod()

    book = ledger.FindingLedger()
    book.record(
        _PUBLISHED_FP,
        "open",
        source="inline",
        round_index=1,
    )
    book.record(
        _DEFERRED_FP,
        "deferred",
        source="overflow",
        round_index=1,
    )
    book.record(
        _DROPPED_FP,
        "withdrawn",
        source="verifier-drop",
        round_index=1,
        reason="Judge refuted the cited code.",
    )

    states = {record.fingerprint: record.state for record in book.records()}
    assert states[_PUBLISHED_FP] == "open"
    assert states[_DEFERRED_FP] == "deferred"
    assert states[_DROPPED_FP] == "withdrawn"
    assert len(states) == 3
    assert all(isinstance(record, lifecycle.LifecycleRecord) for record in book.records())


def test_ledger_key_is_the_review_taxonomy_fingerprint() -> None:
    ledger = _ledger_mod()

    book = ledger.FindingLedger()
    taxonomy_fp = finding_fingerprint(path=_PATH, body=_PUBLISHED_BODY)
    book.record(taxonomy_fp, "open", source="inline", round_index=1)

    block = book.render_ledger_block()
    assert f"<!-- mergecraft-ledger:v2:{taxonomy_fp}:open:" in block
    assert taxonomy_fp == _PUBLISHED_FP
    assert ledger.LEDGER_MARKER_PREFIX == "<!-- mergecraft-ledger:v1:"


def test_ledger_round_trips_through_the_sticky_comment_html_block() -> None:
    ledger = _ledger_mod()

    book = ledger.FindingLedger()
    book.record(_DEFERRED_FP, "deferred", source="overflow", round_index=1)
    book.record(_UNPUBLISHED_FP, "unpublished", source="verification-budget", round_index=1)

    comment_body = ledger.merge_ledger_into_comment(
        _progress_comment_with_ledger(ledger_block=book.render_ledger_block()),
        records=book.records(),
    )
    assert _LEDGER_MARKER_RE.search(comment_body)

    restored = ledger.FindingLedger.from_comment_body(comment_body)
    restored_states = {record.fingerprint: record.state for record in restored.records()}
    assert restored_states[_DEFERRED_FP] == "deferred"
    assert restored_states[_UNPUBLISHED_FP] == "unpublished"


def test_ledger_survives_a_second_action_run_with_no_local_state() -> None:
    ledger = _ledger_mod()

    first_run = ledger.FindingLedger()
    first_run.record(_PUBLISHED_FP, "open", source="inline", round_index=1)
    first_run.record(_DEFERRED_FP, "deferred", source="overflow", round_index=1)

    persisted_body = ledger.merge_ledger_into_comment(
        "## mergeCraft progress\n\nRound 1 complete.\n",
        records=first_run.records(),
    )

    second_run = ledger.FindingLedger.from_comment_body(persisted_body)
    second_run.record(_DROPPED_FP, "withdrawn", source="verifier-drop", round_index=2)

    states = {record.fingerprint: record.state for record in second_run.records()}
    assert states[_PUBLISHED_FP] == "open"
    assert states[_DEFERRED_FP] == "deferred"
    assert states[_DROPPED_FP] == "withdrawn"
    assert len(second_run.records()) == 3


def test_ledger_records_over_budget_verifications_from_w2(tmp_path: Path) -> None:
    from mergecraft.config.settings import load_repo_settings

    verifier = importlib.import_module("mergecraft.agents.verifier")
    ledger = _ledger_mod()

    settings = load_repo_settings(root=tmp_path, load_learnings_files=False)
    review = settings.review
    budget = review.verification_budget if review.verification_budget != 0 else 0

    findings = [
        verifier.AgentFinding(
            path=f"src/critical{index:02d}.py",
            body=f"critical blocker {index}",
            severity="Critical",
        )
        for index in range(25)
    ]
    plan = verifier.plan_agent_verifications(findings, budget=budget)
    overflow_id = findings[24].identity()

    book = ledger.FindingLedger()
    ledger.record_over_budget_verifications(book, skipped_over_budget=plan.skipped_over_budget)

    states = {record.fingerprint: record.state for record in book.records()}
    assert overflow_id in states
    assert states[overflow_id] == "unpublished"


def test_ledger_never_files_a_github_issue(monkeypatch: MonkeyPatch) -> None:
    from mergecraft.findings.sweep import plan_carryover

    ledger = _ledger_mod()
    created: list[dict[str, Any]] = []

    class _RecordingClient:
        async def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
            return {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {"totalCount": 0, "nodes": []},
                    }
                }
            }

        async def list_issues(self, owner: str, repo: str, **kwargs: Any) -> list[dict[str, Any]]:
            return []

        async def create_issue(self, owner: str, repo: str, **kwargs: Any) -> dict[str, Any]:
            created.append(kwargs)
            return {"number": 1, "html_url": "https://github.com/o/r/issues/1"}

    book = ledger.FindingLedger()
    book.record(_DEFERRED_FP, "deferred", source="overflow", round_index=1)

    plan = asyncio.run(
        plan_carryover(
            _RecordingClient(),
            owner="o",
            repo="r",
            pull_number=7,
            ledger_records=book.records(),
        )
    )

    assert plan.to_file == []
    assert created == []


def test_deferred_state_is_added_to_lifecycle_state_literal() -> None:
    lifecycle = _lifecycle_mod()

    states = set(get_args(lifecycle.LifecycleState))
    assert "deferred" in states
    assert "unpublished" in states

    enum_names = {
        name for name in dir(lifecycle) if name.endswith("State") and name != "LifecycleState"
    }
    assert enum_names == set()


def test_promotion_records_a_reason_and_timestamp() -> None:
    ledger = _ledger_mod()
    lifecycle = _lifecycle_mod()

    book = ledger.FindingLedger()
    book.record(_DEFERRED_FP, "deferred", source="overflow", round_index=1)

    promoted = book.promote(
        _DEFERRED_FP,
        reason="Incremental diff touched src/deferred.py.",
        recorded_at="2026-08-22T12:00:00Z",
    )

    assert isinstance(promoted, lifecycle.LifecycleRecord)
    assert promoted.fingerprint == _DEFERRED_FP
    assert promoted.state == "open"
    assert promoted.reason == "Incremental diff touched src/deferred.py."
    assert promoted.recorded_at == "2026-08-22T12:00:00Z"

    current = next(record for record in book.records() if record.fingerprint == _DEFERRED_FP)
    assert current.state == "open"
    assert current.reason == "Incremental diff touched src/deferred.py."
    assert current.recorded_at == "2026-08-22T12:00:00Z"
