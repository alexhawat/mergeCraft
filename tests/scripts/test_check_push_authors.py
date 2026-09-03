"""``scripts/check_push_authors.py`` — client-side pre-push author allowlist guard.

Companion to ``trust.sandboxTrustedAuthors`` (``src/mergecraft/config/trust_policy.py``):
this catches a fork PR checked out onto a local branch and pushed to ``origin``
*before* it reaches origin. It is a guardrail, not a gate — an undeterminable
range must pass, never block.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "check_push_authors", _ROOT / "scripts" / "check_push_authors.py"
)
assert _SPEC is not None
assert _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
main = _MOD.main


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=True)


def _init_repo(repo: Path) -> None:
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.com")


def _commit(repo: Path, *, author_email: str, committer_email: str, message: str) -> str:
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = "Test Author"
    env["GIT_AUTHOR_EMAIL"] = author_email
    env["GIT_COMMITTER_NAME"] = "Test Committer"
    env["GIT_COMMITTER_EMAIL"] = committer_email
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", message],
        cwd=str(repo),
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """A fresh, isolated git repo; the script's module-level REPO points at it."""
    target = tmp_path / "repo"
    target.mkdir()
    _init_repo(target)
    monkeypatch.setattr(_MOD, "REPO", target)
    monkeypatch.setattr(_MOD, "ALLOWLIST_PATH", target / ".github" / "trusted-authors.txt")
    monkeypatch.delenv("PRE_COMMIT_FROM_REF", raising=False)
    monkeypatch.delenv("PRE_COMMIT_TO_REF", raising=False)
    monkeypatch.delenv("MERGECRAFT_TRUSTED_AUTHORS", raising=False)
    return target


def test_range_with_only_trusted_authors_passes(
    repo: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    base_sha = _commit(
        repo,
        author_email="trusted@example.com",
        committer_email="trusted@example.com",
        message="base",
    )
    head_sha = _commit(
        repo,
        author_email="trusted@example.com",
        committer_email="trusted@example.com",
        message="head",
    )
    monkeypatch.setenv("MERGECRAFT_TRUSTED_AUTHORS", "trusted@example.com")

    assert main(["--range", f"{base_sha}..{head_sha}"]) == 0
    assert "refusing" not in capsys.readouterr().err.lower()


def test_foreign_author_fails_with_address_named(
    repo: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    base_sha = _commit(
        repo,
        author_email="trusted@example.com",
        committer_email="trusted@example.com",
        message="base",
    )
    head_sha = _commit(
        repo,
        author_email="attacker@evil.example",
        committer_email="attacker@evil.example",
        message="head",
    )
    monkeypatch.setenv("MERGECRAFT_TRUSTED_AUTHORS", "trusted@example.com")

    exit_code = main(["--range", f"{base_sha}..{head_sha}"])
    err = capsys.readouterr().err

    assert exit_code == 1
    assert "attacker@evil.example" in err
    assert head_sha[:12] in err
    assert "trusted-authors.txt" in err
    assert "--no-verify" in err


def test_env_var_allowlist_overrides_file(
    repo: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """The env var wins even when the committed file would refuse the same commit."""
    (repo / ".github").mkdir()
    (repo / ".github" / "trusted-authors.txt").write_text(
        "# only this address is on the file allowlist\nfile-only@example.com\n", encoding="utf-8"
    )
    base_sha = _commit(
        repo,
        author_email="env-only@example.com",
        committer_email="env-only@example.com",
        message="base",
    )
    head_sha = _commit(
        repo,
        author_email="env-only@example.com",
        committer_email="env-only@example.com",
        message="head",
    )
    monkeypatch.setenv("MERGECRAFT_TRUSTED_AUTHORS", "env-only@example.com")

    assert main(["--range", f"{base_sha}..{head_sha}"]) == 0
    assert "refusing" not in capsys.readouterr().err.lower()


def test_file_allowlist_used_when_no_env_var(
    repo: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Regression for the override test above — the file alone still gates."""
    (repo / ".github").mkdir()
    (repo / ".github" / "trusted-authors.txt").write_text(
        "file-only@example.com\n", encoding="utf-8"
    )
    base_sha = _commit(
        repo,
        author_email="env-only@example.com",
        committer_email="env-only@example.com",
        message="base",
    )
    head_sha = _commit(
        repo,
        author_email="env-only@example.com",
        committer_email="env-only@example.com",
        message="head",
    )

    exit_code = main(["--range", f"{base_sha}..{head_sha}"])
    assert exit_code == 1
    assert "env-only@example.com" in capsys.readouterr().err


def test_undeterminable_range_passes(repo: Path) -> None:
    """No explicit range, no PRE_COMMIT_*_REF, no upstream, no origin — never blocks."""
    _commit(
        repo, author_email="whoever@example.com", committer_email="whoever@example.com", message="c"
    )
    assert main([]) == 0


def test_comparison_is_case_insensitive(
    repo: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    base_sha = _commit(
        repo,
        author_email="Mixed-Case@Example.com",
        committer_email="Mixed-Case@Example.com",
        message="base",
    )
    head_sha = _commit(
        repo,
        author_email="Mixed-Case@Example.com",
        committer_email="Mixed-Case@Example.com",
        message="head",
    )
    monkeypatch.setenv("MERGECRAFT_TRUSTED_AUTHORS", "mixed-case@example.com")

    exit_code = main(["--range", f"{base_sha}..{head_sha}"])
    assert exit_code == 0
    assert "refusing" not in capsys.readouterr().err.lower()


def test_pre_commit_from_to_ref_env_vars_are_used(
    repo: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """PRE_COMMIT_FROM_REF/TO_REF take precedence when no explicit --range is given."""
    base_sha = _commit(
        repo,
        author_email="attacker@evil.example",
        committer_email="attacker@evil.example",
        message="base",
    )
    head_sha = _commit(
        repo,
        author_email="attacker@evil.example",
        committer_email="attacker@evil.example",
        message="head",
    )
    monkeypatch.setenv("PRE_COMMIT_FROM_REF", base_sha)
    monkeypatch.setenv("PRE_COMMIT_TO_REF", head_sha)
    monkeypatch.setenv("MERGECRAFT_TRUSTED_AUTHORS", "trusted@example.com")

    exit_code = main([])
    assert exit_code == 1
    assert "attacker@evil.example" in capsys.readouterr().err


# --- #623 — a first push to a new remote branch must not bypass the guard ----

_ZERO_SHA = "0" * 40
_ZERO_SHA_256 = "0" * 64


def _repo_with_origin_default(repo: Path, *, author_email: str) -> None:
    """Give ``repo`` an ``origin/main`` to resolve against, then a branch commit.

    Mirrors the real shape of the bypass: a branch whose commits are not yet on
    the remote, pushed for the first time, so git hands the hook an all-zeros
    ``<remote-sha>``.
    """
    _commit(
        repo,
        author_email="trusted@example.com",
        committer_email="trusted@example.com",
        message="base",
    )
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    _git(repo, "checkout", "-q", "-b", "feature")
    _commit(repo, author_email=author_email, committer_email=author_email, message="branch work")


def test_new_remote_branch_still_checks_authors(repo: Path, monkeypatch: MonkeyPatch) -> None:
    """The #623 bypass: an all-zeros from-ref must not skip the author check.

    Git's pre-push protocol sends an all-zeros ``<remote-sha>`` when the remote
    ref does not exist yet, and pre-commit forwards it as
    ``PRE_COMMIT_FROM_REF``. Passing that through as a range made ``git log``
    fail, which the script treated as "undeterminable, pass" — turning the
    guard into a no-op on exactly the push it exists to catch (a fork branch
    pushed to ``origin`` for the first time).
    """
    _repo_with_origin_default(repo, author_email="attacker@evil.example")
    monkeypatch.setenv("MERGECRAFT_TRUSTED_AUTHORS", "trusted@example.com")
    monkeypatch.setenv("PRE_COMMIT_FROM_REF", _ZERO_SHA)
    monkeypatch.setenv("PRE_COMMIT_TO_REF", "HEAD")

    assert main([]) == 1, "a new-branch push with a foreign author must be refused"


def test_new_remote_branch_passes_for_trusted_authors(repo: Path, monkeypatch: MonkeyPatch) -> None:
    """The new-branch path resolves a real range, so trusted commits still pass."""
    _repo_with_origin_default(repo, author_email="trusted@example.com")
    monkeypatch.setenv("MERGECRAFT_TRUSTED_AUTHORS", "trusted@example.com")
    monkeypatch.setenv("PRE_COMMIT_FROM_REF", _ZERO_SHA)
    monkeypatch.setenv("PRE_COMMIT_TO_REF", "HEAD")

    assert main([]) == 0


def test_new_remote_branch_sentinel_is_matched_by_shape(
    repo: Path, monkeypatch: MonkeyPatch
) -> None:
    """A SHA-256 repository spells the same sentinel with 64 zeros, not 40."""
    _repo_with_origin_default(repo, author_email="attacker@evil.example")
    monkeypatch.setenv("MERGECRAFT_TRUSTED_AUTHORS", "trusted@example.com")
    monkeypatch.setenv("PRE_COMMIT_FROM_REF", _ZERO_SHA_256)
    monkeypatch.setenv("PRE_COMMIT_TO_REF", "HEAD")

    assert main([]) == 1


def test_branch_deletion_passes_without_error(
    repo: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """An all-zeros *to*-ref is a branch deletion — nothing to check, pass cleanly."""
    _repo_with_origin_default(repo, author_email="attacker@evil.example")
    monkeypatch.setenv("MERGECRAFT_TRUSTED_AUTHORS", "trusted@example.com")
    monkeypatch.setenv("PRE_COMMIT_FROM_REF", "HEAD")
    monkeypatch.setenv("PRE_COMMIT_TO_REF", _ZERO_SHA)

    assert main([]) == 0
    assert "branch deletion" in capsys.readouterr().err
