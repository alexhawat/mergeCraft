"""Checkout hydration must retain operator limits after the PR changes YAML."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
import yaml
from tests.support.tool_context import make_tool_context

from mergecraft.config.settings import RepoSettings
from mergecraft.config.settings_snapshot import (
    capture_run_scope_snapshot,
    rebaseline_repo_settings_snapshot,
)
from mergecraft.mcp.review_context import hydrate_review_context
from mergecraft.utils.run_bounds import BudgetTracker, resolve_run_bounds

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("factor", [0.1, 10.0])
async def test_head_config_cannot_change_pinned_bounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, factor: float
) -> None:
    limits = {
        "tokenBudget": 1000,
        "costBudgetUsd": 10,
        "toolCallBudget": 100,
        "maxDiffLines": 1000,
        "contextRetrievalTimeoutS": 100,
        "cacheMaxBytes": 1000,
        "tokenBudgetTolerance": 0.1,
    }
    base = {"runBounds": limits, "review": {"roundBudgets": {"multipliers": [1.0, 0.5]}}}
    config = tmp_path / ".mergecraft" / "config.yaml"
    config.parent.mkdir()
    config.write_text(yaml.safe_dump(base))
    ctx = make_tool_context(tmp_path, trust_tier="untrusted")
    settings = RepoSettings.model_validate(base)
    ctx.budget_tracker = BudgetTracker(bounds=resolve_run_bounds(settings=settings), tokens_used=27)
    capture_run_scope_snapshot(ctx, root=tmp_path, settings=settings, operator_owned=True)

    # Match checkout_pr: materialize a different head config, then rebaseline
    # its integrity hash while keeping the original settings snapshot.
    head_limits = {
        key: value * factor if isinstance(value, float) else int(value * factor)
        for key, value in limits.items()
    }
    config.write_text(
        yaml.safe_dump(
            {
                "runBounds": head_limits,
                "review": {"roundBudgets": {"multipliers": [factor, factor]}},
            }
        )
    )
    rebaseline_repo_settings_snapshot(ctx)
    monkeypatch.setattr(
        "mergecraft.findings.ledger.hydrate_finding_ledger_from_progress_comment", AsyncMock()
    )
    await hydrate_review_context(ctx, round_index=2)
    assert ctx.budget_tracker.bounds == resolve_run_bounds(settings=settings, round_index=2)
    assert ctx.budget_tracker.tokens_used == 27


async def test_unsnapshotted_context_still_loads_its_own_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / ".mergecraft" / "config.yaml"
    config.parent.mkdir()
    config.write_text("runBounds:\n  tokenBudget: 1234\n")
    ctx = make_tool_context(tmp_path, trust_tier="trusted")
    ctx.budget_tracker = BudgetTracker(bounds=resolve_run_bounds())
    monkeypatch.setattr(
        "mergecraft.findings.ledger.hydrate_finding_ledger_from_progress_comment", AsyncMock()
    )
    await hydrate_review_context(ctx, round_index=1)
    assert ctx.budget_tracker.bounds.token_budget == 1234
