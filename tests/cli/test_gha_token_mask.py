"""``_set_output(mask=True)`` masks through the raw workflow-command helper (#1558).

The GitHub Actions runner parses workflow commands on stdout and stderr alike,
so the mask took effect before — but it was the one command rendered by Rich.
This pins the fixed shape: one unescaped-by-Rich line on **stdout**, the same
string written to ``$GITHUB_OUTPUT``, and no dependence on ``COLUMNS`` or
``FORCE_COLOR``.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from mergecraft.cli.gha_cmd import _set_output

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def test_mask_line_is_raw_on_stdout_and_matches_the_output_file(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    """Bug: the mask is one raw stdout line and the output file carries the value."""
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))

    _set_output("token", "tok[bold]en", mask=True)

    captured = capsys.readouterr()
    mask_lines = [line for line in captured.out.splitlines() if line.startswith("::add-mask::")]
    assert mask_lines == ["::add-mask::tok[bold]en"], captured.out
    assert "::add-mask::" not in captured.err
    assert out.read_text(encoding="utf-8") == "token=tok[bold]en\n"


def test_mask_line_ignores_terminal_width_and_colour(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    """Bug: a long value masks as one unbroken line with no escape sequence."""
    out = tmp_path / "out"
    value = "ghs_" + "a" * 56
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("COLUMNS", "20")
    monkeypatch.setenv("FORCE_COLOR", "1")

    _set_output("token", value, mask=True)

    captured = capsys.readouterr()
    mask_lines = [line for line in captured.out.splitlines() if line.startswith("::add-mask::")]
    assert mask_lines == [f"::add-mask::{value}"], captured.out
    assert _ANSI.search(captured.out) is None, captured.out
