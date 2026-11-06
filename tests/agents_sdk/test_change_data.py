"""Regression coverage for workspace grounding across file types and worktrees."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mergecraft.agents_sdk.change_data import (
    _MAX_DIFF_BYTES,
    _MAX_FILE_BYTES,
    materialize_workspace_change,
)


def _patch(*paths: str) -> str:
    return "".join(
        f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-old\n+new\n"
        for path in paths
    )


@pytest.fixture
def linked_worktree(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    git("init", "-b", "main")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    (repo / "app.py").write_text("old\n", encoding="utf-8")
    git("add", "app.py")
    git("commit", "-m", "initial")
    worktree = tmp_path / "worktree"
    git("worktree", "add", "-b", "review", str(worktree))
    (worktree / "app.py").write_text("new\n", encoding="utf-8")
    return worktree


@pytest.mark.asyncio
async def test_linked_worktree_materializes_real_diff(linked_worktree: Path) -> None:
    assert (linked_worktree / ".git").is_file()
    result = await materialize_workspace_change(linked_worktree, base="main")
    assert "error" not in result
    assert "+new" in result["diff"]
    assert result["changed_paths"] == ["app.py"]
    assert result["files"] == {"app.py": "new\n"}


@pytest.mark.asyncio
async def test_invalid_git_base_is_not_a_clean_review(linked_worktree: Path) -> None:
    result = await materialize_workspace_change(linked_worktree, base="missing-ref")
    assert result.get("error")
    assert "files" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("binary", [b"\x89PNG\xff", b"a\x00b", b"caf\xe9"])
async def test_binary_file_does_not_hide_text_change(tmp_path: Path, binary: bytes) -> None:
    (tmp_path / "app.py").write_text("new\n", encoding="utf-8")
    (tmp_path / "asset.bin").write_bytes(binary)
    (tmp_path / "change.patch").write_text(_patch("app.py", "asset.bin"), encoding="utf-8")
    result = await materialize_workspace_change(tmp_path, diff="change.patch")
    assert result["files"] == {"app.py": "new\n"}
    assert result["changed_paths"] == ["app.py", "asset.bin"]
    assert result["skipped_files"]["asset.bin"] in {"binary content", "non-UTF-8 content"}
    assert "+new" in result["diff"]


@pytest.mark.asyncio
async def test_oversized_file_is_reported_without_loading_content(tmp_path: Path) -> None:
    (tmp_path / "large.txt").write_bytes(b"x" * (_MAX_FILE_BYTES + 1))
    result = await materialize_workspace_change(tmp_path, allowed_paths=frozenset({"large.txt"}))
    assert result["files"] == {}
    assert "byte limit" in result["skipped_files"]["large.txt"]


@pytest.mark.asyncio
async def test_unreadable_file_does_not_abort_grounding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "app.py"
    source.write_text("new\n", encoding="utf-8")
    original = Path.open

    def fail_source(path: Path, *args: object, **kwargs: object):
        if path == source:
            raise PermissionError("unreadable")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_source)
    result = await materialize_workspace_change(tmp_path, allowed_paths=frozenset({"app.py"}))
    assert result["files"] == {}
    assert result["skipped_files"] == {"app.py": "unreadable file"}


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["missing", "non-utf8", "binary", "oversized"])
async def test_unusable_diff_returns_explicit_error(tmp_path: Path, case: str) -> None:
    # Keep multi-megabyte payloads out of pytest node IDs and CI log lines.
    content = {
        "missing": None,
        "non-utf8": b"\xff",
        "binary": b"a\x00b",
    }.get(case)
    if case == "oversized":
        content = b"x" * (_MAX_DIFF_BYTES + 1)
    if content is not None:
        (tmp_path / "change.patch").write_bytes(content)
    result = await materialize_workspace_change(tmp_path, diff="change.patch")
    assert result["error"].startswith("Cannot read diff:")
    assert "files" not in result


@pytest.mark.asyncio
async def test_allowed_paths_filter_diff_and_path_list(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("new\n", encoding="utf-8")
    (tmp_path / "private.txt").write_text("private\n", encoding="utf-8")
    (tmp_path / "change.patch").write_text(_patch("src/app.py", "private.txt"), encoding="utf-8")
    result = await materialize_workspace_change(
        tmp_path,
        diff="change.patch",
        allowed_paths=frozenset({"./src"}),
    )
    assert "private.txt" not in result["diff"]
    assert result["changed_paths"] == ["src/app.py"]
    assert result["files"] == {"src/app.py": "new\n"}
