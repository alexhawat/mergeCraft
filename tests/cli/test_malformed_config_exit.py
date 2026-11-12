"""A malformed ``.mergecraft/config.yaml`` exits through the configuration code.

Every read command that loads repo config must print one error line and exit
30 (``configuration_error``), never a traceback with exit 1 (#1337).
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_CONFIGURATION_EXIT_CODE

if TYPE_CHECKING:
    from pathlib import Path

_COMMANDS = [
    ["trust", "show"],
    ["plan"],
    ["agent", "list"],
    ["agents", "list"],
    ["provider", "list"],
    ["provider", "status"],
    ["model", "list"],
    ["models", "show"],
    ["jev", "status"],
    ["describe"],
    ["analyzers", "list"],
    ["config", "tracing"],
]


def _malformed_repo(tmp_path: Path) -> Path:
    """Create a git repo whose committed config cannot be parsed."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".mergecraft").mkdir()
    (tmp_path / ".mergecraft" / "config.yaml").write_text(
        "shell: disabled\nrunBounds: [\n", encoding="utf-8"
    )
    return tmp_path


@pytest.mark.parametrize("argv", _COMMANDS, ids=["-".join(a) for a in _COMMANDS])
def test_malformed_config_exits_with_configuration_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, argv: list[str]
) -> None:
    """The command prints a one-line parse error and exits 30, no traceback."""
    root = _malformed_repo(tmp_path)
    monkeypatch.chdir(root)
    monkeypatch.delenv("MERGECRAFT_CONFIG", raising=False)

    result = CliRunner().invoke(app, argv, env={"NO_COLOR": "1", "TERM": "dumb"})

    output = result.stdout + result.stderr
    assert result.exit_code == CLI_CONFIGURATION_EXIT_CODE, (result.exception, output)
    assert "Traceback" not in output
    assert "config parse error" in output
    assert "config.yaml" in output


@pytest.mark.parametrize("argv", [["agents", "list"], ["plan"]], ids=["agents-list", "plan"])
def test_missing_mergecraft_config_file_is_a_configuration_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, argv: list[str]
) -> None:
    """A ``MERGECRAFT_CONFIG`` naming a missing file never falls back to the committed one."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".mergecraft").mkdir()
    (tmp_path / ".mergecraft" / "config.yaml").write_text("shell: disabled\n", encoding="utf-8")
    missing = tmp_path / "typo.yaml"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MERGECRAFT_CONFIG", str(missing))

    result = CliRunner().invoke(app, argv, env={"NO_COLOR": "1", "TERM": "dumb"})

    output = result.stdout + result.stderr
    assert result.exit_code == CLI_CONFIGURATION_EXIT_CODE, (result.exception, output)
    assert "typo.yaml" in output
    assert "Traceback" not in output
