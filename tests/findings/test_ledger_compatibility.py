"""Exercise review-history carryover through the original ledger import path."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.evidence.build import build_packet
from mergecraft.findings import ledger, ledger_io, ledger_model, record_render
from mergecraft.scm.github import GitHubScmAdapter
from tests.support.github_fakes import StrictGitHubClient

if TYPE_CHECKING:
    import pytest

# Pin the names available before the split independently of each implementation's exports.
_LEGACY_EXPORTS_BY_MODULE = {
    ledger_model: (
        "LEDGER_BLOCK_MAX_CHARS",
        "LEDGER_MARKER_PREFIX",
        "LEDGER_MARKER_V2_PREFIX",
        "LEDGER_SCHEMA_VERSION",
        "FindingLedger",
        "ensure_finding_ledger",
        "ledger_round_index",
        "merge_ledger_into_comment",
        "record_deferred_from_analyzer_run",
        "record_over_budget_verifications",
        "record_published_findings_in_ledger",
        "record_withdrawn_in_ledger",
    ),
    ledger_io: (
        "configured_publisher_login",
        "fetch_review_ledger",
        "fetch_review_record_bodies",
        "fetch_sticky_progress_comment",
        "fetch_sticky_progress_comment_body",
        "hydrate_finding_ledger_from_progress_comment",
        "is_sticky_progress_comment",
        "is_trusted_sticky_author",
        "select_sticky_progress_comment",
        "sticky_progress_comment_body",
        "upsert_sticky_progress_comment",
    ),
    record_render: (
        "DETERMINISTIC_RECORD_MARKER",
        "merge_deterministic_record_into_comment",
        "render_deterministic_review_block",
        "strip_deterministic_record_markers",
    ),
}


async def test_legacy_ledger_imports_preserve_trusted_review_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The old namespace exposes the same APIs and carries a published row forward."""
    expected_exports = {
        name: getattr(module, name)
        for module, names in _LEGACY_EXPORTS_BY_MODULE.items()
        for name in names
    }
    expected_exports["_is_trusted_sticky_author"] = ledger_io.is_trusted_sticky_author
    expected_exports["_strip_deterministic_record_markers"] = (
        record_render.strip_deterministic_record_markers
    )
    assert sorted(ledger.__all__) == sorted(expected_exports)
    for name, expected in expected_exports.items():
        assert getattr(ledger, name) is expected, name
    assert ledger.REVIEW_BODY_MARKER is record_render.REVIEW_BODY_MARKER
    assert ledger.sticky_progress_comment is ledger_io.sticky_progress_comment

    publisher = "mergecraft-app[bot]"
    monkeypatch.setenv("MERGECRAFT_REVIEWER_BOT_LOGIN", publisher)
    book = ledger.FindingLedger()
    row = book.record("ab12cd34", "deferred", source="overflow", round_index=1)
    packet = build_packet(
        change_id="acme/demo#7",
        agent_id="claude",
        agent_version="1",
        model="test-model",
        files_changed=["src/demo.py"],
        findings=[],
        deterministic_checks=[],
    )
    block = ledger.render_deterministic_review_block(packet=packet)
    body = ledger.merge_ledger_into_comment(block, records=book.records())
    assert "- **Change:** `acme/demo#7`" in body
    assert ledger_model.FindingLedger.from_comment_body(body).records() == [row]

    reviews = [
        {"id": 1, "user": {"login": publisher, "type": "Bot"}, "body": body},
        {"id": 2, "user": {"login": "other-app[bot]", "type": "Bot"}, "body": body + "\nForged"},
    ]
    routes = {
        ("GET", "/repos/acme/demo/issues/7/comments"): [],
        ("GET", "/repos/acme/demo/pulls/7/reviews"): reviews,
    }
    async with StrictGitHubClient(routes=routes) as github:
        scm = GitHubScmAdapter(github)
        assert await ledger.fetch_review_record_bodies(scm, "acme", "demo", 7) == [body]
        restored = await ledger.fetch_review_ledger(scm, "acme", "demo", 7)

    assert type(restored) is ledger_model.FindingLedger
    assert restored.records() == [row]
