"""CRAP scoring on coverage artifacts written by a real coverage.py run.

``tests/analyzers/fixtures/crap/real_coverage_py`` was produced by coverage.py
7.15.2 (``coverage run --branch``, then ``coverage json`` saved as
``coverage.py.json`` and ``coverage lcov``) over ``source.py``: a class method ``Foo.bar``, a decorated ``top`` and a nested
``outer.inner``. coverage.py keys methods by qualified name and its lcov writer
emits the lcov 2.x ``FN:<start>,<end>,<name>`` form; both must score.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.ci.support_crap import CRAP_FIXTURES, import_ci

_REAL = CRAP_FIXTURES / "real_coverage_py"
_PATH = "src/pkg/mod.py"
# Low bands so every scored function emits a finding we can inspect.
_SCORE_EVERYTHING = {"watch": 0.5, "elevated": 1000, "crap": 2000, "severe": 3000}


def _read(name: str) -> str:
    return (_REAL / name).read_text(encoding="utf-8")


def _score(document: str, filename: str) -> Any:
    coverage = import_ci("coverage")
    parsed = coverage.parse_coverage_artifact(document, filename=filename)
    assert parsed.skip_reason is None
    return coverage.coverage_findings(
        parsed,
        diff=_read("change.diff"),
        source_tree={_PATH: _read("source.py")},
        source="ci",
        mode="shadow",
        bands=_SCORE_EVERYTHING,
    )


def _scored(result: Any) -> dict[str, str]:
    """``symbol name -> coverage evidence`` for every emitted finding."""
    scored: dict[str, str] = {}
    for finding in result.findings:
        name = finding.message.split("`")[1]
        scored[name] = next(item for item in finding.evidence if item.startswith("coverage="))
    return scored


@pytest.mark.parametrize(
    ("artifact", "filename"),
    [("coverage.py.json", "coverage.json"), ("lcov.info", "lcov.info")],
    ids=["coverage-py-json", "lcov-2x"],
)
def test_real_artifact_scores_methods_decorated_and_nested_functions(
    artifact: str, filename: str
) -> None:
    result = _score(_read(artifact), filename)

    # The hunk's trailing context line sits in ``outer``, so it is changed too.
    assert set(_scored(result)) == {"bar", "top", "outer", "inner"}
    assert not any(note.startswith("coverage_symbols_unmatched") for note in result.run_notes)


def test_coverage_py_json_uses_line_coverage_not_the_branch_blend() -> None:
    """``Foo.bar``: 3 of 5 statements (60%); ``percent_covered`` blends branches (56%)."""
    result = _score(_read("coverage.py.json"), "coverage.json")

    assert _scored(result)["bar"] == "coverage=0.6"


def test_lcov_2x_function_rows_carry_name_and_end_line() -> None:
    parsed = import_ci("coverage").parse_lcov(_read("lcov.info"))

    rows = {item.name: item for item in parsed.functions}
    assert set(rows) == {"Foo.bar", "top", "outer", "outer.inner"}
    assert rows["Foo.bar"].start_line == 5
    # ``inner`` (lines 21-22) is unexecuted; its span ends at FN's end line, so
    # ``outer``'s own executed def line 20 does not leak into it.
    assert rows["outer.inner"].coverage == 0.0


def test_lcov_2_2_fnl_fna_records_parse() -> None:
    document = (
        "SF:src/pkg/mod.py\nDA:5,1\nDA:6,1\nDA:7,0\nFNL:0,5,7\nFNA:0,1,Foo.bar\nend_of_record\n"
    )
    parsed = import_ci("coverage").parse_lcov(document)

    assert [(item.name, item.start_line) for item in parsed.functions] == [("Foo.bar", 5)]
    assert parsed.functions[0].coverage == pytest.approx(2 / 3)


def test_unmatched_changed_symbols_are_recorded_as_a_run_note() -> None:
    coverage = import_ci("coverage")
    parsed = coverage.parse_lcov("SF:src/pkg/mod.py\nDA:14,1\nFN:14,17,top\nend_of_record\n")

    result = coverage.coverage_findings(
        parsed,
        diff=_read("change.diff"),
        source_tree={_PATH: _read("source.py")},
        source="ci",
        mode="shadow",
        bands=_SCORE_EVERYTHING,
    )

    assert set(_scored(result)) == {"top"}
    assert "coverage_symbols_unmatched=3" in result.run_notes


@pytest.mark.parametrize(
    ("percent", "expected"),
    [(1.0, 0.01), (0.8, 0.008), (55.5, 0.555)],
    ids=["one-percent", "under-one-percent", "fractional-percent"],
)
def test_coverage_py_percent_is_never_read_as_a_ratio(percent: float, expected: float) -> None:
    """A 1% function is 1% covered, not 100% (no ``<= 1.0`` ratio guess)."""
    function = {"start_line": 1, "summary": {"percent_covered": percent}}
    document = json.dumps({"files": {"src/a.py": {"functions": {"f": function}}}})
    parsed = import_ci("coverage").parse_coverage_py_json(document)

    assert parsed.functions[0].coverage == pytest.approx(expected)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("./src/a.py", "src/a.py"), ("../lib/a.py", "../lib/a.py"), (".github/x.py", ".github/x.py")],
    ids=["dot-slash", "parent-dir", "dotfile-dir"],
)
def test_lcov_path_normalisation_strips_only_a_dot_slash_prefix(raw: str, expected: str) -> None:
    parsed = import_ci("coverage").parse_lcov(f"SF:{raw}\nFN:1,f\nend_of_record\n")

    assert parsed.functions[0].path == expected
