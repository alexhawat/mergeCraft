"""W6 — coverage ratchet in ``make ci`` (#142, rescoped)."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from typing import Any

import pytest

from tests.ci.workflow_support import REPO_ROOT, read_text

_W6 = pytest.mark.xfail(
    reason="green after W6: coverage ratchet + coverage-gate in make ci",
    strict=False,
)


@_W6
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


@_W6
def test_ratchet_fails_when_coverage_drops_below_floor(tmp_path: Path) -> None:
    module = _load_ratchet()
    check = getattr(module, "check_coverage_ratchet", None) or getattr(module, "main", None)
    assert callable(check)
    report = _coverage_json(tmp_path, 10.0)
    rc = int(check([str(report)])) if check.__name__ == "main" else int(check(report, floor=65.0))
    assert rc != 0, "ratchet accepted coverage below the floor"


@_W6
def test_ratchet_fails_when_coverage_exceeds_floor_without_bump(tmp_path: Path) -> None:
    """Guard-deletion: a large rise without bumping the floor must fail."""
    module = _load_ratchet()
    check = getattr(module, "check_coverage_ratchet", None) or getattr(module, "main", None)
    assert callable(check)
    report = _coverage_json(tmp_path, 99.0)
    if check.__name__ == "main":
        rc = int(check([str(report)]))
    else:
        rc = int(check(report, floor=65.0, margin=5.0))
    assert rc != 0, "ratchet accepted coverage far above the floor without a bump commit"


@_W6
def test_ratchet_passes_within_margin(tmp_path: Path) -> None:
    module = _load_ratchet()
    check = getattr(module, "check_coverage_ratchet", None) or getattr(module, "main", None)
    assert callable(check)
    report = _coverage_json(tmp_path, 66.0)
    rc = (
        int(check([str(report)]))
        if check.__name__ == "main"
        else int(check(report, floor=65.0, margin=5.0))
    )
    assert rc == 0
