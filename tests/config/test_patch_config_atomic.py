"""F38 — the comment-preserving config patch is an atomic replace, like the full rewrite."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from mergecraft.config import io as config_io

_COMMENTED = """\
# fork floor always refuses
trust:
  selfReview: 'off'
model: anthropic/claude-sonnet
"""


def _config(tmp_path: Path) -> Path:
    path = tmp_path / ".mergecraft" / "config.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(_COMMENTED, encoding="utf-8")
    return path


def test_comment_preserving_patch_goes_through_an_atomic_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _config(tmp_path)
    replaced: list[tuple[str, str]] = []
    real_replace = os.replace

    def _recording_replace(src: Path, dst: Path) -> None:
        replaced.append((str(src), str(dst)))
        real_replace(src, dst)

    def _no_in_place_write(self: Path, *_args: object, **_kwargs: object) -> int:
        raise AssertionError("the patch must not truncate-and-write the live file")

    monkeypatch.setattr(config_io.os, "replace", _recording_replace)
    monkeypatch.setattr(Path, "write_text", _no_in_place_write)

    config_io.patch_config_dict(path, {"model": "openai/gpt-5"})

    assert [dst for _src, dst in replaced] == [str(path)]
    text = path.read_text(encoding="utf-8")
    assert "model: openai/gpt-5" in text
    assert "# fork floor always refuses" in text
    assert "anthropic/claude-sonnet" not in text


def test_failed_comment_preserving_patch_leaves_the_original_and_no_temp_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _config(tmp_path)

    def _boom(src: object, dst: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(config_io.os, "replace", _boom)

    with pytest.raises(OSError, match="disk full"):
        config_io.patch_config_dict(path, {"model": "openai/gpt-5"})

    assert path.read_text(encoding="utf-8") == _COMMENTED
    leftovers = [c.name for c in path.parent.iterdir() if c.name != path.name]
    assert leftovers == [], f"temp files must be removed on failure: {leftovers}"


def test_comment_preserving_patch_keeps_the_file_mode(tmp_path: Path) -> None:
    path = _config(tmp_path)
    path.chmod(0o640)

    config_io.patch_config_dict(path, {"model": "openai/gpt-5"})

    assert path.stat().st_mode & 0o777 == 0o640
