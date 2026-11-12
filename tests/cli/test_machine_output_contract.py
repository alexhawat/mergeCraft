"""Every command honours or rejects the root ``--format json`` (#1343).

The contract walks the whole command tree, so a command added later is
covered without editing this file.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import click
import pytest
import typer
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_USAGE_EXIT_CODE
from mergecraft.cli.machine_output import ROOT_FORMAT_COMMANDS, json_capability

_ENV = {"NO_COLOR": "1", "TERM": "dumb"}


def _leaves() -> list[tuple[tuple[str, ...], click.Command]]:
    def walk(
        command: click.Command, path: tuple[str, ...]
    ) -> list[tuple[tuple[str, ...], click.Command]]:
        if isinstance(command, click.Group):
            found: list[tuple[tuple[str, ...], click.Command]] = []
            for name, sub in sorted(command.commands.items()):
                found.extend(walk(sub, (*path, name)))
            return found
        return [(path, command)]

    return walk(typer.main.get_command(app), ())


_LEAVES = _leaves()
_UNSUPPORTED = [path for path, command in _LEAVES if json_capability(command, path) == "none"]
# Read-only commands that need no arguments and no repository: each must print
# one schema-versioned JSON document on stdout under the root flag.
_JSON_READERS = [
    ("version",),
    ("capabilities",),
    ("explain",),
    ("provider", "status"),
    ("memory", "list"),
    ("requirements", "inspect"),
    ("xrepo", "explain"),
]


@pytest.fixture(autouse=True)
def _outside_any_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MERGECRAFT_CONFIG", raising=False)


def test_the_tree_has_both_kinds_of_command() -> None:
    """Sanity: the walk sees the real tree, not an empty or all-JSON one."""
    assert len(_LEAVES) > 100
    assert ("doctor",) in _UNSUPPORTED
    assert ("version",) not in _UNSUPPORTED


@pytest.mark.parametrize("path", _UNSUPPORTED, ids=[" ".join(p) for p in _UNSUPPORTED])
def test_commands_without_json_output_reject_the_root_flag(path: tuple[str, ...]) -> None:
    """No command silently ignores ``--format json``: it exits 2 before doing anything."""
    result = CliRunner().invoke(app, ["--format", "json", *path], env=_ENV)

    assert result.exit_code == CLI_USAGE_EXIT_CODE, result.output
    assert result.stdout == ""
    assert "has no JSON output" in result.stderr


@pytest.mark.parametrize("path", _JSON_READERS, ids=[" ".join(p) for p in _JSON_READERS])
def test_json_readers_print_schema_versioned_json_on_stdout(path: tuple[str, ...]) -> None:
    """Commands that honour the flag put one JSON document on stdout."""
    result = CliRunner().invoke(app, ["--format", "json", *path], env=_ENV)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert "schema_version" in payload


def test_help_is_never_rejected() -> None:
    """``--help`` still works under the root flag."""
    result = CliRunner().invoke(app, ["--format", "json", "doctor", "--help"], env=_ENV)

    assert result.exit_code == 0, result.output


def test_an_explicit_command_format_still_wins() -> None:
    """``version --format table`` keeps text output under the root flag."""
    result = CliRunner().invoke(app, ["--format", "json", "version", "--format", "table"], env=_ENV)

    assert result.exit_code == 0, result.output
    assert not result.stdout.lstrip().startswith("{")


def test_table_format_leaves_every_command_alone() -> None:
    """The default format never triggers the rejection."""
    result = CliRunner().invoke(app, ["doctor", "--help"], env=_ENV)

    assert result.exit_code == 0, result.output


@pytest.mark.parametrize(
    "path", sorted(ROOT_FORMAT_COMMANDS), ids=[" ".join(p) for p in sorted(ROOT_FORMAT_COMMANDS)]
)
def test_root_format_commands_exist_and_read_the_root_format(path: tuple[str, ...]) -> None:
    """Each declared root-format command exists and consults the root format."""
    commands = dict(_LEAVES)
    assert path in commands, f"stale entry in ROOT_FORMAT_COMMANDS: {path}"
    source = inspect.getsource(inspect.getmodule(commands[path].callback))  # type: ignore[arg-type]
    assert any(
        name in source for name in ("wants_json_output", "get_cli_globals", "cli_json_dumps")
    )
