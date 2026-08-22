"""``mergecraft review --shell`` — operator opt-in for repo-provided tooling."""

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
def captured_kwargs(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub the offline review entrypoint and capture the kwargs the CLI sends."""
    seen: dict[str, Any] = {}

    async def fake_run_offline_diff_review(**kwargs: Any) -> OfflineReviewResult:
        seen.update(kwargs)
        return OfflineReviewResult(success=True, output="ok")

    monkeypatch.setattr(
        "mergecraft.cli.diff_review_cmd.run_offline_diff_review",
        fake_run_offline_diff_review,
    )
    return seen


@pytest.fixture
def diff_file(tmp_path: Path) -> Path:
    path = tmp_path / "changes.patch"
    path.write_text("diff --git a/a.py b/a.py\n", encoding="utf-8")
    return path


def test_review_shell_defaults_to_disabled(
    captured_kwargs: dict[str, Any], diff_file: Path
) -> None:
    """Absent ``--shell`` keeps today's safe default (regression lock)."""
    runner.invoke(app, ["review", "--diff", str(diff_file), "--dry-run"])
    assert captured_kwargs["shell"] == "disabled"


@pytest.mark.parametrize("value", ["restricted", "enabled"])
def test_review_shell_flag_forwarded(
    value: str, captured_kwargs: dict[str, Any], diff_file: Path
) -> None:
    runner.invoke(app, ["review", "--diff", str(diff_file), "--dry-run", "--shell", value])
    assert captured_kwargs["shell"] == value


def test_review_shell_rejects_unknown_value(
    captured_kwargs: dict[str, Any], diff_file: Path
) -> None:
    result = runner.invoke(
        app, ["review", "--diff", str(diff_file), "--dry-run", "--shell", "everything"]
    )
    assert result.exit_code != 0
    assert captured_kwargs == {}


def test_review_help_documents_shell_opt_in() -> None:
    result = runner.invoke(
        app,
        ["review", "--help"],
        env={"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "200"},
    )
    assert result.exit_code == 0
    out = " ".join(_plain(result.stdout).replace("│", " ").split())
    assert "--shell" in out
    assert "disabled" in out
    assert "restricted" in out
    assert "enabled" in out
    assert "tooling provided by the repository under review" in out
    assert "Unsafe for untrusted code" in out
