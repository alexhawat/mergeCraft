"""A missing model chain is one configuration line, not a traceback (#1569).

``_prepare_offline_agent`` raised a plain ``ValueError``; the blanket
``except Exception`` arm logged it with ``logger.exception``, printing a full
traceback for what is an ordinary configuration error.

Contract: ``mergecraft review`` with no ``models:`` exits ``30``, prints the
actionable message, and writes no traceback to either stream.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest
from tests.support.cli_text import compact_cli_text
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_CONFIGURATION_EXIT_CODE

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}
_MESSAGE = "no model chain configured"


def _repo_with_a_change(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """Create a git repo with one commit and one uncommitted change; no models."""
    monkeypatch.delenv("MERGECRAFT_MODEL", raising=False)
    monkeypatch.delenv("MERGECRAFT_CONFIG", raising=False)
    monkeypatch.delenv("MERGECRAFT_ENV", raising=False)
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "a.txt").write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=cli@example.invalid",
            "-c",
            "user.name=CLI Test",
            "commit",
            "-qm",
            "baseline",
        ],
        cwd=repo,
        check=True,
    )
    (repo / "a.txt").write_text("one\ntwo\n", encoding="utf-8")
    return repo


@pytest.mark.xfail(reason="green after W4", strict=True)
def test_missing_model_chain_prints_one_line_without_a_traceback(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Bug: the failure is one configuration line with no stack trace."""
    repo = _repo_with_a_change(tmp_path, monkeypatch)
    monkeypatch.chdir(repo)

    result = runner.invoke(app, ["review"], env=_DUMB_ENV)

    output = compact_cli_text(result.stdout + result.stderr)
    assert result.exit_code == CLI_CONFIGURATION_EXIT_CODE, output
    assert _MESSAGE in output
    assert "Traceback" not in result.stdout
    assert "Traceback" not in result.stderr
