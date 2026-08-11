"""Direct unit coverage for ``mergecraft.utils.workspace`` (W3 containment)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

import mergecraft.utils.workspace as workspace
from mergecraft.utils.workspace import (
    WorkspacePathError,
    add_safe_directory,
    ensure_github_workspace_registered,
    register_workspace_root,
    resolve_allowed_working_directory,
)

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


@pytest.fixture(autouse=True)
def _reset_workspace_registry() -> None:
    """Isolate module-level workspace / safe.directory registries per test."""
    workspace._workspace_roots.clear()
    workspace._safe_directories_added.clear()
    yield
    workspace._workspace_roots.clear()
    workspace._safe_directories_added.clear()


def test_workspace_path_error_is_value_error() -> None:
    """Direct ``WorkspacePathError`` — escape failures are typed ValueErrors."""
    err = WorkspacePathError("working_directory '/etc' is outside allowed workspace roots")
    assert isinstance(err, ValueError)
    assert "working_directory" in str(err)
    assert "outside" in str(err)


def test_add_safe_directory_invokes_git_config(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Direct ``add_safe_directory`` — must call ``git config --global --add``.

    Fails if the helper is deleted or no-ops: no git invocation is recorded.
    """
    calls: list[list[str]] = []

    def _fake_run(cmd: list[str], **_kwargs: object) -> object:
        calls.append(list(cmd))

        class _Result:
            returncode = 0

        return _Result()

    monkeypatch.setattr(workspace.subprocess, "run", _fake_run)
    target = tmp_path / "checkout"
    target.mkdir()
    add_safe_directory(str(target))

    assert calls, "add_safe_directory must invoke git"
    assert calls[0][:4] == ["git", "config", "--global", "--add"]
    assert calls[0][4] == "safe.directory"
    assert Path(calls[0][5]).resolve() == target.resolve()

    # Idempotent: second call must not re-add.
    add_safe_directory(str(target))
    assert len(calls) == 1


def test_register_workspace_root_records_and_marks_safe(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Direct ``register_workspace_root`` — root is allowed and safe.directory'd.

    Fails if registration is deleted: resolve escapes that should be allowed.
    """
    calls: list[list[str]] = []

    def _fake_run(cmd: list[str], **_kwargs: object) -> object:
        calls.append(list(cmd))

        class _Result:
            returncode = 0

        return _Result()

    monkeypatch.setattr(workspace.subprocess, "run", _fake_run)
    root = tmp_path / "ws"
    root.mkdir()
    register_workspace_root(str(root))

    assert str(root.resolve()) in workspace._workspace_roots
    assert calls
    assert calls[0][4] == "safe.directory"

    inside = root / "pkg"
    inside.mkdir()
    resolved = resolve_allowed_working_directory(str(inside), default=str(root))
    assert Path(resolved) == inside.resolve()


def test_ensure_github_workspace_registered_reads_env(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Direct ``ensure_github_workspace_registered`` — registers ``$GITHUB_WORKSPACE``.

    Fails if the helper ignores the env var: the path never enters the registry.
    """
    monkeypatch.setattr(workspace.subprocess, "run", lambda *_a, **_k: None)
    ws = tmp_path / "gha-workspace"
    ws.mkdir()
    monkeypatch.setenv("GITHUB_WORKSPACE", str(ws))

    ensure_github_workspace_registered()
    assert str(ws.resolve()) in workspace._workspace_roots


def test_ensure_github_workspace_registered_noops_when_unset(
    monkeypatch: MonkeyPatch,
) -> None:
    """Direct ``ensure_github_workspace_registered`` — empty/missing env is a no-op."""
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
    ensure_github_workspace_registered()
    assert not workspace._workspace_roots


@pytest.mark.parametrize(
    "escape",
    ["/etc", "..", "/", "/private/etc"],
    ids=["absolute-etc", "dotdot", "root", "alias-etc"],
)
def test_resolve_allowed_working_directory_rejects_escapes(tmp_path: Path, escape: str) -> None:
    """Direct ``resolve_allowed_working_directory`` — escapes raise ``WorkspacePathError``.

    Fails if the guard is deleted: the escape path is returned as allowed.
    """
    default = tmp_path / "repo"
    default.mkdir()
    with pytest.raises(WorkspacePathError, match=r"working_directory|outside") as excinfo:
        resolve_allowed_working_directory(escape, default=str(default))
    assert "outside" in str(excinfo.value) or "working_directory" in str(excinfo.value)


def test_resolve_allowed_working_directory_rejects_symlink_escape(
    tmp_path: Path,
) -> None:
    """Direct ``resolve_allowed_working_directory`` — symlink-to-/etc is an escape."""
    default = tmp_path / "repo"
    default.mkdir()
    link = default / "looks-local"
    link.symlink_to("/etc", target_is_directory=True)
    with pytest.raises(WorkspacePathError, match=r"outside|working_directory"):
        resolve_allowed_working_directory(str(link), default=str(default))


def test_resolve_allowed_working_directory_accepts_inside_default(
    tmp_path: Path,
) -> None:
    """Direct ``resolve_allowed_working_directory`` — in-tree paths stay allowed."""
    default = tmp_path / "repo"
    nested = default / "src" / "pkg"
    nested.mkdir(parents=True)
    resolved = resolve_allowed_working_directory(str(nested), default=str(default))
    assert Path(resolved) == nested.resolve()


def test_resolve_allowed_working_directory_none_uses_default(tmp_path: Path) -> None:
    """Direct ``resolve_allowed_working_directory`` — ``None`` returns resolved default."""
    default = tmp_path / "repo"
    default.mkdir()
    resolved = resolve_allowed_working_directory(None, default=str(default))
    assert Path(resolved) == default.resolve()
