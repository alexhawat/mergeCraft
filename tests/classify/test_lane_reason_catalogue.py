"""The lane-reason catalogue and ``docs/blast-radius.md`` cannot drift (#1056 part 2).

``LANE_REASON_CATALOGUE`` is the closed set of reason codes with their default
lanes. ``docs/blast-radius.md`` carries a *Lane reasons* table
(``code | default lane | when``) that must list exactly those codes with
exactly those lanes, and a *Checklist* section naming every gate. Adding a
code without a docs row, or a docs row without a code, fails here.

The catalogue is read through the ``api`` fixture so the suite collects before
the production names exist.
"""

from __future__ import annotations

import re
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest

_DOC = Path(__file__).resolve().parents[2] / "docs" / "blast-radius.md"
_HEADING = re.compile(r"^(?P<level>#{2,4})\s+(?P<title>.+?)\s*$")
_SEPARATOR_CELL = re.compile(r"^:?-{3,}:?$")
_CODE_SHAPE = re.compile(r"^[a-z]+(\.[a-z][a-z_-]*)+$")

# The codes and default lanes the catalogue must carry. Later parts of #1056 add
# codes; they never change these.
EXPECTED_CODES: dict[str, str] = {
    "signal.missing.paths": "medium",
    "signal.missing.diff": "medium",
    "paths.migrations": "high",
    "paths.auth": "high",
    "paths.security": "high",
    "paths.payment": "high",
    "paths.permissions": "high",
    "paths.secrets_config": "high",
    "paths.deployment": "high",
    "paths.irreversible_infra": "high",
    "diff.destructive_sql": "high",
    "diff.secret_assignment": "high",
    "diff.irreversible_command": "high",
    "paths.public_api": "medium",
    "deps.changed": "medium",
    "tests.missing": "medium",
    "paths.review_config": "medium",
    "source.changed": "medium",
    "paths.generated": "low",
    "source.small_isolated": "low",
    "baseline.clean": "low",
}


@pytest.fixture
def api() -> Any:
    """Load the classifier module lazily so new names fail per test, not at collection."""
    return import_module("mergecraft.classify.blast_radius")


def _section(text: str, title: str) -> list[str]:
    """Lines under the first heading named ``title`` up to the next same-or-higher heading."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = _HEADING.match(line)
        if match and match["title"].strip().lower() == title.lower():
            level = len(match["level"])
            body: list[str] = []
            for following in lines[index + 1 :]:
                nested = _HEADING.match(following)
                if nested and len(nested["level"]) <= level:
                    break
                body.append(following)
            return body
    raise AssertionError(f"docs/blast-radius.md has no `{title}` section")


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _table(section: list[str]) -> tuple[list[str], list[list[str]]]:
    """The first markdown table in ``section``: its header and body rows."""
    rows: list[list[str]] = []
    for line in section:
        if line.lstrip().startswith("|"):
            rows.append(_cells(line))
        elif rows:
            break
    if len(rows) < 2:
        raise AssertionError("the `Lane reasons` section has no markdown table")
    header, *body = rows
    body = [row for row in body if not all(_SEPARATOR_CELL.match(cell) for cell in row)]
    return [cell.lower() for cell in header], body


def _strip_code(cell: str) -> str:
    return cell.strip().strip("`").strip()


def _doc_rows() -> list[tuple[str, str]]:
    """(code, default lane) for every row of the docs *Lane reasons* table."""
    _header, body = _table(_section(_DOC.read_text(encoding="utf-8"), "Lane reasons"))
    return [(_strip_code(row[0]), _strip_code(row[1]).lower()) for row in body]


def _drift(rows: dict[str, str], catalogue: dict[str, str]) -> list[str]:
    """Every disagreement between docs rows and the catalogue, as readable messages."""
    problems = [f"no docs row for `{code}`" for code in sorted(set(catalogue) - set(rows))]
    problems += [
        f"docs row for unknown code `{code}`" for code in sorted(set(rows) - set(catalogue))
    ]
    problems += [
        f"`{code}` is {rows[code]} in docs but {catalogue[code]} in the catalogue"
        for code in sorted(set(rows) & set(catalogue))
        if rows[code] != catalogue[code]
    ]
    return problems


# ── the catalogue itself ─────────────────────────────────────────────────────


def test_the_catalogue_carries_every_locked_code_with_its_default_lane(api: Any) -> None:
    catalogue = dict(api.LANE_REASON_CATALOGUE)

    assert {code: catalogue.get(code) for code in EXPECTED_CODES} == EXPECTED_CODES


def test_every_catalogue_lane_is_a_known_lane(api: Any) -> None:
    assert set(api.LANE_REASON_CATALOGUE.values()) <= {"low", "medium", "high"}
    assert {"low", "medium", "high"} <= set(api.LANE_REASON_CATALOGUE.values())


def test_every_code_is_a_stable_dotted_lowercase_name(api: Any) -> None:
    bad = [code for code in api.LANE_REASON_CATALOGUE if not _CODE_SHAPE.match(code)]

    assert len(api.LANE_REASON_CATALOGUE) >= len(EXPECTED_CODES)
    assert bad == []


# ── the docs table ───────────────────────────────────────────────────────────


def test_the_docs_table_has_the_documented_columns() -> None:
    header, body = _table(_section(_DOC.read_text(encoding="utf-8"), "Lane reasons"))

    assert header == ["code", "default lane", "when"]
    assert body
    assert all(len(row) == 3 and row[2] for row in body)


def test_the_docs_table_lists_no_code_twice() -> None:
    codes = [code for code, _lane in _doc_rows()]

    assert codes
    assert len(codes) == len(set(codes))


def test_the_docs_table_matches_the_catalogue(api: Any) -> None:
    rows = dict(_doc_rows())

    assert _drift(rows, dict(api.LANE_REASON_CATALOGUE)) == []
    assert set(rows) >= set(EXPECTED_CODES)


def test_a_code_added_without_a_docs_row_is_caught(api: Any) -> None:
    catalogue = {**api.LANE_REASON_CATALOGUE, "paths.brand_new": "high"}

    assert _drift(dict(_doc_rows()), catalogue) == ["no docs row for `paths.brand_new`"]


def test_a_docs_row_without_a_code_is_caught(api: Any) -> None:
    rows = {**dict(_doc_rows()), "paths.ghost": "medium"}

    assert _drift(rows, dict(api.LANE_REASON_CATALOGUE)) == [
        "docs row for unknown code `paths.ghost`"
    ]


def test_a_docs_row_with_the_wrong_lane_is_caught(api: Any) -> None:
    rows = {**dict(_doc_rows()), "deps.changed": "low"}

    assert _drift(rows, dict(api.LANE_REASON_CATALOGUE)) == [
        "`deps.changed` is low in docs but medium in the catalogue"
    ]


# ── the checklist section ────────────────────────────────────────────────────


def test_the_docs_checklist_section_names_every_gate_and_the_null_rule(api: Any) -> None:
    section = "\n".join(_section(_DOC.read_text(encoding="utf-8"), "Checklist"))

    missing = [gate for gate in api.GATE_ORDER if f"`{gate}`" not in section]
    assert missing == []
    assert "null" in section
    assert "eligible" in section
