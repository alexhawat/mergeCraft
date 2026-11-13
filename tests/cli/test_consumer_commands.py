"""Consumer help omits removed previews and source-only maintenance commands."""

from __future__ import annotations

from tests.docs.support import load_script_module
from typer.testing import CliRunner

from mergecraft.cli.app import app


def test_removed_pipeline_command_is_rejected() -> None:
    result = CliRunner().invoke(app, ["pipeline", "--help"])
    assert result.exit_code == 2
    assert "No such command" in result.output


def test_source_checkout_keeps_maintainer_commands() -> None:
    for args in (["eval", "--help"], ["analyzers", "docs", "--help"]):
        result = CliRunner().invoke(app, args)
        assert result.exit_code == 0, result.output


def test_consumer_reference_omits_maintainer_commands() -> None:
    generator = load_script_module("scripts/gen_reference_docs.py")
    paths = {path for path, _ in generator._walk_typer_commands(app)}
    assert not any(path[0] in {"pipeline", "eval"} for path in paths)
    assert ("analyzers", "docs") not in paths
    assert ("review",) in paths
    assert ("analyzers", "list") in paths
