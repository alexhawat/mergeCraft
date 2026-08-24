"""Init scaffold must ignore durable local review artifacts under ``.mergecraft/reviews/``."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from tests.cli.support_init_audit_jsonl import (
    git_check_ignores,
    git_status_porcelain,
    gitignore_path,
)
from tests.cli.test_init_audit_jsonl_gitignore import _init_git_repo
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.review.completed import COMPLETED_REVIEWS_GITIGNORE_LINE

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()


def reviews_rel_path() -> str:
    return f"{COMPLETED_REVIEWS_GITIGNORE_LINE.rstrip('/')}/review-fixture/completed.json"


def reviews_path(repo_root: Path) -> Path:
    return repo_root / reviews_rel_path()


def test_init_scaffolds_reviews_gitignore_line(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Happy — init writes the explicit ``.mergecraft/reviews/`` ignore line."""
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init", "--force"])
    assert result.exit_code == 0, result.output
    text = gitignore_path(tmp_path).read_text(encoding="utf-8")
    assert COMPLETED_REVIEWS_GITIGNORE_LINE in text


def test_reviews_dir_is_gitignored_after_init(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Functional — ``git check-ignore`` accepts review artifacts after init."""
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init", "--force"])
    assert result.exit_code == 0, result.output
    rel = reviews_rel_path()
    reviews_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    reviews_path(tmp_path).write_text('{"schema_version":"1.0.0"}\n', encoding="utf-8")
    assert git_check_ignores(tmp_path, rel)


def test_reviews_dir_not_listed_as_untracked_after_init(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Functional — review artifacts do not appear in ``git status`` as untracked."""
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init", "--force"])
    assert result.exit_code == 0, result.output
    rel = reviews_rel_path()
    reviews_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    reviews_path(tmp_path).write_text('{"schema_version":"1.0.0"}\n', encoding="utf-8")
    status = git_status_porcelain(tmp_path, rel)
    assert status == ""


def test_init_does_not_duplicate_reviews_gitignore_line(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Edge — re-init with --force does not duplicate the reviews ignore line."""
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    first = runner.invoke(app, ["init", "--force"])
    assert first.exit_code == 0, first.output
    second = runner.invoke(app, ["init", "--force"])
    assert second.exit_code == 0, second.output
    text = gitignore_path(tmp_path).read_text(encoding="utf-8")
    assert text.count(COMPLETED_REVIEWS_GITIGNORE_LINE) == 1
