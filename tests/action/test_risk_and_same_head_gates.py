"""Action-layer wiring for risk grade and same-head skip (#1489, #1490)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from tests.review_policy.test_same_head_review import _completed_body
from tests.support.publication import HEAD_SHA, RecordingReviewGitHub, publication_ctx

from mergecraft.action.review_policy import _same_head_skip_gate
from mergecraft.action.review_pull import _resolve_run_risk_config, _resolve_run_risk_grade
from mergecraft.action.review_state import RunContext, SkipAgentReview
from mergecraft.config.settings import RepoSettings
from mergecraft.review_policy.same_head_review import SAME_HEAD_RECOGNIZER


def _completed_review(
    sha: str, *, url: str = "https://github.com/acme/demo/pull/7#pullrequestreview-1"
) -> dict[str, Any]:
    return {
        "commit_id": sha,
        "state": "APPROVED",
        "body": _completed_body(),
        "html_url": url,
    }


@pytest.mark.asyncio
async def test_same_head_skip_gate_returns_none_without_pull_request(tmp_path: Path) -> None:
    tctx = publication_ctx(tmp_path, github=RecordingReviewGitHub(), trust_tier="trusted")
    run = RunContext(
        settings=RepoSettings(),
        tool_state=tctx.tool_state,
        tool_context=tctx,
        gh_event={},
    )
    assert await _same_head_skip_gate(run) is None


@pytest.mark.asyncio
async def test_same_head_skip_gate_records_skip_triage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sha = "f" * 40
    tctx = publication_ctx(tmp_path, github=RecordingReviewGitHub(), trust_tier="trusted")
    run = RunContext(
        settings=RepoSettings(),
        tool_state=tctx.tool_state,
        tool_context=tctx,
        gh_event={"pull_request": {"number": 7, "head": {"sha": sha}}},
    )
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")

    async def _fake_evaluate(*_a: object, **_k: object) -> str:
        return "This head SHA already has a trusted mergeCraft review."

    async def _fake_list(_ctx: object, *, pull_number: int) -> list[dict[str, Any]]:
        assert pull_number == 7
        return [_completed_review(sha)]

    monkeypatch.setattr(
        "mergecraft.review_policy.same_head_review.evaluate_same_head_skip",
        _fake_evaluate,
    )
    monkeypatch.setattr("mergecraft.mcp.checkout.list_mergecraft_reviews", _fake_list)

    result = await _same_head_skip_gate(run)
    assert isinstance(result, SkipAgentReview)
    assert run.tool_state.triage is not None
    assert run.tool_state.triage.recognizer == SAME_HEAD_RECOGNIZER
    assert run.tool_state.triage.tier == "skip"


@pytest.mark.asyncio
async def test_resolve_run_risk_grade_sets_classification(tmp_path: Path) -> None:
    tctx = publication_ctx(tmp_path, github=RecordingReviewGitHub(), trust_tier="trusted")
    run = RunContext(
        settings=RepoSettings(),
        tool_state=tctx.tool_state,
        tool_context=tctx,
        settings_snapshot_operator_owned=True,
        gh_event={
            "pull_request": {
                "number": 7,
                "head": {"sha": HEAD_SHA},
                "base": {"ref": "main", "sha": "b" * 40},
            }
        },
    )
    await _resolve_run_risk_grade(run)
    assert run.tool_state.risk_classification is not None
    assert run.tool_state.risk_settings is not None


@pytest.mark.asyncio
async def test_resolve_run_risk_config_survives_base_read_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tctx = publication_ctx(tmp_path, github=RecordingReviewGitHub(), trust_tier="trusted")
    run = RunContext(
        settings=RepoSettings(),
        tool_state=tctx.tool_state,
        tool_context=tctx,
        settings_snapshot_operator_owned=False,
        gh_event={
            "pull_request": {
                "number": 7,
                "base": {"ref": "main", "sha": "c" * 40},
                "head": {"sha": HEAD_SHA},
            }
        },
    )

    async def _boom(*_a: object, **_k: object) -> tuple[None, str, str]:
        raise OSError("unreadable base")

    monkeypatch.setattr("mergecraft.review_policy.risk_mode._base_repo_settings", _boom)
    await _resolve_run_risk_config(run)
    assert run.tool_state.risk_settings is not None
    assert run.tool_state.risk_settings.mode == "deterministic"
