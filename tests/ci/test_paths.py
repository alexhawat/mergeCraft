"""Failure-path extraction from CI logs (U4 / N5).

The extractor must read a path only out of a *failure context* — a ``FAILED`` /
``ERROR`` node, a line-start ``path:line:`` citation, or a ``path(line,col)``
compiler citation — and normalise it (strip a leading ``./``, collapse repeated
``/``). A path-shaped token anywhere else in the log (a ``PASSED`` line, a
``collecting`` line, a command echo, a bare URL) is not a failure location.
"""

from __future__ import annotations

import pytest

from tests.ci.support import import_module, load_fixture

_FAILED_TEST_PATH = "tests/analyzers/test_adapters_supply_chain.py"


@pytest.mark.parametrize(
    ("log_excerpt", "expected_path"),
    [
        # A root-level file cited in a traceback citation (U4).
        ("setup.py:12: SyntaxError\n", "setup.py"),
        # A root-level file in pytest's FAILED report (U4).
        ("FAILED test_root.py::t\n", "test_root.py"),
        # A compiler citation carrying ``(line,col)`` (U4, TS/MSBuild shape).
        ("src/a.ts(3,5): error TS2322\n", "src/a.ts"),
        # A line-start citation with a ``./`` prefix must be normalised (U4).
        ("./src/a.py:3: error\n", "src/a.py"),
    ],
)
def test_failure_context_forms_are_extracted_and_normalised(
    log_excerpt: str, expected_path: str
) -> None:
    paths = import_module("mergecraft.ci.paths")
    assert paths.extract_failure_paths(log_excerpt) == [expected_path]


def test_normalize_repo_path_strips_dot_slash_and_collapses_slashes() -> None:
    paths = import_module("mergecraft.ci.paths")
    normalize = paths.normalize_repo_path
    assert normalize("./src/a.py") == "src/a.py"
    assert normalize("src//a.py") == "src/a.py"
    assert normalize("src/a.py") == "src/a.py"


def test_failure_line_accepts_dot_slash_and_line_col_forms() -> None:
    paths = import_module("mergecraft.ci.paths")
    assert paths.failure_line("./src/a.py:3: error\n", path="src/a.py") == 3
    assert paths.failure_line("src/a.ts(3,5): error TS2322\n", path="src/a.ts") == 3


def test_flaky_retry_failure_attempt_yields_only_the_failed_path() -> None:
    """The captured retry log has one FAILED node; its PASSED lines are not failures."""
    fixture = load_fixture("flaky_retry_pass.json")
    paths = import_module("mergecraft.ci.paths")
    extracted = paths.extract_failure_paths(fixture["attempts"][0]["log_excerpt"])
    assert extracted == [_FAILED_TEST_PATH]


@pytest.mark.parametrize(
    "log_excerpt",
    [
        # A green test is not a failure location (N5).
        "PASSED src/a.py::t \n",
        # A collection line names a file the run read, not one that failed (N5).
        "collecting src/a.py done\n",
        # A command echo is not a failure location (N5).
        "uv run python scripts/x.py\n",
        # A bare URL is not a failure location (N5).
        "https://example.com/src/a.py error\n",
        # A run on the runner's absolute workspace is not a repo-relative path.
        "FAILED /home/runner/work/x/y/src/a.py::t\n",
        # A URL in a failure report is not a repo-relative path.
        "FAILED https://example.com/src/a.py::t\n",
    ],
)
def test_non_failure_lines_yield_no_failure_path(log_excerpt: str) -> None:
    paths = import_module("mergecraft.ci.paths")
    assert paths.extract_failure_paths(log_excerpt) == []


def test_absolute_path_in_a_traceback_citation_stays_dropped() -> None:
    """An absolute path is never a repo-relative failure location."""
    paths = import_module("mergecraft.ci.paths")
    assert paths.extract_failure_paths("/home/runner/work/x/y/src/a.py:3: boom\n") == []
