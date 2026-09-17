"""C2 — changed-hunk → enclosing-function resolution (C-D4)."""

from __future__ import annotations

from typing import Any

from tests.ci.support_crap import (
    CRAP_FIXTURES,
    SKIP_ENCLOSING_SYMBOL_UNRESOLVED,
    import_ci,
    load_diff,
    load_source,
)


def _changed() -> Any:
    return import_ci("changed_functions")


def test_hunk_inside_function_resolves_enclosing_symbol() -> None:
    changed = _changed()
    source = load_source("watch")
    symbol = changed.resolve_enclosing_symbol("src/mod.py", 3, source)
    assert symbol is not None
    assert symbol.name == "fn_watch"
    assert symbol.path == "src/mod.py"
    assert symbol.start_line == 1


def test_changed_functions_from_diff_returns_only_the_enclosing_function() -> None:
    changed = _changed()
    symbols = changed.changed_functions_from_diff(
        load_diff("watch"),
        source_tree={"src/mod.py": load_source("watch")},
    )
    names = [item.name for item in symbols]
    assert names == ["fn_watch"]
    assert all(item.path == "src/mod.py" for item in symbols)


def test_unresolvable_hunk_emits_nothing_never_file_scope() -> None:
    """C-D4: no enclosing symbol → skip, zero findings, never a file-level score."""
    coverage = import_ci("coverage")
    changed = _changed()
    root = CRAP_FIXTURES / "unresolvable"
    source = (root / "source.py").read_text(encoding="utf-8")
    diff = (root / "change.diff").read_text(encoding="utf-8")
    artifact = (root / "coverage.json").read_text(encoding="utf-8")

    symbol = changed.resolve_enclosing_symbol("src/unresolvable.py", 1, source)
    assert symbol is None

    parsed = coverage.parse_coverage_py_json(artifact)
    result = coverage.coverage_findings(
        parsed,
        diff=diff,
        source_tree={"src/unresolvable.py": source},
        source="ci",
        mode="shadow",
    )
    assert result.findings == []
    assert result.skip_reason == SKIP_ENCLOSING_SYMBOL_UNRESOLVED
    assert all(getattr(item, "start_line", None) is not None for item in result.findings)


def test_empty_diff_yields_no_changed_functions() -> None:
    assert _changed().changed_functions_from_diff("", source_tree={}) == []


def test_unicode_path_survives_resolution() -> None:
    changed = _changed()
    source = "def fn_ünicode() -> int:\n    return 1\n"
    symbol = changed.resolve_enclosing_symbol("src/mód.py", 2, source)
    assert symbol is not None
    assert symbol.name == "fn_ünicode"
    assert symbol.path == "src/mód.py"
