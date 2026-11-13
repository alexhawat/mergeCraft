"""Lazy entrypoints retain public imports, parser errors, and completion behavior."""

from __future__ import annotations

import importlib
import runpy
import sys
from typing import TYPE_CHECKING

import click
import pytest
from click.testing import CliRunner
from typer.main import get_command

from mergecraft.cli.command_catalog import COMMANDS
from mergecraft.cli.help_text import terminal_help

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("package_name", "public_name", "implementation"),
    [
        ("mergecraft.analyzers", "make_finding", "mergecraft.analyzers.finding"),
        ("mergecraft.mcp", "ToolContext", "mergecraft.mcp.context"),
        ("mergecraft.utils", "parse_timeout", "mergecraft.utils.time_parse"),
    ],
    ids=["analyzer-factory", "mcp-context", "timeout-parser"],
)
def test_public_imports_preserve_canonical_objects(
    monkeypatch: pytest.MonkeyPatch, package_name: str, public_name: str, implementation: str
) -> None:
    package = importlib.import_module(package_name)
    # Exercise the uncached public import even when another test used this API.
    monkeypatch.delattr(package, public_name, raising=False)
    imported = getattr(package, public_name)
    assert imported is getattr(importlib.import_module(implementation), public_name)
    assert getattr(package, public_name) is imported


@pytest.mark.parametrize(
    "package_name",
    ["mergecraft.analyzers", "mergecraft.mcp", "mergecraft.utils"],
    ids=["analyzers", "mcp", "utils"],
)
def test_unknown_public_attribute_uses_normal_python_errors(package_name: str) -> None:
    package = importlib.import_module(package_name)
    assert not hasattr(package, "not_a_mergecraft_api")
    with pytest.raises(AttributeError, match="not_a_mergecraft_api"):
        _ = package.not_a_mergecraft_api


@pytest.mark.parametrize("option", ["--version", "-v"], ids=["long", "short"])
def test_module_entrypoint_prints_build_identity(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], option: str
) -> None:
    import mergecraft
    from mergecraft import build_metadata

    monkeypatch.setenv("MERGECRAFT_BUILD_COMMIT", "abcdef0123456789")
    monkeypatch.setattr(sys, "argv", ["mergecraft", option])
    build_metadata.resolve_build_commit.cache_clear()
    try:
        runpy.run_module("mergecraft.cli.entrypoint", run_name="__main__")
        captured = capsys.readouterr()
        assert captured.out == f"{mergecraft.__version__} (abcdef0)\n"
        assert captured.err == ""
    finally:
        build_metadata.resolve_build_commit.cache_clear()


@pytest.mark.parametrize(
    ("args", "exit_code", "expected"),
    [
        (["provider", "--help"], 0, "auth"),
        (["--version", "--unknown-option"], 2, "No such option"),
    ],
    ids=["selected-command-help", "invalid-combined-version-option"],
)
def test_module_entrypoint_keeps_real_parser_behavior(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    args: list[str],
    exit_code: int,
    expected: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.setattr(sys, "argv", ["mergecraft", *args])
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("mergecraft.cli.entrypoint", run_name="__main__")
    assert exc.value.code == exit_code
    captured = capsys.readouterr()
    assert expected in captured.out + captured.err


def test_completion_leaves_selected_command_ready_for_execution() -> None:
    from mergecraft.cli.app import app

    root = get_command(app)
    assert isinstance(root, click.Group)
    with click.Context(root) as ctx:
        names = {item.value for item in root.shell_complete(ctx, "rev")}
    assert "review" in names
    assert "diff-review" not in names
    result = CliRunner().invoke(root, ["review", "--help"], env={"NO_COLOR": "1", "TERM": "dumb"})
    assert result.exit_code == 0, result.output
    assert "--diff" in result.output


@pytest.mark.parametrize("command_name", sorted(COMMANDS), ids=sorted(COMMANDS))
def test_catalog_summary_matches_resolved_command_help(command_name: str) -> None:
    """Import-free discovery text stays aligned with the command's own help."""
    from mergecraft.cli.app import app

    root = get_command(app)
    assert isinstance(root, click.Group)
    with click.Context(root) as ctx:
        command = root.get_command(ctx, command_name)
    assert command is not None
    assert command.help
    summary = command.help.strip().splitlines()[0]
    assert terminal_help(COMMANDS[command_name].help) == terminal_help(summary)
    assert command.hidden is COMMANDS[command_name].hidden
