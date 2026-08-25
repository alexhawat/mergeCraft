"""W6 — coverage ratchet in ``make ci`` (#142, rescoped)."""

from __future__ import annotations

import importlib.util
import json
import re
import tomllib
from pathlib import Path
from typing import Any

import pytest

from tests.ci.workflow_support import REPO_ROOT, read_text


def _fail_under() -> float:
    """Load the live floor so tests track ``pyproject.toml``, not a stale literal."""
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    floor = data["tool"]["coverage"]["report"]["fail_under"]
    return float(floor)


def _load_coverage_config() -> Any:
    path = REPO_ROOT / "scripts" / "coverage_config.py"
    assert path.is_file(), "scripts/coverage_config.py missing"
    spec = importlib.util.spec_from_file_location("coverage_config", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_coverage_config_fail_under_matches_pyproject() -> None:
    """Direct pin: ``coverage_config.fail_under_from_pyproject`` is the floor source."""
    module = _load_coverage_config()
    assert module.fail_under_from_pyproject(REPO_ROOT) == _fail_under()
    assert module.repo_root() == REPO_ROOT


def test_coverage_config_missing_pyproject_raises(tmp_path: Path) -> None:
    module = _load_coverage_config()
    with pytest.raises(FileNotFoundError):
        module.fail_under_from_pyproject(tmp_path)


def test_make_ci_graph_includes_coverage_gate() -> None:
    """Producer → consumer: ``make ci`` / ``CI_STEPS`` must invoke ``coverage-gate``."""
    makefile = read_text("Makefile")
    ci_steps = re.search(r"^CI_STEPS\s*:?=.*$", makefile, re.MULTILINE)
    ci_target = re.search(r"^ci:.*$", makefile, re.MULTILINE)
    blob = " ".join(part.group(0) for part in (ci_steps, ci_target) if part)
    assert "coverage-gate" in blob, (
        "coverage-gate is not in the make ci graph (CI_STEPS / ci: recipe)"
    )


def _load_ratchet() -> Any:
    path = REPO_ROOT / "scripts" / "check_coverage_ratchet.py"
    assert path.is_file(), "scripts/check_coverage_ratchet.py missing"
    spec = importlib.util.spec_from_file_location("check_coverage_ratchet", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _coverage_json(tmp_path: Path, percent: float) -> Path:
    payload = {
        "totals": {
            "percent_covered": percent,
            "num_statements": 100,
            "covered_lines": int(percent),
        },
        "files": {},
    }
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _run_ratchet(check: Any, report: Path, **kwargs: Any) -> int:
    if check.__name__ == "main":
        return int(check([str(report)]))
    return int(check(report, **kwargs))


def test_ratchet_fails_when_coverage_drops_below_floor(tmp_path: Path) -> None:
    module = _load_ratchet()
    check = getattr(module, "check_coverage_ratchet", None) or getattr(module, "main", None)
    assert callable(check)
    floor = _fail_under()
    report = _coverage_json(tmp_path, max(0.0, floor - 60.0))
    rc = _run_ratchet(check, report)
    assert rc != 0, "ratchet accepted coverage below the floor"


def test_ratchet_warns_when_coverage_exceeds_floor_without_bump(tmp_path: Path) -> None:
    """D12: a large rise without bumping the floor warns by default (exit 0)."""
    module = _load_ratchet()
    check = getattr(module, "check_coverage_ratchet", None) or getattr(module, "main", None)
    assert callable(check)
    report = _coverage_json(tmp_path, 99.0)
    rc = _run_ratchet(check, report, margin=5.0)
    assert rc == 0, "ratchet should warn, not fail, when coverage exceeds the soft ceiling (D12)"


def test_ratchet_fails_with_hard_ceiling_when_above_margin(tmp_path: Path) -> None:
    """``--hard-ceiling`` restores the legacy fail-on-above-margin behaviour."""
    module = _load_ratchet()
    check = getattr(module, "check_coverage_ratchet", None) or getattr(module, "main", None)
    assert callable(check)
    report = _coverage_json(tmp_path, 99.0)
    rc = _run_ratchet(check, report, margin=5.0, hard_ceiling=True)
    assert rc != 0, "hard ceiling must fail when coverage far exceeds the floor"


def test_ratchet_passes_within_margin(tmp_path: Path) -> None:
    module = _load_ratchet()
    check = getattr(module, "check_coverage_ratchet", None) or getattr(module, "main", None)
    assert callable(check)
    floor = _fail_under()
    report = _coverage_json(tmp_path, floor + 1.0)
    rc = _run_ratchet(check, report, margin=5.0)
    assert rc == 0


def test_ratchet_passes_when_github_base_ref_empty_on_push(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Push events expose ``GITHUB_BASE_REF=""``; must not resolve to ``origin/``."""
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_BASE_REF", "")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/pre-0.0.1")

    module = _load_ratchet()
    check = getattr(module, "check_coverage_ratchet", None) or getattr(module, "main", None)
    assert callable(check)
    floor = _fail_under()
    report = _coverage_json(tmp_path, floor + 1.0)
    rc = _run_ratchet(check, report, margin=5.0)
    assert rc == 0
