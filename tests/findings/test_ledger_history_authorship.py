"""Ledger review history trusts the same publishers as ``review/authorship.py``.

A formal review's ledger rows are folded into later rounds only when the review
was written by an expected publisher: the reviewer App's bot or the PAT the run
publishes with. A PAT review is ``type == "User"``, so the account type is not
the test; the shared ``github-actions[bot]`` login is never a publisher.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.findings import ledger
from mergecraft.review_taxonomy import finding_fingerprint

if TYPE_CHECKING:
    from pathlib import Path

_FP = finding_fingerprint(path="src/history.py", body="Deferred overflow row.")


def _record_body() -> str:
    book = ledger.FindingLedger()
    book.record(_FP, "deferred", source="overflow", round_index=1)
    return ledger.merge_ledger_into_comment(
        f"{ledger.DETERMINISTIC_RECORD_MARKER}\n", records=book.records()
    )


class _Scm:
    def __init__(self, *, author: dict[str, str], viewer: str = "") -> None:
        self._author = author
        self._viewer = viewer

    async def list_issue_comments(self, *_a: object, **_k: object) -> list[dict[str, Any]]:
        return []

    async def list_reviews(
        self, *_a: object, params: dict[str, int], **_k: object
    ) -> list[dict[str, Any]]:
        if params["page"] != 1:
            return []
        return [{"id": 1, "user": dict(self._author), "body": _record_body()}]

    async def get(self, path: str, **_k: object) -> dict[str, Any]:
        if path == "/user" and self._viewer:
            return {"login": self._viewer}
        msg = f"unexpected GET {path}"
        raise RuntimeError(msg)


def _ctx(tmp_path: Path, scm: _Scm, *, token: str) -> Any:
    from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
    from mergecraft.mcp.tool_state import init_tool_state
    from mergecraft.modes import compute_modes

    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    state.pr_number = 7
    state.finding_ledger_loaded = False
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request", issue_number=7, is_pr=True)
        ),
        scm=scm,
        github_installation_token=token,
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
        trust_tier="trusted",
    )


@pytest.fixture
def _no_app(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MERGECRAFT_REVIEWER_BOT_LOGIN", raising=False)
    monkeypatch.delenv("GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("GITHUB_APP_PRIVATE_KEY", raising=False)
    monkeypatch.setattr(ledger, "_publisher_login_from_config", "")


@pytest.mark.usefixtures("_no_app")
async def test_a_pat_published_review_contributes_its_ledger_rows(tmp_path: Path) -> None:
    scm = _Scm(author={"login": "release-pat", "type": "User"}, viewer="release-pat")

    loaded = await ledger.hydrate_finding_ledger_from_progress_comment(
        _ctx(tmp_path, scm, token="pat-token")
    )

    record = loaded.get_record(_FP)
    assert record is not None
    assert record.state == "deferred"


@pytest.mark.usefixtures("_no_app")
async def test_a_job_token_review_contributes_nothing_to_the_run_ledger(tmp_path: Path) -> None:
    scm = _Scm(author={"login": "github-actions[bot]", "type": "Bot"}, viewer="github-actions[bot]")

    loaded = await ledger.hydrate_finding_ledger_from_progress_comment(
        _ctx(tmp_path, scm, token="job-token")
    )

    assert loaded.get_record(_FP) is None


@pytest.mark.usefixtures("_no_app")
async def test_the_read_side_ledger_never_trusts_the_shared_actions_login() -> None:
    scm = _Scm(author={"login": "github-actions[bot]", "type": "Bot"})

    found = await ledger.fetch_review_ledger(scm, "acme", "demo", 7)  # type: ignore[arg-type]

    assert found.get_record(_FP) is None


async def test_the_read_side_ledger_trusts_the_configured_app_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MERGECRAFT_REVIEWER_BOT_LOGIN", "mergecraft-app[bot]")
    scm = _Scm(author={"login": "Mergecraft-App[bot]", "type": "Bot"})

    found = await ledger.fetch_review_ledger(scm, "acme", "demo", 7)  # type: ignore[arg-type]

    record = found.get_record(_FP)
    assert record is not None
    assert record.state == "deferred"
