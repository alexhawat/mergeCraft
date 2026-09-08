"""The image live gate must require real terminal-review acceptance."""

from __future__ import annotations

import os
from typing import Any

import pytest

from mergecraft.review.offline_result import OfflineReviewResult
from mergecraft.run_outcome import RunOutcome
from scripts import live_image_smoke


@pytest.fixture(autouse=True)
def restore_smoke_budget_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "MERGECRAFT_RUN_TIMEOUT_S",
        "MERGECRAFT_TOKEN_BUDGET",
        "MERGECRAFT_TOOL_CALL_BUDGET",
        "MERGECRAFT_COST_BUDGET_USD",
    ):
        monkeypatch.setenv(key, "1")


@pytest.mark.parametrize(
    "result",
    [
        OfflineReviewResult(success=False, outcome=RunOutcome.configuration_error),
        OfflineReviewResult(success=True, outcome=RunOutcome.passed),
        OfflineReviewResult(success=True, structured_output="{}"),
    ],
)
async def test_live_smoke_rejects_nonterminal_results(
    monkeypatch: pytest.MonkeyPatch, result: OfflineReviewResult
) -> None:
    monkeypatch.setenv("MERGECRAFT_E2E_LIVE_MODEL", "openai/test")

    async def review(**kwargs: Any) -> OfflineReviewResult:
        assert kwargs["use_cache"] is False
        assert kwargs["diff_file"].is_file()
        assert os.environ["MERGECRAFT_RUN_TIMEOUT_S"] == "180"
        return result

    monkeypatch.setattr(live_image_smoke, "run_offline_diff_review", review)
    with pytest.raises(RuntimeError, match="accepted terminal"):
        await live_image_smoke.main()


async def test_live_smoke_reports_accepted_terminal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MERGECRAFT_E2E_LIVE_MODEL", "openai/test")

    async def review(**kwargs: Any) -> OfflineReviewResult:
        return OfflineReviewResult(success=True, outcome=RunOutcome.passed, structured_output="{}")

    monkeypatch.setattr(live_image_smoke, "run_offline_diff_review", review)
    await live_image_smoke.main()
    assert '"terminal_review": true' in capsys.readouterr().out
