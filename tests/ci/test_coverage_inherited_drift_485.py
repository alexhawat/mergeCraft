"""#485 — inherited-drift attribution is reachable, or the dead branch is gone (D9).

Locked D9 (open-issues-sweep-2026-08-24-a):

- Attribution (1): base already below the floor → inherited.
- Attribution (2): head dropped versus a base at/above the floor → caused.
- Attribution (3): ``INHERITED_BREACH_MARGIN`` / ``INHERITED_DRIFT_THRESHOLD``
  inherited-drift when the base is already at the floor and head is at least
  that many points below the floor.

Today (3) is dead: ``compare_to_base`` classifies ``head < base`` first, so the
margin branch never runs. Impl may **either** reorder so a fixture can hit (3)
**or** delete the dead branch and the constant. No third attribution.

These assertions fail until one of those forks lands. Do not xfail.
"""

from __future__ import annotations

import importlib.util
import inspect
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
    """Edge (2): below-floor drop shallower than the 1.0pp margin stays caused under both D9 forks."""
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


def test_d9_inherited_drift_is_reachable_or_dead_branch_and_constant_removed(
    tmp_path: Path,
) -> None:
    """D9 XOR: fixture hits inherited-drift (3), or the constant and dead branch are gone.

    Fixture: base already at the floor, head ≥ 1.0pp below the floor (also below base).
    Today this is classified as caused (2) while ``INHERITED_BREACH_MARGIN`` still
    exists — that is the bug. Green after either D9 fork; no third attribution.
    """
    module = _load_module()
    compare = _compare_fn(module)
    base = _coverage_json(tmp_path / "base.json", _FLOOR)
    head = _coverage_json(tmp_path / "head.json", _FLOOR - 1.5)

    result = compare(head, base, floor=_FLOOR)
    constant_name = _drift_constant_name(module)
    source = inspect.getsource(compare)
    inherited_true = len(re.findall(r"inherited\s*=\s*True", source))

    if constant_name is not None:
        assert result.inherited is True, (
            f"D9: {constant_name} is still defined but base-at-floor / "
            f"head {_FLOOR - 1.5:.1f}% vs floor {_FLOOR:.1f}% did not take "
            "the inherited-drift branch. Reorder compare_to_base so the "
            "margin can fire, or delete the constant and the dead branch."
        )
        assert result.caused_by_change is False
        assert result.base_percent + 1e-9 >= result.floor
        assert "base branch" not in result.message.lower()
        assert "inherited" in result.message.lower()
        return

    assert result.inherited is False
    assert result.caused_by_change is True
    assert inherited_true == 1, (
        "D9 delete-fork: with the margin constant gone, compare_to_base must "
        "keep only attribution (1) as inherited=True (dead branch removed). "
        f"Found {inherited_true} inherited=True assignments."
    )
    for name in _MARGIN_NAMES:
        assert name not in source


def test_d9_cli_matches_inherited_drift_or_caused_remaining_attribution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Functional: main() exit 1 for the D9 fixture; message follows the chosen fork."""
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
    constant_name = _drift_constant_name(module)

    assert code == 1
    if constant_name is not None:
        assert "inherited" in combined, (
            "D9 reorder-fork: CLI must report inherited-drift for base-at-floor "
            f"head {_FLOOR - 1.5:.1f}% (constant {constant_name} still present)."
        )
        assert "base branch" not in captured.out.lower()
        return

    assert "caused" in combined
    assert "inherited" not in combined


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
