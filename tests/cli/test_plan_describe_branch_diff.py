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


def _pushed_branch_repo(tmp_path: Path) -> Path:
    """Clone of a bare remote with ``feat`` committed and pushed with ``-u``."""
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    root = tmp_path / "work"
    root.mkdir()
    _repo_with_branch_commit(root)
    _git(root, "remote", "add", "origin", str(remote))
    _git(root, "push", "-q", "origin", "main")
    _git(root, "push", "-q", "-u", "origin", "feat")
    _git(root, "remote", "set-head", "origin", "main")
    return root


def _describe_json(root: Path, *extra: str) -> dict[str, object]:
    """Run ``describe --format json`` on *root* and return the payload."""
    result = CliRunner().invoke(
        app, ["--format", "json", "describe", "--repo-root", str(root), *extra], env=_ENV
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def test_describe_after_push_u_diffs_against_the_target_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``@{upstream}`` is ``origin/feat`` here; the diff must still cover the branch work."""
    root = _pushed_branch_repo(tmp_path)
    monkeypatch.chdir(root)
    assert _git(root, "rev-parse", "--abbrev-ref", "@{upstream}").strip() == "origin/feat"

    payload = _describe_json(root)

    assert "feature.py" in str(payload["walkthrough"]), payload


def test_describe_base_flag_selects_the_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--base`` wins: against ``origin/feat`` the pushed branch has no changes."""
    root = _pushed_branch_repo(tmp_path)
    monkeypatch.chdir(root)

    assert "feature.py" in str(_describe_json(root, "--base", "main")["walkthrough"])
    assert "feature.py" not in str(_describe_json(root, "--base", "origin/feat")["walkthrough"])


def test_describe_unknown_base_is_a_configuration_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit base that does not exist fails instead of describing nothing."""
    root = _pushed_branch_repo(tmp_path)
    monkeypatch.chdir(root)
    result = CliRunner().invoke(
        app, ["describe", "--repo-root", str(root), "--base", "no-such-ref"], env=_ENV
    )
    assert result.exit_code == 30, result.stdout + result.stderr


def test_plan_after_push_u_diffs_against_the_target_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``plan`` shares the target-branch default and honours ``--base``."""
    from mergecraft.cli.plan_cmd import build_plan_report

    root = _pushed_branch_repo(tmp_path)
    monkeypatch.chdir(root)

    report = build_plan_report(cwd=root)
    assert report["base_ref"] == "origin/main"
    assert "feature.py" in Path(str(report["diff_path"])).read_text(encoding="utf-8")

    pinned = build_plan_report(cwd=root, base="origin/feat")
    assert pinned["base_ref"] == "origin/feat"
    assert "feature.py" not in Path(str(pinned["diff_path"])).read_text(encoding="utf-8")


def test_plan_unknown_base_is_a_configuration_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``plan --base <unknown>`` prints one error line and exits 30, like ``describe``."""
    root = _pushed_branch_repo(tmp_path)
    monkeypatch.chdir(root)
    result = CliRunner().invoke(
        app, ["plan", "--cwd", str(root), "--base", "no-such-ref"], env=_ENV
    )
    output = result.stdout + result.stderr
    assert result.exit_code == 30, (result.exception, output)
    assert "Traceback" not in output
    assert "no-such-ref" in output


def test_target_base_on_main_never_picks_a_sibling_branch(tmp_path: Path) -> None:
    """On ``main`` with ``origin/HEAD`` unset, ``develop`` is not the base."""
    from mergecraft.cli.diff_base import target_base

    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    root = tmp_path / "work"
    root.mkdir()
    _repo_with_branch_commit(root)
    _git(root, "branch", "-q", "develop", "feat")
    _git(root, "checkout", "-q", "main")
    _git(root, "remote", "add", "origin", str(remote))
    _git(root, "push", "-q", "-u", "origin", "main", "develop")
    unset = subprocess.run(
        ["git", "symbolic-ref", "-q", "refs/remotes/origin/HEAD"], cwd=root, check=False
    )
    assert unset.returncode != 0

    base = target_base(root)

    assert "develop" not in base
    assert base in {"origin/main", "main", "HEAD^"}
