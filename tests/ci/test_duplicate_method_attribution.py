"""Regression: duplicate method names must not cross-attribute evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests.ci.support_crap import import_ci

_DUPLICATE_FIXTURES = (
    Path(__file__).resolve().parents[1] / "analyzers" / "fixtures" / "crap" / "duplicate_method"
)


def _load_duplicate(name: str) -> str:
    return (_DUPLICATE_FIXTURES / name).read_text(encoding="utf-8")


def _coverage() -> Any:
    return import_ci("coverage")


def _mutation() -> Any:
    return import_ci("mutation")


def _changed() -> Any:
    return import_ci("changed_functions")


def test_coverage_py_json_skips_wrong_duplicate_method() -> None:
    coverage = _coverage()
    source = _load_duplicate("source.py")
    diff = _load_duplicate("change.diff")
    parsed = coverage.parse_coverage_py_json(_load_duplicate("coverage.json"))
    result = coverage.coverage_findings(
        parsed,
        diff=diff,
        source_tree={"src/mod.py": source},
        source="ci",
        mode="shadow",
    )
    assert result.findings == []


def test_coverage_py_json_skips_one_row_without_start_line_when_duplicates() -> None:
    coverage = _coverage()
    source = _load_duplicate("source.py")
    diff = _load_duplicate("change.diff")
    parsed = coverage.parse_coverage_py_json(_load_duplicate("coverage.nostart.json"))
    rows = [row for row in parsed.functions if row.name == "run"]
    assert len(rows) == 1
    assert rows[0].start_line is None

    result = coverage.coverage_findings(
        parsed,
        diff=diff,
        source_tree={"src/mod.py": source},
        source="ci",
        mode="shadow",
    )
    assert result.findings == []


def test_lcov_disambiguates_duplicate_method_by_start_line() -> None:
    coverage = _coverage()
    changed = _changed()
    source = _load_duplicate("source.py")
    diff = _load_duplicate("change.diff")
    symbols = changed.changed_functions_from_diff(
        diff,
        source_tree={"src/mod.py": source},
    )
    assert len(symbols) == 1
    assert symbols[0].name == "run"
    assert symbols[0].start_line == 9

    parsed = coverage.parse_lcov(_load_duplicate("lcov.info"))
    rows = [row for row in parsed.functions if row.name == "run"]
    assert len(rows) == 2
    assert {row.start_line for row in rows} == {2, 9}

    matched = coverage._lookup_coverage(
        parsed.functions,
        path="src/mod.py",
        name="run",
        start_line=symbols[0].start_line,
    )
    assert matched is not None
    assert matched.start_line == 9

    result = coverage.coverage_findings(
        parsed,
        diff=diff,
        source_tree={"src/mod.py": source},
        source="ci",
        mode="shadow",
    )
    assert all(finding.start_line != 2 for finding in result.findings)


def test_mutation_skips_survivor_on_unchanged_duplicate_method() -> None:
    mutation = _mutation()
    changed = _changed()
    source = _load_duplicate("source.py")
    diff = _load_duplicate("change.diff")
    symbols = changed.changed_functions_from_diff(
        diff,
        source_tree={"src/mod.py": source},
    )
    parsed = mutation.parse_stryker_json(
        (
            Path(__file__).resolve().parents[1]
            / "analyzers"
            / "fixtures"
            / "mutation"
            / "duplicate-method-stryker.json"
        ).read_text(encoding="utf-8")
    )
    result = mutation.mutation_findings(
        parsed,
        changed_functions=symbols,
        diff=diff,
        source_tree={"src/mod.py": source},
        source="ci",
        mode="shadow",
    )
    assert result.findings == []
