"""TH1 RED — integration job must execute at least one test (H2 / D9).

``make test-integration`` currently selects ``-m 'integration and not live'`` while
every marked test is secret-gated and skips, so CI reports zero executed tests.
TH2 wires ``scripts/check_integration_ran.py`` (or equivalent) into the workflow.
"""

from __future__ import annotations

import importlib.util
from typing import Any

import pytest

from tests.ci.workflow_support import REPO_ROOT


def _load_count_executed() -> Any:
    path = REPO_ROOT / "scripts" / "check_integration_ran.py"
    spec = importlib.util.spec_from_file_location("check_integration_ran", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    count_executed = getattr(module, "count_executed", None)
    assert callable(count_executed)
    return count_executed


@pytest.mark.integration
def test_integration_job_always_runs_smoke() -> None:
    """Always-executed integration smoke so the PR job never reports zero tests (D9)."""
    assert (REPO_ROOT / "scripts" / "check_integration_ran.py").is_file()


@pytest.mark.parametrize(
    ("summary_line", "expected"),
    [
        ("============================= 5 passed in 0.42s ==============================", 5),
        ("============================= 3 failed in 1.02s ==============================", 3),
        (
            "================== 1 failed, 2 passed, 1 skipped in 0.88s ==================",
            3,
        ),
        (
            "================== 3 passed, 2 failed, 1 skipped in 0.88s ==================",
            5,
        ),
    ],
)
def test_count_executed_parses_pytest_summary(summary_line: str, expected: int) -> None:
    """``count_executed`` must count passed + failed for common pytest summary shapes."""
    count_executed = _load_count_executed()
    assert count_executed(summary_line) == expected


def test_count_executed_returns_zero_when_summary_missing() -> None:
    """Absent summary lines must not satisfy the integration meta-gate."""
    count_executed = _load_count_executed()
    assert count_executed("collecting ... no tests ran\n") == 0
