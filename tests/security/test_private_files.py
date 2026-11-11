"""``write_private_file`` creates owner-only files from the first byte."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from mergecraft.security import private_files
from mergecraft.security.private_files import PRIVATE_FILE_MODE, write_private_file

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _spy_creations(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int, int]]:
    """Record every ``os.open`` the helper makes: (path, flags, mode)."""
    calls: list[tuple[str, int, int]] = []
    real_open = os.open

    def _open(path: str | os.PathLike[str], flags: int, mode: int = 0o777, **kw: object) -> int:
        calls.append((os.fspath(path), flags, mode))
        return real_open(path, flags, mode, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(private_files.os, "open", _open)
    return calls


def test_file_is_created_owner_only_even_under_a_permissive_umask(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _spy_creations(monkeypatch)
    target = tmp_path / "creds.json"
    old_umask = os.umask(0)
    try:
        write_private_file(target, '{"k": "v"}')
    finally:
        os.umask(old_umask)

    assert target.read_text(encoding="utf-8") == '{"k": "v"}'
    assert _mode(target) == PRIVATE_FILE_MODE
    [(created, flags, mode)] = calls
    assert mode == PRIVATE_FILE_MODE
    assert flags & os.O_CREAT
    assert flags & os.O_EXCL
    assert Path(created).parent == tmp_path


def test_an_existing_wider_file_is_replaced_not_written_through(tmp_path: Path) -> None:
    target = tmp_path / "creds.json"
    target.write_text("old", encoding="utf-8")
    target.chmod(0o644)
    before = target.stat().st_ino

    write_private_file(target, "new")

    assert target.read_text(encoding="utf-8") == "new"
    assert _mode(target) == PRIVATE_FILE_MODE
    assert target.stat().st_ino != before


def test_a_link_at_the_destination_is_replaced_and_its_target_left_alone(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere.txt"
    elsewhere.write_text("unchanged", encoding="utf-8")
    target = tmp_path / "creds.json"
    target.symlink_to(elsewhere)

    write_private_file(target, "new")

    assert not target.is_symlink()
    assert target.read_text(encoding="utf-8") == "new"
    assert elsewhere.read_text(encoding="utf-8") == "unchanged"


def test_no_sibling_is_left_behind_when_the_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fail(*_a: object) -> None:
        raise OSError("rename refused")

    monkeypatch.setattr(private_files.os, "replace", _fail)

    with pytest.raises(OSError, match="rename refused"):
        write_private_file(tmp_path / "creds.json", "x")

    assert list(tmp_path.iterdir()) == []
