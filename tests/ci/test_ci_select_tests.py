"""PR-tier pytest selection helper (#1493)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tests.ci.workflow_support import REPO_ROOT


def _module():
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import ci_select_tests as module

    return module


def test_tests_for_path_maps_src_and_ci_touchpoints() -> None:
    module = _module()
    assert module._tests_for_path("src/mergecraft/review/budget_trend.py") == {
        "tests/review/test_budget_trend.py"
    }
    assert module._tests_for_path(".github/workflows/ci.yml") == {"tests/ci"}
    assert module._tests_for_path("README.md") == set()


def test_main_falls_back_when_git_diff_unavailable(tmp_path: Path) -> None:
    script = REPO_ROOT / "scripts" / "ci_select_tests.py"
    run = subprocess.run(
        [sys.executable, str(script), "--base", "nonexistent-ref-for-diff"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0
    assert run.stdout.strip() == "tests"
