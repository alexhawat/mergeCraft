"""Lane A AP1.1 — manifest / xrepo rev guards (MCB-33)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mergecraft.xrepo.review import _rev_parse_commit

pytestmark = pytest.mark.xfail(
    reason="green after AP2: reject_if_leading_dash + --end-of-options in _rev_parse_commit",
    strict=False,
)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "linked"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "t"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "f").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "f"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    return repo


def test_leading_dash_rev_is_rejected(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    with pytest.raises(ValueError, match=r"dash|ref|rev"):
        _rev_parse_commit(repo, "-evil")


def test_rev_parse_passes_end_of_options(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _init_repo(tmp_path)
    seen: list[list[str]] = []
    real_run = subprocess.run

    def _record_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.append(list(cmd))
        return real_run(cmd, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(subprocess, "run", _record_run)
    sha = real_run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert _rev_parse_commit(repo, sha) == sha
    assert any("--end-of-options" in argv for argv in seen)
