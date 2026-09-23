"""Init scaffolds ignores for generated managed analyzer state."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from tests.cli.support_init_audit_jsonl import git_check_ignores, gitignore_path
from tests.cli.test_init_audit_jsonl_gitignore import _init_git_repo
from typer.testing import CliRunner

from mergecraft.cli.app import app

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()

ANALYZER_CACHE_GITIGNORE_LINE = ".mergecraft/analyzer-cache/"
ANALYZERS_LOCK_GITIGNORE_LINE = ".mergecraft/analyzers.lock"


def test_init_scaffolds_analyzer_runtime_gitignore_lines(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Init ignores the cache and lock written by managed analyzers."""
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["init", "--force"])

    assert result.exit_code == 0, result.output
    text = gitignore_path(tmp_path).read_text(encoding="utf-8")
    assert ANALYZER_CACHE_GITIGNORE_LINE in text
    assert ANALYZERS_LOCK_GITIGNORE_LINE in text


def test_init_ignores_analyzer_runtime_files_after_provisioning(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Generated cache entries and lock state stay out of ``git status``."""
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init", "--force"])
    assert result.exit_code == 0, result.output

    cache_file = tmp_path / ".mergecraft" / "analyzer-cache" / "pip" / "semgrep" / "module.py"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_text("cache_payload = 1\n", encoding="utf-8")
    lock_file = tmp_path / ".mergecraft" / "analyzers.lock"
    lock_file.write_text("generated lock\n", encoding="utf-8")

    assert git_check_ignores(tmp_path, ".mergecraft/analyzer-cache/pip/semgrep/module.py")
    assert git_check_ignores(tmp_path, ".mergecraft/analyzers.lock")


def test_init_does_not_duplicate_analyzer_runtime_gitignore_lines(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Re-running init keeps each generated-state ignore line singular."""
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    first = runner.invoke(app, ["init", "--force"])
    second = runner.invoke(app, ["init", "--force"])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    text = gitignore_path(tmp_path).read_text(encoding="utf-8")
    assert text.count(ANALYZER_CACHE_GITIGNORE_LINE) == 1
    assert text.count(ANALYZERS_LOCK_GITIGNORE_LINE) == 1
