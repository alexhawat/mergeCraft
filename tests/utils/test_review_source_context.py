"""Real repository boundaries for the optional result-cache source identity."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from loguru import logger

from mergecraft.utils.review_source_context import review_source_context_digest
from mergecraft.utils.workspace import confine_to_workspace


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def test_context_tracks_files_commits_and_moving_base(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    source = tmp_path / "dependency.py"
    source.write_text("result = 1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "first")
    _git(tmp_path, "branch", "base")
    first = review_source_context_digest(cwd=tmp_path, base_ref="base")
    assert first is not None
    assert first == review_source_context_digest(cwd=tmp_path, base_ref="base")
    source.write_text("result = 2\n")
    dirty = review_source_context_digest(cwd=tmp_path, base_ref="base")
    assert dirty is not None
    assert dirty != first
    _git(tmp_path, "commit", "-am", "second", "-q")
    committed = review_source_context_digest(cwd=tmp_path, base_ref="base")
    assert committed is not None
    assert committed != dirty
    _git(tmp_path, "branch", "-f", "base", "HEAD")
    moved = review_source_context_digest(cwd=tmp_path, base_ref="base")
    assert moved is not None
    assert moved != committed
    (tmp_path / "new_context.py").write_text("other = True\n")
    assert review_source_context_digest(cwd=tmp_path, base_ref="base") != moved


def test_unidentifiable_context_declines_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert review_source_context_digest(cwd=tmp_path, base_ref=None) is None
    _git(tmp_path, "init", "-q")
    assert review_source_context_digest(cwd=tmp_path, base_ref="HEAD") is not None
    (tmp_path / "large.py").write_text("value = 1\n")
    monkeypatch.setattr("mergecraft.utils.review_source_context._MAX_BYTES", 1)
    assert review_source_context_digest(cwd=tmp_path, base_ref="HEAD") is None


def test_source_fingerprint_never_follows_external_symlinks(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    external = tmp_path / "external"
    external.write_text("not review source")
    (repo / "link").symlink_to(external)
    assert review_source_context_digest(cwd=repo, base_ref=None) is None


def test_registered_external_link_target_can_change_tool_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, secondary = tmp_path / "repo", tmp_path / "secondary"
    repo.mkdir()
    secondary.mkdir()
    _git(repo, "init", "-q")
    external = secondary / "dependency.py"
    external.write_text("result = 1\n")
    (repo / "dependency.py").symlink_to(external)
    _git(repo, "add", "dependency.py")
    # Cross-repo acquisition registers secondary roots. Use the real tool
    # confinement rule without writing the user's global Git configuration.
    monkeypatch.setattr("mergecraft.utils.workspace._workspace_roots", {str(secondary)})
    visible = confine_to_workspace("dependency.py", base=str(repo))
    assert visible.read_text() == "result = 1\n"
    assert review_source_context_digest(cwd=repo, base_ref=None) is None
    external.write_text("result = 2\n")
    assert confine_to_workspace("dependency.py", base=str(repo)).read_text() == "result = 2\n"
    # The tracked link text did not change. Hashing only that text would reuse
    # a result despite different context reachable through the tool boundary.
    assert review_source_context_digest(cwd=repo, base_ref=None) is None


@pytest.mark.parametrize(
    "relative", ["reviews/run/snapshot.json", "analyzer-cache/tool/data", "audit.jsonl"]
)
def test_runtime_files_do_not_churn_cache_but_tracked_changes_do(
    tmp_path: Path, relative: str
) -> None:
    _git(tmp_path, "init", "-q")
    initial = review_source_context_digest(cwd=tmp_path, base_ref=None)
    assert initial is not None
    artifact = tmp_path / ".mergecraft" / relative
    artifact.parent.mkdir(parents=True)
    artifact.write_text("first\n")
    assert review_source_context_digest(cwd=tmp_path, base_ref=None) == initial
    artifact.write_text("second\n")
    assert review_source_context_digest(cwd=tmp_path, base_ref=None) == initial
    _git(tmp_path, "add", ".mergecraft")
    tracked = review_source_context_digest(cwd=tmp_path, base_ref=None)
    assert tracked != initial
    artifact.write_text("tracked change\n")
    assert review_source_context_digest(cwd=tmp_path, base_ref=None) != tracked


@pytest.mark.parametrize("bound", ["files", "bytes", "external"])
def test_cache_decline_emits_a_safe_debug_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bound: str
) -> None:
    _git(tmp_path, "init", "-q")
    path = tmp_path / "source.py"
    if bound == "external":
        path.symlink_to(tmp_path.parent / "outside")
        reason = "symlink resolves outside repository"
    else:
        path.write_text("synthetic-sensitive-content")
        monkeypatch.setattr(
            "mergecraft.utils.review_source_context."
            + ("_MAX_FILES" if bound == "files" else "_MAX_BYTES"),
            0,
        )
        reason = f"source exceeds 0 {bound}"
    logs: list[str] = []
    sink = logger.add(lambda message: logs.append(str(message)), level="DEBUG")
    try:
        assert review_source_context_digest(cwd=tmp_path, base_ref=None) is None
    finally:
        logger.remove(sink)
    assert any(reason in entry for entry in logs)
    assert all("synthetic-sensitive-content" not in entry for entry in logs)
