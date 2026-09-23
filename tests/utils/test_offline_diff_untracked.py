"""Default local review includes eligible untracked additions (RA1.5, N7/D11).

A repository with a committed ``existing.py`` and an untracked ``new_bug.py``
produced ``empty=True`` under default materialization, and the offline review
mapped that to a passed review. These tests use real Git in disposable repos —
a mocked runner returning a canned diff cannot see what ``git diff`` omits.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

from mergecraft.utils.offline_diff import (
    git_range_diff,
    git_staged_diff,
    git_unstaged_diff,
    materialize_diff,
)


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
    repo.mkdir()
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


def test_default_materialization_includes_an_untracked_addition(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    (repo / "new_bug.py").write_text("def bug():\n    return 1 / 0\n", encoding="utf-8")

    result = materialize_diff(cwd=repo, out_dir=tmp_path / "out", base="main")

    text = result.path.read_text(encoding="utf-8")
    assert "new_bug.py" in text
    assert result.empty is False


def test_default_materialization_skips_managed_analyzer_cache_but_keeps_source(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Generated analyzer cache entries are not untracked source additions."""
    import mergecraft.utils.offline_diff as offline_diff

    repo = _init_repo(tmp_path)
    cache_file = (
        repo / ".mergecraft" / "analyzer-cache" / "pip" / "semgrep" / "1.170.0" / "module.py"
    )
    cache_file.parent.mkdir(parents=True)
    cache_file.write_text("cache_payload = 1\n", encoding="utf-8")
    sibling = repo / ".mergecraft" / "analyzer-cache-copy" / "module.py"
    sibling.parent.mkdir(parents=True)
    sibling.write_text("sibling_payload = 1\n", encoding="utf-8")
    source = repo / "src" / "new_bug.py"
    source.parent.mkdir(parents=True)
    source.write_text("def bug():\n    return 1 / 0\n", encoding="utf-8")
    config = repo / ".mergecraft" / "config.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("models: [anthropic/claude-sonnet]\n", encoding="utf-8")

    git_calls: list[list[str]] = []
    real_run_git = offline_diff._run_git

    def spy_run_git(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        git_calls.append(args)
        return real_run_git(args, **kwargs)

    monkeypatch.setattr(offline_diff, "_run_git", spy_run_git)
    cache_reads: list[Path] = []
    real_read_bytes = Path.read_bytes

    def spy_read_bytes(path: Path) -> bytes:
        if path == cache_file:
            cache_reads.append(path)
        return real_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", spy_read_bytes)

    result = materialize_diff(cwd=repo, out_dir=tmp_path / "out", base="main")
    text = result.path.read_text(encoding="utf-8")

    assert "src/new_bug.py" in text
    assert ".mergecraft/config.yaml" in text
    assert ".mergecraft/analyzer-cache-copy/module.py" in text
    assert ".mergecraft/analyzer-cache/pip/semgrep/1.170.0/module.py" not in text
    assert cache_reads == []
    cache_rel = cache_file.relative_to(repo).as_posix()
    assert not any(args[:2] == ["diff", "--no-index"] and cache_rel in args for args in git_calls)


def test_unstaged_diff_skips_managed_analyzer_cache(tmp_path: Path) -> None:
    """The explicit unstaged path shares the managed-cache exclusion."""
    repo = _init_repo(tmp_path)
    cache_file = (
        repo / ".mergecraft" / "analyzer-cache" / "pip" / "semgrep" / "1.170.0" / "module.py"
    )
    cache_file.parent.mkdir(parents=True)
    cache_file.write_text("cache_payload = 1\n", encoding="utf-8")
    source = repo / "src" / "new_bug.py"
    source.parent.mkdir(parents=True)
    source.write_text("def bug():\n    return 1 / 0\n", encoding="utf-8")

    text = git_unstaged_diff(cwd=repo)

    assert "src/new_bug.py" in text
    assert ".mergecraft/analyzer-cache/pip/semgrep/1.170.0/module.py" not in text


def test_tracked_analyzer_cache_change_remains_in_default_diff(tmp_path: Path) -> None:
    """The reserved path only excludes untracked runtime artifacts."""
    repo = _init_repo(tmp_path)
    cache_file = repo / ".mergecraft" / "analyzer-cache" / "tracked.py"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_text("cache_payload = 1\n", encoding="utf-8")
    _git(repo, "add", "-f", str(cache_file.relative_to(repo)))
    _git(repo, "commit", "-m", "track cache fixture")
    cache_file.write_text("cache_payload = 2\n", encoding="utf-8")

    result = materialize_diff(cwd=repo, out_dir=tmp_path / "out", base="main")
    text = result.path.read_text(encoding="utf-8")

    assert ".mergecraft/analyzer-cache/tracked.py" in text
    assert "cache_payload = 2" in text


def test_mixed_tracked_and_untracked_changes_include_both(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    (repo / "existing.py").write_text("def existing():\n    return 2\n", encoding="utf-8")
    _git(repo, "add", "existing.py")
    _git(repo, "commit", "-m", "tracked change")
    (repo / "new_bug.py").write_text("def bug():\n    return 1 / 0\n", encoding="utf-8")

    result = materialize_diff(cwd=repo, out_dir=tmp_path / "out", base="main")

    text = result.path.read_text(encoding="utf-8")
    assert "existing.py" in text
    assert "new_bug.py" in text


def test_staged_mode_semantics_are_unchanged(tmp_path: Path) -> None:
    """Guard — staged mode has a defined meaning and untracked files are not in it."""
    repo = _init_repo(tmp_path)
    (repo / "existing.py").write_text("def existing():\n    return 3\n", encoding="utf-8")
    _git(repo, "add", "existing.py")
    (repo / "new_bug.py").write_text("def bug():\n    return 1 / 0\n", encoding="utf-8")

    text = git_staged_diff(cwd=repo)

    assert "existing.py" in text
    assert "new_bug.py" not in text


def test_commit_range_semantics_are_unchanged(tmp_path: Path) -> None:
    """Guard — a committed range never picks up untracked working-tree files."""
    repo = _init_repo(tmp_path)
    (repo / "existing.py").write_text("def existing():\n    return 4\n", encoding="utf-8")
    _git(repo, "add", "existing.py")
    _git(repo, "commit", "-m", "tracked change")
    (repo / "new_bug.py").write_text("def bug():\n    return 1 / 0\n", encoding="utf-8")

    text = git_range_diff(cwd=repo, range_spec="main..feature")

    assert "existing.py" in text
    assert "new_bug.py" not in text


def test_gitignored_file_is_excluded(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, gitignore="ignored.py\n")
    (repo / "ignored.py").write_text("def ignored():\n    return 1 / 0\n", encoding="utf-8")

    result = materialize_diff(cwd=repo, out_dir=tmp_path / "out", base="main")

    assert "ignored.py" not in result.path.read_text(encoding="utf-8")
    assert _reports(_limitations(result), "ignored.py")


def test_oversized_untracked_file_is_excluded_and_reported(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    (repo / "huge.py").write_bytes(b"x = 1\n" + b"# pad\n" * 60_000)

    result = materialize_diff(cwd=repo, out_dir=tmp_path / "out", base="main")

    assert "huge.py" not in result.path.read_text(encoding="utf-8")
    assert _reports(_limitations(result), "huge.py")


def test_binary_untracked_file_is_excluded_and_reported(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    (repo / "blob.bin").write_bytes(b"\x00\x01\x02\x03")

    result = materialize_diff(cwd=repo, out_dir=tmp_path / "out", base="main")

    assert "blob.bin" not in result.path.read_text(encoding="utf-8")
    assert _reports(_limitations(result), "blob.bin")


def test_symlink_is_excluded(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    (repo / "target.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "link.py").symlink_to(repo / "target.py")

    result = materialize_diff(cwd=repo, out_dir=tmp_path / "out", base="main")

    assert "link.py" not in result.path.read_text(encoding="utf-8")
    assert _reports(_limitations(result), "link.py")


def test_unicode_quoted_path_is_included(tmp_path: Path) -> None:
    """The path round-trips into the materialized diff (adjacent to residual R5)."""
    repo = _init_repo(tmp_path)
    _git(repo, "config", "core.quotepath", "false")
    (repo / "ünïcode_bug.py").write_text("def bug():\n    return 1 / 0\n", encoding="utf-8")

    result = materialize_diff(cwd=repo, out_dir=tmp_path / "out", base="main")

    assert "ünïcode_bug.py" in result.path.read_text(encoding="utf-8")
