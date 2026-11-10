"""The askpass helper emits the exact token without shell interpretation (#1260)."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from mergecraft.utils.git_setup import write_askpass_script

if TYPE_CHECKING:
    from pathlib import Path

_NASTY = [
    "ghs_plain",
    "a\"b$c`d\\e'f",
    "$(touch PWNED)",
    "`touch PWNED`",
    "'; touch PWNED; echo '",
    '"; touch PWNED; echo "',
    "tok\\nen",
    "%s %d \\n",
    "-n",
    "é-unicode-tök",
]


def _run(script: str, prompt: str, cwd: Path) -> str:
    done = subprocess.run(
        ["sh", script, prompt], capture_output=True, text=True, check=True, cwd=cwd
    )
    return done.stdout


@pytest.mark.parametrize("token", _NASTY)
def test_script_prints_exact_token_and_executes_nothing(tmp_path: Path, token: str) -> None:
    work = tmp_path / "work"
    work.mkdir()
    (tmp_path / "tmp").mkdir()
    script = write_askpass_script(str(tmp_path / "tmp"), token)

    assert _run(script, "Password for 'https://x-access-token@github.com': ", work) == token + "\n"
    assert _run(script, "Username for 'https://github.com': ", work) == "x-access-token\n"
    assert not (work / "PWNED").exists()
    assert list(work.iterdir()) == []


@pytest.mark.parametrize("token", ["abc\ndef", "abc\rdef", "a\x00b", "a\x1bb", "abc\x7f"])
def test_control_characters_are_rejected_without_echoing_the_token(
    tmp_path: Path, token: str
) -> None:
    with pytest.raises(ValueError, match="control characters") as excinfo:
        write_askpass_script(str(tmp_path), token)
    assert token not in str(excinfo.value)
    assert not (tmp_path / "credentials").exists()
