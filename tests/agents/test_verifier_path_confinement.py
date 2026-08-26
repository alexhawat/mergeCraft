"""RED — verifier citation path confinement (AG2 / MCB-20)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest


def _resolve(repo_root: str, untrusted: str, *, changed_paths: frozenset[str] | None = None) -> str:
    from mergecraft.utils.path_confinement import resolve_confined_path

    if changed_paths is not None:
        return resolve_confined_path(repo_root, untrusted, changed_paths=changed_paths)
    return resolve_confined_path(repo_root, untrusted)


if TYPE_CHECKING:
    from pathlib import Path


def test_absolute_path_is_rejected(tmp_path: Path) -> None:
    with pytest.raises((ValueError, ModuleNotFoundError), match=r".+"):
        _resolve(str(tmp_path), "/etc/passwd")


def test_traversal_and_nested_traversal_are_rejected(tmp_path: Path) -> None:
    with pytest.raises((ValueError, ModuleNotFoundError), match=r".+"):
        _resolve(str(tmp_path), "../outside")
    with pytest.raises((ValueError, ModuleNotFoundError), match=r".+"):
        _resolve(str(tmp_path), "src/../../outside")


def test_root_prefix_collision_is_rejected(tmp_path: Path) -> None:
    sibling = tmp_path.parent / f"{tmp_path.name}2"
    sibling.mkdir(exist_ok=True)
    with pytest.raises((ValueError, ModuleNotFoundError), match=r".+"):
        _resolve(str(tmp_path), f"../{sibling.name}/secret")


def test_symlink_to_outside_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-target"
    outside.mkdir(exist_ok=True)
    target = outside / "leak.txt"
    target.write_text("x", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises((ValueError, ModuleNotFoundError), match=r".+"):
        _resolve(str(tmp_path), "link")


def test_citation_must_be_in_the_changed_path_set(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    untouched = src / "unchanged.py"
    untouched.write_text("x = 1\n", encoding="utf-8")
    changed_only = frozenset({"src/changed.py"})
    with pytest.raises((ValueError, ModuleNotFoundError), match=r".+"):
        _resolve(str(tmp_path), "src/unchanged.py", changed_paths=changed_only)
