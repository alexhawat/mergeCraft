"""Tests for the ``mergecraft gha`` helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.cli.gha_cmd import _set_output

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_set_output_single_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    _set_output("result", "ok")
    assert out.read_text(encoding="utf-8") == "result=ok\n"


def test_set_output_multiline_uses_heredoc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    value = "line one\nline two"
    _set_output("result", value)
    written = out.read_text(encoding="utf-8")
    # name<<DELIM \n value \n DELIM \n — never a bare `result=` with a raw newline.
    assert written.startswith("result<<ghadelimiter_")
    assert f"\n{value}\n" in written
    lines = written.splitlines()
    assert lines[0] == f"result<<{lines[-1]}"  # opening delimiter matches closing
    assert not written.startswith("result=")
