"""Terminal help is free of RST markup, planning ids and foreign product names (#1344).

The snapshot renders ``--help`` for every group and command in the tree, so a
help string added later is covered too.
"""

from __future__ import annotations

import re

import click
import pytest
import typer
from typer.testing import CliRunner

from mergecraft.cli.app import app

_ENV = {"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "200"}

# Planning ids: decision / wave / ticket references such as D14, W8.4, EV-D11,
# TS1, RC6, B3, CF #473 or a bare issue number.
_PLANNING_ID = re.compile(
    r"\b(?:D\d{1,2}[a-z]?|W\d+(?:\.\d+)*|EV-?D?\d+|TS\d+|RC\d+|B\d+|CF)\b|#\d{2,}"
)


def _paths() -> list[tuple[str, ...]]:
    def walk(command: click.Command, path: tuple[str, ...]) -> list[tuple[str, ...]]:
        found = [path]
        if isinstance(command, click.Group):
            for name, sub in sorted(command.commands.items()):
                found.extend(walk(sub, (*path, name)))
        return found

    return walk(typer.main.get_command(app), ())


_PATHS = _paths()


@pytest.mark.parametrize("path", _PATHS, ids=[" ".join(p) or "mergecraft" for p in _PATHS])
def test_help_has_no_rst_planning_ids_or_foreign_names(path: tuple[str, ...]) -> None:
    """Every ``--help`` page reads as user documentation."""
    result = CliRunner().invoke(app, [*path, "--help"], env=_ENV)

    assert result.exit_code == 0, result.output
    text = result.stdout
    assert "``" not in text
    assert _PLANNING_ID.findall(text) == []
    assert "sevn" not in text.lower()


def test_unknown_command_suggests_once() -> None:
    """A mistyped command prints one suggestion, not the same one twice."""
    result = CliRunner().invoke(app, ["helth"], env=_ENV)

    assert result.exit_code == 2
    assert result.output.count("Did you mean") == 1
