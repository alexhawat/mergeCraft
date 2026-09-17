"""J1.3 — hunk units, stable ids, cache key (D2)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.jev.support import J3_XFAIL, PINNED_MODEL, import_jev, load_diff


def _segment() -> Any:
    return import_jev("segment")


@J3_XFAIL
def test_segment_hunks_extracts_one_unit_with_bounded_context() -> None:
    segment = _segment()
    units = segment.segment_hunks(load_diff("privilege_drop_home.diff"), context_lines=3)
    assert len(units) == 1
    unit = units[0]
    assert unit.kind == "hunk"
    assert unit.path == "src/mergecraft/utils/privilege.py"
    assert unit.context_lines <= 3
    assert "setpriv" in unit.content


@J3_XFAIL
def test_function_units_are_out_of_scope() -> None:
    segment = _segment()
    units = segment.segment_hunks(load_diff("privilege_drop_home.diff"))
    assert all(unit.kind == "hunk" for unit in units)
    assert not any(getattr(unit, "kind", None) == "function" for unit in units)


@J3_XFAIL
def test_unit_ids_are_stable_across_calls() -> None:
    segment = _segment()
    first = segment.segment_hunks(load_diff("privilege_drop_home.diff"))
    second = segment.segment_hunks(load_diff("privilege_drop_home.diff"))
    assert segment.unit_id(first[0]) == segment.unit_id(second[0])
    assert first[0].unit_id == second[0].unit_id


@J3_XFAIL
def test_unit_ids_differ_across_files() -> None:
    segment = _segment()
    privilege = segment.segment_hunks(load_diff("privilege_drop_home.diff"))
    auth = segment.segment_hunks(load_diff("auth_stem_author.diff"))
    assert segment.unit_id(privilege[0]) != segment.unit_id(auth[0])


@J3_XFAIL
def test_cache_key_covers_content_hash_pack_and_pinned_model() -> None:
    segment = _segment()
    unit = segment.segment_hunks(load_diff("privilege_drop_home.diff"))[0]
    key = segment.unit_cache_key(unit, pack_id="unit/v1", model=PINNED_MODEL)
    same = segment.unit_cache_key(unit, pack_id="unit/v1", model=PINNED_MODEL)
    other_pack = segment.unit_cache_key(unit, pack_id="evidence/v1", model=PINNED_MODEL)
    other_model = segment.unit_cache_key(unit, pack_id="unit/v1", model="jev-1.12.0")
    assert key == same
    assert key != other_pack
    assert key != other_model


@J3_XFAIL
def test_empty_diff_yields_no_units() -> None:
    segment = _segment()
    assert segment.segment_hunks("") == []
    assert segment.segment_hunks(load_diff("empty.diff")) == []


@J3_XFAIL
def test_none_diff_raises_structured_error() -> None:
    segment = _segment()
    with pytest.raises(segment.JevError) as exc_info:
        segment.segment_hunks(None)
    assert exc_info.value.code == "invalid_diff"


@J3_XFAIL
def test_unicode_paths_survive_segmentation() -> None:
    segment = _segment()
    units = segment.segment_hunks(load_diff("unicode_path.diff"))
    assert len(units) == 1
    assert units[0].path == "src/mergecraft/café.py"
    assert "🎉" in units[0].content


@J3_XFAIL
def test_analyzer_flagged_hunks_are_not_residual() -> None:
    segment = _segment()
    units = segment.segment_hunks(load_diff("privilege_drop_home.diff"))
    finding = {
        "path": "src/mergecraft/utils/privilege.py",
        "start_line": units[0].start_line,
    }
    residual = segment.residual_units(units, analyzer_findings=[finding])
    assert residual == []
