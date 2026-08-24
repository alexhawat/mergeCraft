"""Coverage delta exit policy — regressions above floor do not fail."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DELTA_SCRIPT = _REPO_ROOT / "scripts" / "check_coverage_delta.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("check_coverage_delta_exit", _DELTA_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _coverage_json(path: Path, percent: float) -> Path:
    path.write_text(
        json.dumps({"totals": {"percent_covered": percent}}),
        encoding="utf-8",
    )
    return path


def test_compare_to_base_marks_regression_above_floor_as_non_fatal(tmp_path: Path) -> None:
    module = _load_module()
    base = _coverage_json(tmp_path / "base.json", 83.0)
    head = _coverage_json(tmp_path / "head.json", 82.5)

    result = module.compare_to_base(head, base, floor=82.0)

    assert result.caused_by_change is True
    assert result.inherited is False
    assert result.head_percent >= 82.0


def test_compare_to_base_marks_shallower_than_margin_drop_below_floor_as_caused(
    tmp_path: Path,
) -> None:
    """A below-floor drop shallower than INHERITED_BREACH_MARGIN stays caused.

    Depth 0.5pp (< 1.0) remains attribution (2) under both D9 forks: reorder
    so the margin can fire, or delete the dead branch. Do not require the
    current (2)-before-(3) order — that made inherited-drift unreachable.
    """
    module = _load_module()
    base = _coverage_json(tmp_path / "base.json", 83.0)
    head = _coverage_json(tmp_path / "head.json", 81.5)

    result = module.compare_to_base(head, base, floor=82.0)

    assert result.caused_by_change is True
    assert result.inherited is False


def test_main_exits_zero_for_regression_above_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_module()
    base = _coverage_json(tmp_path / "base.json", 83.0)
    head = _coverage_json(tmp_path / "head.json", 82.5)
    monkeypatch.chdir(tmp_path)

    assert module.main([str(head.name), "--base", str(base.name)]) == 0
