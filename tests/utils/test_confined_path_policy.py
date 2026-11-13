"""Real filesystem policies share containment without losing caller semantics."""

from __future__ import annotations

from pathlib import Path

import pytest

from mergecraft.utils.bounded_text import resolve_path_under_root
from mergecraft.utils.path_confinement import resolve_confined_path


@pytest.mark.parametrize("directory_link", [False, True], ids=["file-link", "parent-link"])
def test_linked_repository_path_refuses_internal_symlinks(
    tmp_path: Path, directory_link: bool
) -> None:
    directory = tmp_path / "source"
    directory.mkdir()
    (directory / "file.py").write_text("pass\n")
    link = tmp_path / "link"
    link.symlink_to(directory if directory_link else directory / "file.py")
    operand = "link/file.py" if directory_link else "link"
    with pytest.raises(FileNotFoundError, match="symlink"):
        resolve_path_under_root(tmp_path, operand)


def test_linked_repository_resolver_preserves_missing_absolute_and_directory_paths(
    tmp_path: Path,
) -> None:
    assert resolve_path_under_root(tmp_path, "missing") == tmp_path / "missing"
    assert resolve_path_under_root(tmp_path, str(tmp_path)) == tmp_path


def test_verifier_citations_allow_internal_links_but_require_existing_files(tmp_path: Path) -> None:
    source = tmp_path / "file.py"
    source.write_text("pass\n")
    (tmp_path / "link.py").symlink_to(source)
    assert resolve_confined_path(tmp_path, "link.py") == str(source)
    with pytest.raises(ValueError, match="not a file"):
        resolve_confined_path(tmp_path, "missing")


def test_agent_security_scan_with_relative_root_refuses_external_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.analyzers.agentsec.confinement import confined_changed_file

    monkeypatch.chdir(tmp_path)
    root = Path("repo")
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("external instructions")
    (root / "AGENTS.md").symlink_to(outside)
    assert confined_changed_file(root, "AGENTS.md") is None
