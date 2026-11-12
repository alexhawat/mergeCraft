"""An unknown id is one exit code everywhere: 2, a usage error (#1343)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_USAGE_EXIT_CODE

_ENV = {"NO_COLOR": "1", "TERM": "dumb"}

_UNKNOWN_IDS = [
    ("agent", "show", "nobody"),
    ("agent-local", "show", "nobody"),
    ("lens", "show", "nolens"),
    ("analyzers", "explain", "nope"),
    ("memory", "show", "nope"),
    ("eval", "replay", "nocase"),
    ("evidence", "show", "nope"),
    ("requirements", "explain", "nope"),
]


@pytest.mark.parametrize("argv", _UNKNOWN_IDS, ids=[" ".join(a) for a in _UNKNOWN_IDS])
def test_unknown_id_exits_with_the_usage_code(
    argv: tuple[str, ...], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every ``show``/``explain``-style lookup of a missing id exits 2."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MERGECRAFT_CONFIG", raising=False)

    result = CliRunner().invoke(app, list(argv), env=_ENV)

    assert result.exit_code == CLI_USAGE_EXIT_CODE, result.output
