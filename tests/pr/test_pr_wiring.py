"""W4.1 — ``mergecraft.pr`` production wiring pins (#351 / W5).

Library unit tests under ``tests/pr/test_*.py`` already cover describe / labels /
TODOs / effort / suggestions. This file pins *product* wiring: a review-path or
CLI call site, a new ``cli/*_cmd.py`` (D10), and output-only behaviour (D13).

Current-state tests pass while the package is dead. Tests that assert wiring
exists are ``xfail(strict=False)`` until W5.
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
    CLI_DIR,
    cli_cmd_path,
    production_importers,
    production_invoked_names,
    root_callback_source,
)

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}

_W5 = pytest.mark.xfail(
    reason="green after W5: wire mergecraft.pr (#351)",
    strict=False,
)

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


def test_pr_package_has_no_production_call_site_yet() -> None:
    """W4.1 current state: ``mergecraft.pr`` is library-only (issue #351)."""
    assert production_importers("pr") == []


def test_pr_cli_cmd_module_does_not_exist_yet() -> None:
    """W4.1 current state: no new ``cli/pr_cmd.py`` / ``describe_cmd.py`` (D10)."""
    assert cli_cmd_path("pr", "describe") is None


def test_root_help_does_not_list_describe_yet() -> None:
    """W4.1 current state: ``mergecraft describe`` is not registered."""
    result = _invoke("--help")
    help_text = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, help_text
    assert not re.search(r"^\s+describe\b", help_text, re.MULTILINE)


def test_describe_command_is_currently_a_usage_error() -> None:
    """W4.1 current state: invoking ``describe`` is unknown (exit 2)."""
    result = _invoke("describe")
    assert result.exit_code == CLI_USAGE_EXIT_CODE


def test_d10_root_callback_still_owns_format_quiet_color() -> None:
    """D10 — W5 must not restyle the root callback; tests invoke ``app`` as-is."""
    source = root_callback_source()
    assert "def _root(" in source
    assert '"--format"' in source
    assert '"--quiet"' in source
    assert '"--color"' in source


@_W5
def test_pr_has_a_review_or_cli_production_call_site() -> None:
    """W5 — at least one review-path or CLI module imports ``mergecraft.pr``."""
    importers = production_importers("pr")
    assert importers, "expected a production import of mergecraft.pr (review or CLI)"
    assert any(
        path.startswith(("cli/", "modes/", "mcp/", "action/", "agents/")) or path == "main.py"
        for path in importers
    )


@_W5
def test_pr_cli_is_a_new_cmd_module() -> None:
    """D10 — ``mergecraft describe`` lives in a new ``cli/*_cmd.py`` leaf."""
    path = cli_cmd_path("pr", "describe")
    assert path is not None, "expected src/mergecraft/cli/pr_cmd.py or describe_cmd.py"
    source = path.read_text(encoding="utf-8")
    assert "def run(" in source or "def describe" in source or "typer.Typer" in source
    assert path.resolve() != (CLI_DIR / "app.py").resolve()


@_W5
def test_root_help_lists_describe() -> None:
    """Happy: ``mergecraft --help`` advertises ``describe`` (#351)."""
    result = _invoke("--help")
    help_text = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, help_text
    assert re.search(r"^\s+describe\b", help_text, re.MULTILINE)


@_W5
def test_describe_help_names_output_only_summary() -> None:
    """Happy: describe help is a PR summary, not an apply/write verb."""
    result = _invoke("describe", "--help")
    help_text = _plain(result.stdout + result.stderr).casefold()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, help_text
    assert "title" in help_text or "summary" in help_text or "describe" in help_text
    assert "apply" not in help_text


@_W5
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


@_W5
def test_describe_cli_does_not_write_the_reviewed_tree(tmp_path: Path) -> None:
    """D13 / #351 out of scope — describe is output-only."""
    _require_describe()
    tracked = tmp_path / "tracked.py"
    tracked.write_text("value = 1\n", encoding="utf-8")
    before = tracked.read_bytes()
    result = _invoke("describe", "--repo-root", str(tmp_path))
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, _plain(result.stdout + result.stderr)
    assert tracked.read_bytes() == before


@_W5
def test_production_wiring_invokes_pr_library_surfaces() -> None:
    """W5 wires describe / labels / TODOs / effort / suggestions / split advisor."""
    invoked = production_invoked_names(exclude_package="pr")
    missing = _PR_LIBRARY_SYMBOLS - invoked
    assert not missing, f"production still does not call {sorted(missing)}"


@_W5
def test_similar_issues_and_changes_are_wired() -> None:
    """#351 — similar issues and similar changes reach a production call site."""
    invoked = production_invoked_names(exclude_package="pr")
    assert invoked & _SIMILAR_SYMBOLS, (
        "expected production to call find_similar_issues and/or find_similar_changes"
    )


@_W5
def test_unknown_describe_option_is_usage_error() -> None:
    """Error: unknown flag on describe is usage (2), not a local --format."""
    _require_describe()
    result = _invoke("describe", "--not-a-real-flag")
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_USAGE_EXIT_CODE, combined


def test_w5_does_not_fold_describe_into_root_callback() -> None:
    """D10 — adding describe must not change ``_root`` option names."""
    source = root_callback_source()
    assert "def _root(" in source
    assert '"--format"' in source
    assert '"--quiet"' in source
    assert '"--color"' in source
    root_block = source.split("def _root(", 1)[1].split("\n@app.", 1)[0]
    assert "build_describe_output" not in root_block
