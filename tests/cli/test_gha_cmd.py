"""Tests for the ``mergecraft gha`` helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import typer

from mergecraft.cli.gha_cmd import _set_failed, _set_output

if TYPE_CHECKING:
    from pathlib import Path


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


def test_set_failed_writes_one_escaped_error_line_to_stdout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """CF-D14 — the workflow command is escaped and written to stdout directly.

    Rich would still interpret ``[...]`` as markup, soft-wrap long lines and
    (via ``err_console``) target stderr. A message carrying ``%``, CR, LF or a
    nested workflow command must produce exactly one escaped ``::error::``
    line on stdout with the brackets intact.
    """
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    message = "boom 100%\r\n::add-mask::x [bold]"
    with pytest.raises(typer.Exit):
        _set_failed(message)

    captured = capsys.readouterr()
    lines = [line for line in captured.out.splitlines() if line.startswith("::error::")]
    assert len(lines) == 1, f"expected exactly one ::error:: line, got:\n{captured.out!r}"
    assert captured.out.count("::error::") == 1, captured.out
    assert "%25" in lines[0], lines[0]
    assert "%0D" in lines[0], lines[0]
    assert "%0A" in lines[0], lines[0]
    assert "[bold]" in lines[0], f"Rich markup was interpreted: {lines[0]!r}"
