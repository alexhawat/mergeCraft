"""Exclusions become visible review-coverage limitations (RA1.5, D11/D12).

Every eligible-source skip — oversized, binary, symlink — must be reported on
the result. Gitignored untracked artifacts are outside the review scope.
"Empty because nothing changed" must be
distinguishable from "empty because everything was excluded", so an excluded
run cannot render as a passed review with "no changes to review".
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from typer.testing import CliRunner

if TYPE_CHECKING:
    import pytest

from mergecraft.utils.offline_diff import materialize_diff


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _init_repo(tmp_path: Path, *, gitignore: str | None = None) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "existing.py").write_text("def existing():\n    return 1\n", encoding="utf-8")
    if gitignore is not None:
        (repo / ".gitignore").write_text(gitignore, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")
    _git(repo, "checkout", "-b", "feature")
    return repo


def _limitations(result: Any) -> Any:
    return getattr(result, "coverage_limitations", None)


def _reports(limitations: Any, needle: str) -> bool:
    return any(needle in str(item) for item in (limitations or ()))


def test_exclusions_are_reported_as_review_coverage_limitations(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, gitignore="ignored.py\n")
    (repo / "ignored.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "huge.py").write_bytes(b"x = 1\n" + b"# pad\n" * 60_000)
    (repo / "blob.bin").write_bytes(b"\x00\x01\x02\x03")

    result = materialize_diff(cwd=repo, out_dir=tmp_path / "out", base="main")

    limitations = _limitations(result)
    assert limitations, "excluded files were not reported as coverage limitations"
    assert not _reports(limitations, "ignored.py")
    for name in ("huge.py", "blob.bin"):
        assert _reports(limitations, name), f"{name} was silently excluded"


def test_empty_because_nothing_changed_is_distinguishable_from_empty_because_excluded(
    tmp_path: Path,
) -> None:
    clean = _init_repo(tmp_path / "clean")
    clean_result = materialize_diff(cwd=clean, out_dir=tmp_path / "clean-out", base="main")

    excluded = _init_repo(tmp_path / "excluded")
    (excluded / "huge.py").write_bytes(b"x = 1\n" + b"# pad\n" * 60_000)
    excluded_result = materialize_diff(cwd=excluded, out_dir=tmp_path / "excluded-out", base="main")

    assert clean_result.empty is True
    assert not _limitations(clean_result), "a clean repo reported coverage limitations"
    assert _limitations(excluded_result), (
        "an all-excluded diff is indistinguishable from a clean one"
    )


def test_clean_checkout_with_ignored_environment_is_a_clean_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real selector and CLI outcomes distinguish artifacts from omitted source."""
    from mergecraft.cli.app import app

    monkeypatch.delenv("MERGECRAFT_CONFIG", raising=False)
    repo = _init_repo(tmp_path, gitignore=".venv/\n.cache/\n.env\n")
    for name in (".venv/installed.py", ".cache/build/output", ".env"):
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ordinary ignored artifact\n", encoding="utf-8")
    assert _git(repo, "status", "--porcelain") == ""

    runner = CliRunner()
    args = ["review", "--cwd", str(repo), "--base", "main", "--dry-run"]
    clean = runner.invoke(app, args)
    assert clean.exit_code == 0, clean.output
    assert "no changes to review" in clean.output

    (repo / "huge.py").write_bytes(b"# source\n" * 40_000)
    excluded = runner.invoke(app, args)
    assert excluded.exit_code == 20, excluded.output
    assert "oversized" in excluded.output
    assert "huge.py" in excluded.output
    assert "gitignored path" not in excluded.output
