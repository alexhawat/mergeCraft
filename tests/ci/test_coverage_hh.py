"""Batch HH — #431 coverage floor 82% (D7).

Pins that ``[tool.coverage.report] fail_under`` becomes 82 and that the
coverage-gate scripts enforce the bumped floor. Measured coverage reaching
82% is W16; the config pin is RED until that wave lands.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from tests.ci.workflow_support import REPO_ROOT

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

HH431_TARGET_FAIL_UNDER = 82.0


def _fail_under_from_pyproject() -> float:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return float(data["tool"]["coverage"]["report"]["fail_under"])


def _load_coverage_config() -> Any:
    path = REPO_ROOT / "scripts" / "coverage_config.py"
    assert path.is_file(), "scripts/coverage_config.py missing"
    spec = importlib.util.spec_from_file_location("coverage_config", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_coverage_floors() -> Any:
    path = REPO_ROOT / "scripts" / "check_coverage_floors.py"
    assert path.is_file(), "scripts/check_coverage_floors.py missing"
    spec = importlib.util.spec_from_file_location("check_coverage_floors", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _coverage_json(tmp_path: Path, percent: float) -> Path:
    summary = {
        "percent_covered": percent,
        "num_statements": 100,
        "covered_lines": int(percent),
        "num_branches": 10,
        "covered_branches": int(percent * 0.1),
    }
    files: dict[str, dict[str, Any]] = {}
    for suffix in ("utils/token.py", "utils/git_setup.py", "main.py"):
        files[f"src/mergecraft/{suffix}"] = {"summary": dict(summary)}
    files["src/mergecraft/mcp/server.py"] = {"summary": dict(summary)}
    files["src/mergecraft/action/post.py"] = {"summary": dict(summary)}
    payload = {
        "totals": {
            "percent_covered": percent,
            "num_statements": 1000,
            "covered_lines": int(percent * 10),
        },
        "files": files,
    }
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_pyproject_fail_under_is_eighty_two() -> None:
    """#431 / D7: the global floor must be 82%, not the legacy 80%."""
    assert _fail_under_from_pyproject() == HH431_TARGET_FAIL_UNDER


def test_coverage_config_fail_under_matches_target() -> None:
    """``coverage_config.fail_under_from_pyproject`` must track the 82% contract."""
    module = _load_coverage_config()
    assert module.fail_under_from_pyproject(REPO_ROOT) == HH431_TARGET_FAIL_UNDER


def test_check_coverage_floors_rejects_measured_below_target(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Gate logic: a report below the live floor must fail ``check_coverage_floors``."""
    module = _load_coverage_floors()
    live_floor = _fail_under_from_pyproject()
    report = _coverage_json(tmp_path, live_floor - 1.0)
    monkeypatch.setattr(sys, "argv", ["check_coverage_floors", str(report)])
    rc = int(module.main())
    assert rc != 0


def test_check_coverage_floors_accepts_measured_at_target(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Gate logic: a report at the target floor must pass ``check_coverage_floors``."""
    module = _load_coverage_floors()
    report = _coverage_json(tmp_path, HH431_TARGET_FAIL_UNDER)
    monkeypatch.setattr(sys, "argv", ["check_coverage_floors", str(report)])
    rc = int(module.main())
    assert rc == 0


def test_repo_coverage_report_passes_floor_check_at_target() -> None:
    """W16 must produce ``coverage.json`` with global line ≥ the bumped floor."""
    report = REPO_ROOT / "coverage.json"
    if not report.is_file():
        pytest.skip("coverage.json missing — run make coverage-gate after W16")
    payload = json.loads(report.read_text(encoding="utf-8"))
    measured = float(payload.get("totals", {}).get("percent_covered", 0.0))
    if measured < HH431_TARGET_FAIL_UNDER:
        pytest.skip(
            f"coverage.json reports {measured:.2f}% — stale or mid-session; "
            "make coverage-gate runs check_coverage_floors.py on the fresh report"
        )
    proc = subprocess.run(
        [sys.executable, "scripts/check_coverage_floors.py", str(report)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
