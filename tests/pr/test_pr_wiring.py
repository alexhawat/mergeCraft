"""W5 — ``mergecraft.pr`` production wiring pins (#351).

Library unit tests under ``tests/pr/test_*.py`` already cover describe / labels /
TODOs / effort / suggestions. This file pins *product* wiring: a review-path or
CLI call site, a new ``cli/*_cmd.py`` (D10), and output-only behaviour (D13).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE, CLI_USAGE_EXIT_CODE
from tests.support.dead_package_wiring import (
    production_importers,
    production_invoked_names,
)

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}

_PR_LIBRARY_SYMBOLS = frozenset(
    {
        "build_describe_output",
        "suggest_labels",
        "scan_todo_additions",
        "classify_effort_band",
        "generate_pr_suggestions",
        "recommend_pr_split",
    }
)
_SIMILAR_SYMBOLS = frozenset({"find_similar_issues", "find_similar_changes"})


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def _invoke(*argv: str) -> Any:
    return runner.invoke(app, list(argv), env=_DUMB_ENV)


def _require_describe() -> None:
    """Fail until ``describe`` is registered (avoids XPASS on Typer usage exit)."""
    result = _invoke("describe", "--help")
    if result.exit_code != CLI_SUCCESS_EXIT_CODE:
        pytest.fail("mergecraft describe is not registered yet")


def test_pr_has_a_review_or_cli_production_call_site() -> None:
    """W5 — at least one review-path or CLI module imports ``mergecraft.pr``."""
    importers = production_importers("pr")
    assert importers, "expected a production import of mergecraft.pr (review or CLI)"
    assert any(
        path.startswith(("cli/", "modes/", "mcp/", "action/", "agents/")) or path == "main.py"
        for path in importers
    )


def test_root_help_lists_describe() -> None:
    """Happy: ``mergecraft --help`` advertises ``describe`` (#351)."""
    result = _invoke("--help")
    help_text = _plain(result.stdout + result.stderr).casefold()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, help_text
    assert "describe" in help_text


def test_describe_help_names_output_only_summary() -> None:
    """Happy: describe help is a PR summary, not an apply/write verb."""
    result = _invoke("describe", "--help")
    help_text = _plain(result.stdout + result.stderr).casefold()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, help_text
    assert "title" in help_text or "summary" in help_text or "describe" in help_text
    assert "apply" not in help_text


def test_describe_cli_emits_title_summary_walkthrough_risk_and_tests(
    tmp_path: Path,
) -> None:
    """Happy: ``mergecraft describe`` prints the #351 describe sections."""
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    result = _invoke("describe", "--repo-root", str(tmp_path))
    output = _plain(result.stdout + result.stderr).casefold()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    for section in ("title", "summary", "walkthrough", "risk", "test"):
        assert section in output, f"describe output missing {section!r}: {output}"


def test_describe_cli_does_not_write_the_reviewed_tree(tmp_path: Path) -> None:
    """D13 / #351 out of scope — describe is output-only."""
    _require_describe()
    tracked = tmp_path / "tracked.py"
    tracked.write_text("value = 1\n", encoding="utf-8")
    before = tracked.read_bytes()
    result = _invoke("describe", "--repo-root", str(tmp_path))
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, _plain(result.stdout + result.stderr)
    assert tracked.read_bytes() == before


def test_production_wiring_invokes_pr_library_surfaces() -> None:
    """W5 wires describe / labels / TODOs / effort / suggestions / split advisor."""
    invoked = production_invoked_names(exclude_package="pr")
    missing = _PR_LIBRARY_SYMBOLS - invoked
    assert not missing, f"production still does not call {sorted(missing)}"


def test_similar_issues_and_changes_are_wired() -> None:
    """#351 — similar issues and similar changes reach a production call site."""
    invoked = production_invoked_names(exclude_package="pr")
    assert invoked & _SIMILAR_SYMBOLS, (
        "expected production to call find_similar_issues and/or find_similar_changes"
    )


def test_unknown_describe_option_is_usage_error() -> None:
    """Error: unknown flag on describe is usage (2), not a local --format."""
    _require_describe()
    result = _invoke("describe", "--not-a-real-flag")
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_USAGE_EXIT_CODE, combined
