"""An explicit ``--bank`` that does not exist is an error, not an empty pass (#1343)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_CONFIGURATION_EXIT_CODE

_ENV = {"NO_COLOR": "1", "TERM": "dumb"}
_READERS = [("gate",), ("list",), ("replay-bank",)]


@pytest.mark.parametrize("command", _READERS, ids=[c[0] for c in _READERS])
def test_missing_explicit_bank_exits_30(command: tuple[str, ...], tmp_path: Path) -> None:
    """A typo in ``--bank`` cannot turn the gate green."""
    missing = tmp_path / "no-such-bank"

    result = CliRunner().invoke(app, ["eval", *command, "--bank", str(missing), "--json"], env=_ENV)

    assert result.exit_code == CLI_CONFIGURATION_EXIT_CODE, result.output
    assert "no-such-bank" in result.stderr


def test_existing_empty_explicit_bank_still_passes(tmp_path: Path) -> None:
    """An explicit bank that exists but is empty keeps the lenient pass."""
    result = CliRunner().invoke(app, ["eval", "gate", "--bank", str(tmp_path), "--json"], env=_ENV)

    assert result.exit_code == 0, result.output
