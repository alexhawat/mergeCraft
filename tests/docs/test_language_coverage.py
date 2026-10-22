"""The language coverage page stays tied to the catalog it measures (#860).

The matrix is only useful while it lists every language the analyzer catalog declares
and its counts agree with the catalog; the sourced pull requests must carry a
permissive licence and a link, so nothing unlicensed is queued for vendoring.
"""

from __future__ import annotations

import re
from collections import Counter

from mergecraft.analyzers.registry import load_catalog
from tests.ci.workflow_support import read_text

_PAGE = "docs/language-coverage.md"
_PERMISSIVE = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "MPL-2.0", "Unlicense"}


def _matrix_rows() -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for line in read_text(_PAGE).splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 5 and cells[1].isdigit():
            rows[cells[0]] = cells
    return rows


def _pr_rows() -> list[list[str]]:
    return [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in read_text(_PAGE).splitlines()
        if re.search(r"\| \[#\d+\]\(https://github\.com/", line)
    ]


def test_the_matrix_lists_every_catalog_language_with_the_catalog_tool_count() -> None:
    declared: Counter[str] = Counter()
    for manifest in load_catalog():
        declared.update(manifest.languages or [])

    rows = _matrix_rows()

    assert set(rows) == set(declared)
    for language, cells in rows.items():
        assert int(cells[1]) == declared[language], f"{language}: tool count drifted"


def test_the_golden_column_matches_the_golden_corpus() -> None:
    from tests.ci.workflow_support import REPO_ROOT

    golden = {
        path.name.split("-")[1] for path in (REPO_ROOT / "evals/cases/golden").glob("golden-*.json")
    }
    marked = {language for language, cells in _matrix_rows().items() if cells[2] == "yes"}

    assert marked == golden


def test_every_sourced_pull_request_is_permissively_licensed_and_linked() -> None:
    rows = _pr_rows()

    assert len(rows) >= 20
    for row in rows:
        assert row[3] in _PERMISSIVE, row
        assert re.search(r"\(https://github\.com/[^/]+/[^/]+/pull/\d+\)", row[2]), row


def test_the_sourced_count_column_matches_the_table() -> None:
    per_language = Counter(row[0] for row in _pr_rows())

    for language, cells in _matrix_rows().items():
        assert int(cells[4]) == per_language.get(language, 0), language


def test_the_page_carries_all_three_deliverables() -> None:
    text = read_text(_PAGE)

    for heading in (
        "## Coverage matrix",
        "## Sourced public pull requests",
        "## Prioritized work list",
    ):
        assert heading in text
