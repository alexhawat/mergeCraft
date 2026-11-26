"""Jev hunk units from real ``git diff`` output (#1589, #1590).

Every patch here comes from the real ``git`` binary in a throwaway repository.

- #1589: a removed ``-- x`` renders as ``--- x`` and an added ``++ x`` as
  ``+++ x``. Inside a hunk those are content: they must neither rename the unit
  nor drop out of its body, its id or its cache key.
- #1590: with ``core.quotePath=true`` Git writes ``café.md`` as
  ``"b/caf\\303\\251.md"``. The unit must carry the path the shared diff parser
  decodes, so analyzer findings on that file overlap it.
"""

from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING

from mergecraft.diff import parse_diff
from mergecraft.jev.segment import residual_units, segment_hunks, unit_cache_key, unit_id
from tests.jev.support import PINNED_MODEL

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.jev.types import HunkUnit

_GIT = [
    "git",
    "-c",
    "user.name=t",
    "-c",
    "user.email=t@example.com",
    "-c",
    "commit.gpgsign=false",
    "-c",
    "core.quotePath=true",
]
_GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}

#: Base text whose edits render as header-shaped hunk lines.
_SQL_BASE = "select 1;\n-- a/old.sql\nselect 2;\n-- old comment\n"
#: ``-- a/old.sql`` -> ``--- a/old.sql``; ``++ b/evil.py`` -> ``+++ b/evil.py``.
_SQL_HEAD = "select 1;\n++ b/evil.py\nselect 2;\n++ b/m.sql\n"
_SQL_CHANGED = ["--- a/old.sql", "+++ b/evil.py", "--- old comment", "+++ b/m.sql"]


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        [*_GIT, "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_GIT_ENV,
    )
    return result.stdout


def _patch(repo: Path, base: dict[str, str], head: dict[str, str]) -> str:
    """Commit ``base`` then ``head`` in a fresh repository and diff the two."""
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    for rel, text in base.items():
        (repo / rel).write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base", "--allow-empty")
    for rel, text in head.items():
        (repo / rel).write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "head")
    return _git(repo, "diff", "HEAD~1", "HEAD")


def _changed(unit: HunkUnit) -> list[str]:
    """The unit's added and removed lines, in order."""
    return [line for line in unit.content.split("\n")[1:] if line[:1] in {"+", "-"}]


def test_header_shaped_edits_stay_in_the_unit(tmp_path: Path) -> None:
    diff = _patch(tmp_path / "repo", {"m.sql": _SQL_BASE}, {"m.sql": _SQL_HEAD})
    assert "\n+++ b/evil.py\n" in diff
    assert diff.endswith("\n+++ b/m.sql\n")

    (unit,) = segment_hunks(diff)

    assert unit.path == "m.sql"
    assert _changed(unit) == _SQL_CHANGED
    assert (unit.start_line, unit.end_line) == (1, 4)


def test_changing_a_header_shaped_edit_changes_identity_and_cache_key(tmp_path: Path) -> None:
    edited = _SQL_HEAD.replace("++ b/evil.py", "++ b/other.py")
    (original,) = segment_hunks(
        _patch(tmp_path / "one", {"m.sql": _SQL_BASE}, {"m.sql": _SQL_HEAD})
    )
    (changed,) = segment_hunks(_patch(tmp_path / "two", {"m.sql": _SQL_BASE}, {"m.sql": edited}))

    assert changed.path == original.path == "m.sql"
    assert "+++ b/other.py" in _changed(changed)
    assert unit_id(changed) != unit_id(original)
    assert unit_cache_key(changed, pack_id="unit/v1", model=PINNED_MODEL) != unit_cache_key(
        original, pack_id="unit/v1", model=PINNED_MODEL
    )


def test_a_following_file_keeps_its_own_path_and_body(tmp_path: Path) -> None:
    diff = _patch(
        tmp_path / "repo",
        {"m.sql": _SQL_BASE, "z.txt": "one\ntwo\n"},
        {"m.sql": _SQL_HEAD, "z.txt": "one\nthree\n"},
    )

    first, second = segment_hunks(diff)

    assert first.path == "m.sql"
    assert _changed(first) == _SQL_CHANGED
    assert second.path == "z.txt"
    assert _changed(second) == ["-two", "+three"]
    assert (second.start_line, second.end_line) == (1, 2)


def test_quoted_non_ascii_path_matches_the_shared_parser(tmp_path: Path) -> None:
    diff = _patch(tmp_path / "repo", {}, {"café.md": "# café\n"})
    assert '"b/caf\\303\\251.md"' in diff

    (unit,) = segment_hunks(diff)

    assert [unit.path] == [section.path for section in parse_diff(diff).files] == ["café.md"]
    assert residual_units([unit], [{"path": "café.md", "start_line": 1}]) == []
    assert residual_units([unit], [{"path": "other.md", "start_line": 1}]) == [unit]


def test_ascii_path_matches_the_shared_parser(tmp_path: Path) -> None:
    diff = _patch(tmp_path / "repo", {"plain.md": "a\n"}, {"plain.md": "b\n"})

    (unit,) = segment_hunks(diff)

    assert [unit.path] == [section.path for section in parse_diff(diff).files] == ["plain.md"]
    assert residual_units([unit], [{"path": "plain.md", "start_line": 1}]) == []


def test_multi_file_patch_paths_match_the_shared_parser(tmp_path: Path) -> None:
    diff = _patch(
        tmp_path / "repo",
        {"plain.md": "a\n"},
        {"café.md": "# café\n", "plain.md": "b\n"},
    )

    units = segment_hunks(diff)

    assert [unit.path for unit in units] == [section.path for section in parse_diff(diff).files]
    assert sorted(unit.path for unit in units) == ["café.md", "plain.md"]
    residual = residual_units(units, [{"path": "café.md", "start_line": 1}])
    assert [unit.path for unit in residual] == ["plain.md"]
