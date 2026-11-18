"""Action-layer wiring for risk grade and same-head skip (#1489, #1490)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from tests.review_policy.test_same_head_review import _completed_body
from tests.support.publication import HEAD_SHA, RecordingReviewGitHub, publication_ctx

from mergecraft.action.review_policy import _same_head_skip_gate
from mergecraft.action.review_pull import _resolve_run_risk_config, _resolve_run_risk_grade
from mergecraft.action.review_state import RunContext
from mergecraft.config.settings import RepoSettings


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


@pytest.mark.parametrize("history", ["empty", "other-head", "other-author", "unavailable"])
async def test_same_head_gate_requires_authenticated_history_on_bound_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, history: str
) -> None:
    """An absent, unverified or wrong-head record keeps the normal dispatch path open."""
    sha = "f" * 40
    tctx = publication_ctx(tmp_path, github=RecordingReviewGitHub(), trust_tier="trusted")
    run = RunContext(
        settings=RepoSettings(),
        tool_state=tctx.tool_state,
        tool_context=tctx,
        gh_event={"pull_request": {"number": 7, "head": {"sha": sha}}},
    )
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("MERGECRAFT_REVIEWER_BOT_LOGIN", "mergecraft-app[bot]")

    async def list_reviews(
        _self: RecordingReviewGitHub, owner: str, repo: str, pull_number: int, **_kwargs: Any
    ) -> list[dict[str, Any]]:
        assert (owner, repo) == ("acme", "demo")
        assert pull_number == 7
        if history == "empty":
            return []
        if history == "unavailable":
            raise httpx.ReadTimeout("listing unavailable")
        return [
            {
                "commit_id": "b" * 40 if history == "other-head" else sha,
                "state": "COMMENTED",
                "body": f"{_completed_body()}\n*via mergecraft*",
                "user": {
                    "login": "contributor" if history == "other-author" else "mergecraft-app[bot]"
                },
            }
        ]

    monkeypatch.setattr(RecordingReviewGitHub, "list_reviews", list_reviews)
    assert await _same_head_skip_gate(run) is None
    assert tctx.tool_state.triage is None


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


@pytest.mark.parametrize(
    "status", [None, 404, 403], ids=["missing-base-sha", "missing-config", "unreadable-config"]
)
async def test_risk_config_falls_back_to_defaults_without_readable_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: int | None
) -> None:
    """The head's Jev mode and overrides cannot take effect when base settings are unavailable."""
    tctx = publication_ctx(tmp_path, github=RecordingReviewGitHub(), trust_tier="trusted")
    base_sha = "c" * 40 if status is not None else ""
    run = RunContext(
        settings=RepoSettings.model_validate(
            {
                "risk": {"mode": "jev"},
                "blastRadiusOverride": {"source_without_tests": {"lane": "low"}},
            }
        ),
        tool_state=tctx.tool_state,
        tool_context=tctx,
        settings_snapshot_operator_owned=False,
        gh_event={
            "pull_request": {
                "number": 7,
                "base": {"ref": "main", "sha": base_sha},
                "head": {"sha": HEAD_SHA},
            }
        },
    )

    refs: list[str] = []

    async def get(_self: RecordingReviewGitHub, path: str, **kwargs: Any) -> dict[str, Any]:
        assert path == "/repos/acme/demo/contents/.mergecraft/config.yaml"
        assert status is not None
        refs.append(kwargs["params"]["ref"])
        request = httpx.Request("GET", f"https://api.github.com{path}")
        response = httpx.Response(status, request=request)
        raise httpx.HTTPStatusError("base config unavailable", request=request, response=response)

    monkeypatch.setattr(RecordingReviewGitHub, "get", get)
    await _resolve_run_risk_config(run)
    assert refs == ([base_sha] if base_sha else [])
    assert tctx.tool_state.risk_settings is not None
    assert tctx.tool_state.risk_settings.mode == "deterministic"
    assert tctx.tool_state.blast_rule_set == {}
