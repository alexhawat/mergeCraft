"""``resolve_cwd`` confines the ``cwd`` input to ``GITHUB_WORKSPACE`` (#1259)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mergecraft.utils.payload import resolve_cwd

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "workspace"
    (root / "sub").mkdir(parents=True)
    monkeypatch.setenv("GITHUB_WORKSPACE", str(root))
    return root


def test_unset_cwd_defaults_to_workspace(workspace: Path) -> None:
    assert resolve_cwd(None) == str(workspace)
    assert resolve_cwd("") == str(workspace)


def test_relative_cwd_inside_workspace_is_joined(workspace: Path) -> None:
    assert resolve_cwd("sub") == str(workspace / "sub")
    assert resolve_cwd("sub/../sub") == str(workspace / "sub/../sub")


def test_absolute_cwd_inside_workspace_is_allowed(workspace: Path) -> None:
    assert resolve_cwd(str(workspace / "sub")) == str(workspace / "sub")


@pytest.mark.parametrize("cwd", ["..", "../..", "sub/../../elsewhere", "../workspace-evil"])
def test_relative_escape_is_a_config_error(workspace: Path, cwd: str) -> None:
    with pytest.raises(ValueError, match="outside GITHUB_WORKSPACE"):
        resolve_cwd(cwd)


def test_absolute_path_outside_workspace_is_a_config_error(workspace: Path) -> None:
    with pytest.raises(ValueError, match="outside GITHUB_WORKSPACE"):
        resolve_cwd("/etc")


def test_symlink_escaping_workspace_is_a_config_error(workspace: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace / "link").symlink_to(outside)
    with pytest.raises(ValueError, match="outside GITHUB_WORKSPACE"):
        resolve_cwd("link")


def test_without_workspace_values_pass_through(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
    assert resolve_cwd(None) is None
    assert resolve_cwd("../x") == "../x"
    assert resolve_cwd("/abs/path") == "/abs/path"
