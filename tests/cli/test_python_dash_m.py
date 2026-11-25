"""``python -m mergecraft`` runs the CLI like the console script does (#1570).

The console script is ``mergecraft.cli.entrypoint:main``; the package had no
``__main__`` module, so ``python -m mergecraft --version`` died with
``No module named mergecraft.__main__`` even though ``mergecraft --version``
worked. Any runbook that reaches for ``sys.executable -m mergecraft`` (a
virtualenv without the script on ``PATH``, a container with a bare
interpreter) was broken.

Both tests drive the real CLI in a child process, so they observe the exit
code and the text an operator sees. The expected version line is read from
``mergecraft --version`` on the same interpreter, so a release bump cannot make
this module wrong.
"""

from __future__ import annotations

import os
import runpy
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from mergecraft.cli.app import app

if TYPE_CHECKING:
    import pytest

# A child process with a minimal environment: nothing in the parent's
# ``MERGECRAFT_*`` / provider / proxy variables may change what ``--version``
# prints, and no network is needed.
_CHILD_ENV = {"PATH": os.defpath}


def _python_dash_m(argv: list[str], tmp_path: Path) -> subprocess.CompletedProcess[str]:
    """Run ``python -m mergecraft <argv>`` in a scratch directory."""
    return subprocess.run(
        [sys.executable, "-m", "mergecraft", *argv],
        cwd=tmp_path,
        env={**_CHILD_ENV, "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def _app_version_line() -> str:
    """Return the line the CLI's ``--version`` prints, through the Typer app."""
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0, f"`mergecraft --version` failed:\n{result.output}"
    return result.output.strip()


def test_python_dash_m_prints_the_version(tmp_path: Path) -> None:
    """``python -m mergecraft --version`` exits 0 and prints the console script's line."""
    expected = _app_version_line()
    result = _python_dash_m(["--version"], tmp_path)
    assert result.returncode == 0, (
        f"python -m mergecraft --version exited {result.returncode}; stderr:\n{result.stderr}"
    )
    assert result.stdout.strip() == expected, (
        f"python -m mergecraft --version printed {result.stdout.strip()!r} but "
        f"`mergecraft --version` prints {expected!r}"
    )


def test_python_dash_m_help_matches_the_console_script(tmp_path: Path) -> None:
    """``python -m mergecraft --help`` exits 0 and its usage line names mergecraft."""
    result = _python_dash_m(["--help"], tmp_path)
    assert result.returncode == 0, (
        f"python -m mergecraft --help exited {result.returncode}; stderr:\n{result.stderr}"
    )
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    usage = next((line for line in lines if line.lower().startswith("usage:")), None)
    assert usage is not None, f"no usage line in `python -m mergecraft --help`:\n{result.stdout}"
    assert "mergecraft" in usage.lower(), (
        f"the usage line {usage!r} does not name mergecraft; the module entry point "
        "must run the same CLI as the console script"
    )


def test_package_guard_runs_the_cli_in_process(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The package ``__main__`` guard runs the CLI and prints its version line.

    The child-process tests above prove the operator-visible behaviour but run
    outside coverage's reach; this one drives the same guard in-process so the
    module's own lines are exercised.
    """
    expected = _app_version_line()
    monkeypatch.setattr(sys, "argv", ["mergecraft", "--version"])
    runpy.run_module("mergecraft", run_name="__main__")
    assert capsys.readouterr().out.strip() == expected
