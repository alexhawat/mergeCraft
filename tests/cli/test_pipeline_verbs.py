"""AP6 pipeline CLI — ``mergecraft pipeline lint|show|explain`` (PR AP6).

Wave plan: ``.ignorelocal/03-agent-pipeline-wave-plan.md`` (PR AP6, AP6.1).
Covers ``src/mergecraft/cli/pipeline_cmd.py`` registered on ``mergecraft.cli.app``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from typer.testing import CliRunner

from mergecraft.cli.app import app

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()


def _write_pipeline(tmp_path: Path, body: str) -> None:
    from tests.orchestrator.conftest import write_pipeline_file, write_repo_config

    write_repo_config(tmp_path)
    write_pipeline_file(tmp_path, body)


def test_pipeline_lint_rejects_a_missing_agent_id(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    invalid_agent_pipeline_yaml: str,
) -> None:
    """``pipeline lint`` rejects a pipeline that references an unknown registry agent."""
    _write_pipeline(tmp_path, invalid_agent_pipeline_yaml)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["pipeline", "lint"])

    assert result.exit_code != 0, result.stdout + result.stderr
    output = (result.stdout + result.stderr).lower()
    if result.exception is not None:
        output += str(result.exception).lower()
    assert "mergecraft-nonexistent-agent" in output or "unknown" in output or "agent" in output


def test_pipeline_show_previews_steps_for_a_diff(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    conditional_pipeline_yaml: str,
) -> None:
    """``pipeline show`` previews which steps would run or skip for a diff."""
    from tests.orchestrator.conftest import write_sample_diff

    _write_pipeline(tmp_path, conditional_pipeline_yaml)
    diff_path = write_sample_diff(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["pipeline", "show", "--diff", str(diff_path)])

    assert result.exit_code == 0, result.stdout + result.stderr
    output = (result.stdout + result.stderr).lower()
    assert "review" in output
    assert "verify" in output
    assert "skip" in output or "run" in output or "when" in output
