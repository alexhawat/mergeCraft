"""#485 — inherited-drift attribution is reachable (D9 Fork A).

Locked D9 (open-issues-sweep-2026-08-24-a):

- Attribution (1): base already below the floor → inherited.
- Attribution (2): head dropped versus a base at/above the floor → caused.
- Attribution (3): ``INHERITED_BREACH_MARGIN`` inherited-drift when the base is
  already at the floor and head is at least that many points below the floor.

Impl kept Fork A: reorder so the margin branch runs. Pin that behavior.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DELTA_SCRIPT = _REPO_ROOT / "scripts" / "check_coverage_delta.py"
_FLOOR = 82.0
_MARGIN_NAMES = ("INHERITED_BREACH_MARGIN", "INHERITED_DRIFT_THRESHOLD")
_COMPARE_NAMES = ("compare_to_base", "compare_against_base")


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("check_coverage_delta_485", _DELTA_SCRIPT)
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


def _compare_fn(module: Any) -> Any:
    for name in _COMPARE_NAMES:
        fn = getattr(module, name, None)
        if callable(fn):
            return fn
    pytest.fail("check_coverage_delta must expose compare_to_base or compare_against_base")


def _drift_constant_name(module: Any) -> str | None:
    for name in _MARGIN_NAMES:
        if hasattr(module, name):
            return name
    return None


def test_attribution_1_base_below_floor_is_inherited(tmp_path: Path) -> None:
    """Happy (1): base already under the floor is inherited, not caused."""
    module = _load_module()
    compare = _compare_fn(module)
    base = _coverage_json(tmp_path / "base.json", 81.0)
    head = _coverage_json(tmp_path / "head.json", 81.0)

    result = compare(head, base, floor=_FLOOR)

    assert result.inherited is True
    assert result.caused_by_change is False
    assert "inherited" in result.message.lower()
    assert "base" in result.message.lower()


def test_attribution_2_drop_staying_above_floor_is_caused_and_non_fatal(
    tmp_path: Path,
) -> None:
    """Happy (2): head < base but head still at/above the floor is caused, not inherited."""
    module = _load_module()
    compare = _compare_fn(module)
    base = _coverage_json(tmp_path / "base.json", 83.0)
    head = _coverage_json(tmp_path / "head.json", 82.5)

    result = compare(head, base, floor=_FLOOR)

    assert result.caused_by_change is True
    assert result.inherited is False
    assert result.head_percent + 1e-9 >= result.floor
    assert "inherited" not in result.message.lower()


def test_attribution_2_drop_shallower_than_margin_stays_caused(tmp_path: Path) -> None:
    """Edge (2): below-floor drop shallower than the 1.0pp margin stays caused."""
    module = _load_module()
    compare = _compare_fn(module)
    base = _coverage_json(tmp_path / "base.json", 83.0)
    head = _coverage_json(tmp_path / "head.json", 81.5)

    result = compare(head, base, floor=_FLOOR)

    assert result.caused_by_change is True
    assert result.inherited is False
    assert 0.0 < (result.floor - result.head_percent) < 1.0


def test_equal_coverage_above_floor_is_ok(tmp_path: Path) -> None:
    """Edge: head == base above the floor is neither inherited nor caused."""
    module = _load_module()
    compare = _compare_fn(module)
    base = _coverage_json(tmp_path / "base.json", 84.0)
    head = _coverage_json(tmp_path / "head.json", 84.0)

    result = compare(head, base, floor=_FLOOR)

    assert result.inherited is False
    assert result.caused_by_change is False


def test_missing_coverage_report_raises_file_not_found(tmp_path: Path) -> None:
    """Error: a missing head or base report is FileNotFoundError naming the path."""
    module = _load_module()
    compare = _compare_fn(module)
    base = _coverage_json(tmp_path / "base.json", 83.0)
    missing = tmp_path / "missing.json"

    with pytest.raises(FileNotFoundError, match=re.escape(str(missing))):
        compare(missing, base, floor=_FLOOR)


def test_d9_inherited_drift_margin_branch_is_reachable(tmp_path: Path) -> None:
    """D9 Fork A: base at floor and head ≥ 1.0pp below the floor is inherited-drift."""
    module = _load_module()
    compare = _compare_fn(module)
    base = _coverage_json(tmp_path / "base.json", _FLOOR)
    head = _coverage_json(tmp_path / "head.json", _FLOOR - 1.5)

    result = compare(head, base, floor=_FLOOR)

    assert _drift_constant_name(module) is not None
    assert result.inherited is True
    assert result.caused_by_change is False
    assert result.base_percent + 1e-9 >= result.floor
    assert "base branch" not in result.message.lower()
    assert "inherited" in result.message.lower()


def test_d9_cli_reports_inherited_drift_for_margin_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Functional: main() exit 1 and inherited-drift for the D9 Fork A fixture."""
    module = _load_module()
    fail_under = getattr(module, "_fail_under_from_pyproject", None)
    if callable(fail_under):
        monkeypatch.setattr(module, "_fail_under_from_pyproject", lambda: _FLOOR)

    base = _coverage_json(tmp_path / "base.json", _FLOOR)
    head = _coverage_json(tmp_path / "head.json", _FLOOR - 1.5)
    monkeypatch.chdir(tmp_path)

    code = module.main([str(head.name), "--base", str(base.name)])
    captured = capsys.readouterr()
    combined = f"{captured.out}\n{captured.err}".lower()

    assert code == 1
    assert _drift_constant_name(module) is not None
    assert "inherited" in combined
    assert "base branch" not in captured.out.lower()


def test_no_third_attribution_flags(tmp_path: Path) -> None:
    """Pin: (inherited, caused_by_change) never both True — D9 forbids a third class."""
    module = _load_module()
    compare = _compare_fn(module)
    cases = (
        (81.0, 81.0),
        (83.0, 82.5),
        (_FLOOR, _FLOOR - 1.5),
        (84.0, 84.0),
        (83.0, 81.5),
    )
    for base_pct, head_pct in cases:
        base = _coverage_json(tmp_path / f"base-{base_pct}-{head_pct}.json", base_pct)
        head = _coverage_json(tmp_path / f"head-{base_pct}-{head_pct}.json", head_pct)
        result = compare(head, base, floor=_FLOOR)
        assert not (result.inherited and result.caused_by_change)


def test_recovered_head_above_floor_is_not_inherited(tmp_path: Path) -> None:
    """Recovered HEAD (base under floor, head above) must not fail as inherited."""
    module = _load_module()
    compare = _compare_fn(module)
    base = _coverage_json(tmp_path / "base.json", 81.0)
    head = _coverage_json(tmp_path / "head.json", 90.0)

    result = compare(head, base, floor=_FLOOR)

    assert result.inherited is False
    assert result.caused_by_change is False
    assert "inherited" not in result.message.lower()


def test_further_drop_on_low_base_is_caused_not_inherited(tmp_path: Path) -> None:
    """A PR that tanks coverage while base is slightly under is caused, not inherited."""
    module = _load_module()
    compare = _compare_fn(module)
    base = _coverage_json(tmp_path / "base.json", 81.0)
    head = _coverage_json(tmp_path / "head.json", 80.0)

    result = compare(head, base, floor=_FLOOR)

    assert result.inherited is False
    assert result.caused_by_change is True
    assert "inherited" not in result.message.lower()
