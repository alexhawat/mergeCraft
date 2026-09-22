"""Coverage floor metric contract tests (#824)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tests.ci.workflow_support import REPO_ROOT

if TYPE_CHECKING:
    import pytest


def _load_module() -> Any:
    path = REPO_ROOT / "scripts" / "check_coverage_floors.py"
    spec = importlib.util.spec_from_file_location("check_coverage_floors_824", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _summary(
    *,
    statements: int = 100,
    covered_lines: int = 100,
    branches: int = 100,
    covered_branches: int = 100,
    combined: float = 100.0,
) -> dict[str, int | float]:
    return {
        "num_statements": statements,
        "covered_lines": covered_lines,
        "num_branches": branches,
        "covered_branches": covered_branches,
        "percent_covered": combined,
    }


def _complete_report(*, combined: float = 82.0) -> dict[str, Any]:
    files = {
        "src/mergecraft/utils/token.py": {"summary": _summary()},
        "src/mergecraft/utils/git_setup.py": {"summary": _summary()},
        "src/mergecraft/main.py": {"summary": _summary()},
    }
    for prefix in ("mcp", "action", "security", "analyzers", "agents", "review"):
        files[f"src/mergecraft/{prefix}/example.py"] = {"summary": _summary()}
    return {
        "totals": {
            "num_statements": 900,
            "covered_lines": 900,
            "num_branches": 900,
            "covered_branches": 900,
            "percent_covered": combined,
        },
        "files": files,
    }


def _run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    report: dict[str, Any],
) -> int:
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["check_coverage_floors.py", str(path)])
    return int(_load_module().main())


def test_module_line_floor_uses_line_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = _complete_report()
    report["files"]["src/mergecraft/utils/git_setup.py"]["summary"] = _summary(
        covered_lines=90,
        combined=95.0,
    )

    assert _run(tmp_path, monkeypatch, report) == 1
    assert "utils/git_setup.py line 90.0% < floor 92.0%" in capsys.readouterr().err


def test_module_line_floor_ignores_lower_combined_percentage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _complete_report()
    for payload in report["files"].values():
        payload["summary"]["percent_covered"] = 50.0

    assert _run(tmp_path, monkeypatch, report) == 0


def test_zero_statement_branchless_module_uses_hundred_percent_convention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _complete_report()
    report["files"]["src/mergecraft/main.py"]["summary"] = _summary(
        statements=0,
        covered_lines=0,
        branches=0,
        covered_branches=0,
        combined=0.0,
    )

    assert _run(tmp_path, monkeypatch, report) == 0


def test_missing_required_module_and_prefix_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = _complete_report()
    del report["files"]["src/mergecraft/utils/token.py"]
    del report["files"]["src/mergecraft/security/example.py"]

    assert _run(tmp_path, monkeypatch, report) == 1
    stderr = capsys.readouterr().err
    assert "no coverage data for utils/token.py" in stderr
    assert "no coverage data for prefix security/" in stderr


def test_global_floor_remains_native_combined_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = _complete_report(combined=81.99)

    assert _run(tmp_path, monkeypatch, report) == 1
    assert "global combined coverage 81.99% < floor 82.00%" in capsys.readouterr().err
