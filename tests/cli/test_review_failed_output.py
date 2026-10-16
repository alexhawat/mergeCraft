"""Failed ``mergecraft review`` runs still print partial timing (issue #985 follow-up)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import pytest
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.offline_review import OfflineReviewResult

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


@pytest.fixture
def diff_file(tmp_path: Path) -> Path:
    path = tmp_path / "changes.patch"
    path.write_text("diff --git a/a.py b/a.py\n", encoding="utf-8")
    return path


def test_failed_review_prints_timing_line(diff_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    timing = {
        "line": "⏱ LLM review time: 29m 1s (reviewer)",
        "total_seconds": 1741.0,
    }

    async def fake_run_offline_diff_review(**kwargs: Any) -> OfflineReviewResult:
        return OfflineReviewResult(
            success=False,
            error="checkout integrity failure",
            output="",
            llm_review_timing=timing,
        )

    monkeypatch.setattr(
        "mergecraft.cli.diff_review_cmd.run_offline_diff_review",
        fake_run_offline_diff_review,
    )
    result = runner.invoke(
        app,
        ["review", "--diff", str(diff_file)],
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )
    assert result.exit_code != 0
    output = _plain(result.stdout + result.stderr)
    assert "⏱ LLM review time" in output
