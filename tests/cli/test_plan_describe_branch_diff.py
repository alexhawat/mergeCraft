"""``plan`` leaves the checkout clean and ``describe`` sees committed branch work (#1340)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from mergecraft.cli.app import app

if TYPE_CHECKING:
    import pytest

_ENV = {"NO_COLOR": "1", "TERM": "dumb"}


def _git(root: Path, *args: str) -> str:
    """Run one git command in *root* and return stdout."""
    completed = subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)
    return completed.stdout


def _repo_with_branch_commit(root: Path) -> None:
    """Create ``main`` with one file and a ``feat`` branch with a committed change."""
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "Test")
    (root / "app.py").write_text("print(1)\n", encoding="utf-8")
    _git(root, "add", "app.py")
    _git(root, "commit", "-q", "-m", "init")
    _git(root, "checkout", "-q", "-b", "feat")
    (root / "feature.py").write_text("def feature():\n    return 2\n", encoding="utf-8")
    _git(root, "add", "feature.py")
    _git(root, "commit", "-q", "-m", "feat")


def test_plan_leaves_git_status_clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A plan preview writes nothing into the repository."""
    _repo_with_branch_commit(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, ["plan", "--cwd", str(tmp_path)], env=_ENV)

    assert result.exit_code == 0, result.stdout + result.stderr
    assert _git(tmp_path, "status", "--porcelain", "--untracked-files=all") == ""


def test_plan_report_diff_lives_outside_the_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The persisted plan diff is readable after return and is not under the repo."""
    from mergecraft.cli.plan_cmd import build_plan_report

    _repo_with_branch_commit(tmp_path)
    monkeypatch.chdir(tmp_path)

    report = build_plan_report(cwd=tmp_path)

    diff_path = Path(str(report["diff_path"]))
    assert diff_path.is_file()
    assert not diff_path.resolve().is_relative_to(tmp_path.resolve())
    assert "feature.py" in diff_path.read_text(encoding="utf-8")


def test_describe_lists_committed_branch_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``describe`` on a branch with committed work reports those files."""
    _repo_with_branch_commit(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        app, ["--format", "json", "describe", "--repo-root", str(tmp_path)], env=_ENV
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert "feature.py" in payload["walkthrough"], payload
    assert "summarizes 0 changed files" not in payload["summary"], payload
