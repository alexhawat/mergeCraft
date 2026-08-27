"""TH1 RED — honest coverage ratchet contracts (H10 / D12, TH6).

``check_coverage_ratchet.py`` currently self-approves when ``fail_under`` is lowered
without a merge-base comparison, and treats ``measured > floor + 5`` as a hard
failure instead of a warning. TH6 implements D12.
"""

from __future__ import annotations

import importlib.util
import io
import json
import re
import subprocess
import sys
import tomllib
from contextlib import redirect_stderr
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tests.ci.workflow_support import REPO_ROOT

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

_DEFAULT_MARGIN = 5.0


def _load_ratchet_module() -> Any:
    path = REPO_ROOT / "scripts" / "check_coverage_ratchet.py"
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
            "num_statements": 1000,
            "covered_lines": int(percent * 10),
        },
        "files": {},
    }
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _fail_under_from_pyproject() -> float:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return float(data["tool"]["coverage"]["report"]["fail_under"])


def test_lowering_fail_under_fails_via_the_floor_comparison(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Lowering ``fail_under`` must fail via the merge-base floor comparison (#503)."""
    floor = _fail_under_from_pyproject()
    lowered = max(floor - 2.0, 1.0)
    report = _coverage_json(tmp_path, floor + 1.0)

    module = _load_ratchet_module()
    monkeypatch.setattr(module, "_fail_under_from_pyproject", lambda repo_root=None: lowered)
    monkeypatch.setattr(
        module,
        "_fail_under_from_merge_base",
        lambda *args, **kwargs: (floor + 5.0, None),
    )

    stderr = io.StringIO()
    with redirect_stderr(stderr):
        rc = int(module.check_coverage_ratchet(report, floor=lowered))

    combined = stderr.getvalue()
    assert rc != 0
    assert "below merge-base floor" in combined
    assert "merge-base lookup failed" not in combined


def test_merge_base_error_is_a_distinct_failure_from_a_lowered_floor(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Merge-base errors must be separable from lowered-floor comparison failures (#503)."""
    floor = _fail_under_from_pyproject()
    lowered = max(floor - 2.0, 1.0)
    report = _coverage_json(tmp_path, floor + 1.0)
    merge_detail = "merge-base lookup failed for HEAD vs origin/pre-0.0.1"

    module = _load_ratchet_module()
    monkeypatch.setattr(module, "_fail_under_from_pyproject", lambda repo_root=None: lowered)
    monkeypatch.setattr(
        module,
        "_fail_under_from_merge_base",
        lambda *args, **kwargs: (None, merge_detail),
    )

    stderr = io.StringIO()
    with redirect_stderr(stderr):
        rc = int(module.check_coverage_ratchet(report, floor=lowered))

    combined = stderr.getvalue()
    assert rc != 0
    assert merge_detail in combined
    assert "below merge-base floor" not in combined


def test_lowering_fail_under_without_baseline_commit_fails(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Lowering ``fail_under`` without a merge-base ratchet check must fail (D12 / H10)."""
    floor = _fail_under_from_pyproject()
    lowered = max(floor - 2.0, 1.0)
    report = _coverage_json(tmp_path, floor + 1.0)

    module = _load_ratchet_module()
    monkeypatch.setattr(module, "_fail_under_from_pyproject", lambda repo_root=None: lowered)
    rc = int(module.check_coverage_ratchet(report, floor=lowered))

    assert rc != 0, (
        "lowering fail_under without merge-base comparison must fail the ratchet "
        "(TH6 / D12 — currently self-approving)"
    )


def test_raising_coverage_above_ceiling_warns_not_fails(tmp_path: Path) -> None:
    """``measured > floor + margin`` should warn, not fail, unless hard ceiling is opted in (D12)."""
    floor = _fail_under_from_pyproject()
    measured = floor + _DEFAULT_MARGIN + 2.0
    report = _coverage_json(tmp_path, measured)

    proc = subprocess.run(
        [sys.executable, "scripts/check_coverage_ratchet.py", str(report)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, (
        f"coverage above the soft ceiling should warn, not fail (D12 — TH6)\n{combined}"
    )
    assert re.search(r"warn", combined, re.IGNORECASE), (
        "expected a warning when measured exceeds floor + margin (D12)"
    )
