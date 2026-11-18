"""Risk classification assembly for the evidence packet (#1489)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mergecraft.classify.blast_radius import FixProofSignal, LaneReason, ScopeSignal
from mergecraft.config.settings import RepoSettings, RiskSettings
from mergecraft.evidence.risk_resolve import resolve_run_risk_classification

if TYPE_CHECKING:
    from mergecraft.classify.blast_radius import Lane
    from mergecraft.config.settings import JevSettings, TrustTier


@pytest.mark.asyncio
async def test_deterministic_mode_sets_tool_state() -> None:
    from mergecraft.mcp.tool_state import ToolState

    state = ToolState(repos={}, primary_repo_key="main")
    result = await resolve_run_risk_classification(
        "diff --git a/src/widget.py b/src/widget.py\n--- a/src/widget.py\n+++ b/src/widget.py\n@@ -1 +1 @@\n-old\n+new\n",
        scope=ScopeSignal(declared=False, globs=[], invalid=False),
        fix_proof=FixProofSignal(required=False, status="not-required"),
        risk=RiskSettings(mode="deterministic"),
        rule_set=None,
        settings=RepoSettings(),
        tool_state=state,
    )
    assert result is not None
    assert state.risk_classification is result


@pytest.mark.asyncio
async def test_jev_mode_combines_raise_only(monkeypatch: pytest.MonkeyPatch) -> None:
    repo_settings = RepoSettings()
    client = object()

    def _fake_client(*, settings: JevSettings) -> object:
        assert settings is repo_settings.jev
        return client

    async def _fake_eval(
        received_client: object, *, diff_excerpt: str, floor: Lane, trust_tier: TrustTier
    ) -> tuple[list[LaneReason], list[LaneReason]]:
        assert received_client is client
        assert diff_excerpt.endswith("-old\n+new\n")
        assert floor == "medium"
        assert trust_tier == "untrusted"
        return (
            [LaneReason(code="jev.authz", lane="high", message="raised")],
            [],
        )

    monkeypatch.setattr("mergecraft.evidence.risk_resolve.evaluate_jev_risk", _fake_eval)
    monkeypatch.setattr("mergecraft.evidence.risk_resolve.AsyncJevClient", _fake_client)
    result = await resolve_run_risk_classification(
        "diff --git a/src/widget.py b/src/widget.py\n--- a/src/widget.py\n+++ b/src/widget.py\n@@ -1 +1 @@\n-old\n+new\n",
        scope=ScopeSignal(declared=False, globs=[], invalid=False),
        fix_proof=FixProofSignal(required=False, status="not-required"),
        risk=RiskSettings(mode="jev"),
        rule_set=None,
        settings=repo_settings,
        tool_state=None,
    )
    assert result is not None
    assert result.lane == "high"
    assert any(r.code == "jev.authz" for r in result.reasons)


@pytest.mark.asyncio
async def test_empty_diff_returns_none() -> None:
    assert (
        await resolve_run_risk_classification(
            "   ",
            scope=ScopeSignal(declared=False, globs=[], invalid=False),
            fix_proof=FixProofSignal(required=False, status="not-required"),
            risk=RiskSettings(),
            rule_set=None,
            settings=RepoSettings(),
        )
        is None
    )
