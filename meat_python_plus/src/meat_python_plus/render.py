"""Interactive git-style render matching Go meat ``cmd/meat/render.go``.

On a TTY: color via ``git config --get-color color.diff.*`` and page through
``$GIT_PAGER`` / ``core.pager`` (``git var GIT_PAGER``). Piped/redirected
output and ``-json`` stay plain.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import TextIO

from meat_python_plus import tty
from meat_python_plus.abridge import Result

ANSI_RESET = "\x1b[m"

_DIFF_META_PREFIXES = (
    "diff ",
    "index ",
    "old mode ",
    "new mode ",
    "new file mode ",
    "deleted file mode ",
    "similarity index ",
    "dissimilarity index ",
    "rename from ",
    "rename to ",
    "copy from ",
    "copy to ",
)


@dataclass(frozen=True)
class DiffPalette:
    """ANSI escapes for each unified-diff line kind (empty = plain)."""

    meta: str = ""
    frag: str = ""
    old: str = ""
    new: str = ""


def diff_palette(color: bool) -> DiffPalette:
    """Resolve ``color.diff.*`` via git, or return the empty palette when off."""
    if not color:
        return DiffPalette()
    return DiffPalette(
        meta=_diff_color("meta", "bold"),
        frag=_diff_color("frag", "cyan"),
        old=_diff_color("old", "red"),
        new=_diff_color("new", "green"),
    )


def format_body(
    res: Result,
    elision: str = "",
    palette: DiffPalette | None = None,
) -> str:
    """Render summary + elision manifest + diff using *palette*."""
    p = DiffPalette() if palette is None else palette
    parts: list[str] = []
    if res.summary:
        commit = _commit_color(p)
        if commit:
            parts.append(f"{commit}# {res.summary}{ANSI_RESET}\n")
        else:
            parts.append(f"# {res.summary}\n")
    if elision:
        parts.append(f"# {elision}\n")
    body = "".join(parts)
    if body:
        body += "\n"
    diff = res.smart_diff.rstrip("\n")
    if not diff.strip():
        return body + "(no meaningful change to read)\n"
    lines: list[str] = []
    for line in diff.split("\n"):
        lines.append(colorize_diff_line(line, p))
        lines.append("\n")
    return body + "".join(lines)


def colorize_diff_line(line: str, palette: DiffPalette) -> str:
    """Wrap a unified-diff line in the palette color for its kind."""
    if _is_diff_meta(line):
        c = palette.meta
    elif line.startswith("@@"):
        c = palette.frag
    elif line.startswith("+"):
        c = palette.new
    elif line.startswith("-"):
        c = palette.old
    else:
        return line
    if not c:
        return line
    return f"{c}{line}{ANSI_RESET}"


def render_json(w: TextIO, res: Result, elision: str = "") -> None:
    """Write one JSON object (D11 wire); no color, no pager."""
    payload = res.to_dict()
    if elision:
        payload["elision"] = elision
    json.dump(payload, w, ensure_ascii=False)
    w.write("\n")


def render_result(
    w: TextIO,
    res: Result,
    elision: str = "",
    *,
    color: bool | None = None,
    use_pager: bool | None = None,
    pager_command: str | None = None,
) -> None:
    """Write summary + diff; color/pager when interactive (or overridden)."""
    is_tty = tty.is_terminal(w)
    if color is None:
        color = bool(is_tty and git_wants_color(is_tty))
    body = format_body(res, elision, diff_palette(color))
    if use_pager is None:
        use_pager = is_tty
    if not use_pager:
        w.write(body)
        return
    try:
        run_pager(body, pager_command=pager_command, outfile=w)
    except OSError:
        w.write(body)


def run_pager(
    text: str,
    *,
    pager_command: str | None = None,
    outfile: TextIO | None = None,
) -> None:
    """Send *text* through git's pager (or write plain when pager is ``cat``)."""
    pager = pager_command if pager_command is not None else _git_pager()
    out = outfile if outfile is not None else sys.stdout
    if not pager or pager == "cat":
        out.write(text)
        return
    env = os.environ.copy()
    if "LESS" not in env:
        env["LESS"] = "FRX"
    proc = subprocess.Popen(
        ["sh", "-c", pager],
        stdin=subprocess.PIPE,
        stdout=sys.stdout,
        stderr=sys.stderr,
        env=env,
        text=True,
    )
    assert proc.stdin is not None
    try:
        proc.stdin.write(text)
        proc.stdin.close()
    except BrokenPipeError:
        pass
    proc.wait()


def git_wants_color(is_tty: bool) -> bool:
    """Honor ``color.ui`` / ``color.diff`` via ``git config --get-colorbool``."""
    arg = "true" if is_tty else "false"
    try:
        proc = subprocess.run(
            ["git", "config", "--get-colorbool", "color.diff", arg],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    if proc.returncode != 0:
        return False
    return proc.stdout.strip() == "true"


def _commit_color(palette: DiffPalette) -> str:
    if palette == DiffPalette():
        return ""
    return _diff_color("commit", "yellow")


def _diff_color(slot: str, default: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "config", "--get-color", f"color.diff.{slot}", default],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout


def _git_pager() -> str:
    try:
        proc = subprocess.run(
            ["git", "var", "GIT_PAGER"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _is_diff_meta(line: str) -> bool:
    if line.startswith("+++") or line.startswith("---"):
        return True
    return any(line.startswith(p) for p in _DIFF_META_PREFIXES)
