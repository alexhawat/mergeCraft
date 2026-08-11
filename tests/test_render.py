"""W9 contract: interactive git-style render + TTY helpers (Go cmd/meat/render.go)."""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest import mock

import pytest

from meat_python_plus.abridge import Result
from _parity_helpers import import_or_fail, require_attr

ANSI_ESCAPE = "\x1b["


@pytest.fixture
def render_module():
    return import_or_fail("meat_python_plus.render")


@pytest.fixture
def tty_module():
    return import_or_fail("meat_python_plus.tty")


def test_format_body_plain(render_module) -> None:
    format_body = require_attr(render_module, "format_body")
    res = Result(smart_diff="@@ -1 +1 @@\n-old\n+new\n", summary="did a thing")
    got = format_body(res, elision="", palette=render_module.diff_palette(False))
    want = "# did a thing\n\n@@ -1 +1 @@\n-old\n+new\n"
    assert got == want
    assert ANSI_ESCAPE not in got


def test_format_body_empty_diff(render_module) -> None:
    format_body = require_attr(render_module, "format_body")
    palette = require_attr(render_module, "diff_palette")
    for color in (False, True):
        got = format_body(Result(smart_diff="", summary="s"), elision="", palette=palette(color))
        assert "no meaningful change" in got


def test_palette_disabled_is_all_plain(render_module) -> None:
    diff_palette = require_attr(render_module, "diff_palette")
    colorize = require_attr(render_module, "colorize_diff_line")
    empty = diff_palette(False)
    assert empty == render_module.DiffPalette()
    for line in ("+a", "-b", "@@ x @@", "diff --git a b"):
        assert colorize(line, empty) == line


def test_colorize_diff_line_slots(render_module) -> None:
    colorize = require_attr(render_module, "colorize_diff_line")
    palette = render_module.DiffPalette(
        meta="\x1b[1m",
        frag="\x1b[36m",
        old="\x1b[31m",
        new="\x1b[32m",
    )
    reset = require_attr(render_module, "ANSI_RESET")
    cases = [
        (" context", ""),
        ("+added", palette.new),
        ("-removed", palette.old),
        ("@@ -1 +1 @@", palette.frag),
        ("diff --git a/x b/x", palette.meta),
    ]
    for line, prefix in cases:
        got = colorize(line, palette)
        assert line in got
        if not prefix:
            assert got == line
        else:
            assert got.startswith(prefix)
            assert got.endswith(reset)


def test_is_terminal_non_file(tty_module) -> None:
    is_terminal = require_attr(tty_module, "is_terminal")
    assert not is_terminal(io.StringIO())


def test_is_terminal_regular_file(tty_module, tmp_path: Path) -> None:
    is_terminal = require_attr(tty_module, "is_terminal")
    path = tmp_path / "out"
    with path.open("w", encoding="utf-8") as handle:
        assert not is_terminal(handle)


def test_render_result_to_file_is_plain(render_module, tmp_path: Path) -> None:
    render_result = require_attr(render_module, "render_result")
    path = tmp_path / "out"
    res = Result(smart_diff="@@ x @@\n+a\n-b\n", summary="s")
    with path.open("w", encoding="utf-8") as handle:
        render_result(handle, res, elision="kept 2/9 changed lines", color=False, use_pager=False)
    got = path.read_text(encoding="utf-8")
    assert ANSI_ESCAPE not in got
    assert "+a" in got and "# s" in got
    assert "# kept 2/9 changed lines" in got


def test_render_invokes_pager_when_tty(render_module, tty_module) -> None:
    render_result = require_attr(render_module, "render_result")
    run_pager = require_attr(render_module, "run_pager")
    res = Result(smart_diff="+a\n", summary="s")
    stdout = io.StringIO()

    with mock.patch.object(tty_module, "is_terminal", return_value=True):
        with mock.patch.object(render_module, "run_pager", wraps=run_pager) as pager:
            render_result(stdout, res, elision="", color=True, use_pager=True, pager_command="cat")
            pager.assert_called_once()


def test_render_json_wire(render_module) -> None:
    render_json = require_attr(render_module, "render_json")
    buf = io.StringIO()
    res = Result(
        smart_diff="@@ x @@\n+a\n",
        summary="did thing",
        input_tokens=10,
        output_tokens=2,
    )
    render_json(buf, res, elision="kept 1/5 changed lines")
    payload = json.loads(buf.getvalue())
    assert payload == {
        "smart_diff": "@@ x @@\n+a\n",
        "summary": "did thing",
        "input_tokens": 10,
        "output_tokens": 2,
        "elision": "kept 1/5 changed lines",
    }
    assert ANSI_ESCAPE not in buf.getvalue()
    assert "\\u003c" not in buf.getvalue()
