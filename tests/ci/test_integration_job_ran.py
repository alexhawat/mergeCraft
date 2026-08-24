"""TH1 RED — integration job must execute at least one test (H2 / D9).

``make test-integration`` currently selects ``-m 'integration and not live'`` while
every marked test is secret-gated and skips, so CI reports zero executed tests.
TH2 wires ``scripts/check_integration_ran.py`` (or equivalent) into the workflow.
"""

from __future__ import annotations

import os
import re
import subprocess

import pytest

from tests.ci.workflow_support import REPO_ROOT

_PYTEST_SUMMARY = re.compile(
    r"(?P<passed>\d+) passed(?:, (?P<failed>\d+) failed)?(?:, (?P<skipped>\d+) skipped)?"
)


def _count_executed_tests(combined_output: str) -> int:
    """Return passed + failed from the last pytest summary line, or 0 when absent."""
    executed = 0
    for match in _PYTEST_SUMMARY.finditer(combined_output):
        passed = int(match.group("passed"))
        failed = int(match.group("failed") or 0)
        executed = passed + failed
    return executed


@pytest.mark.xfail(
    reason="green after TH2: integration marker must execute at least one test",
    strict=False,
)
def test_integration_marker_executes_at_least_one_test() -> None:
    """``make test-integration`` must not report zero executed tests (passed + failed == 0)."""
    env = os.environ.copy()
    env["MERGECRAFT_PYTEST_JOBS"] = "0"
    proc = subprocess.run(
        ["make", "test-integration"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    combined = proc.stdout + proc.stderr
    executed = _count_executed_tests(combined)
    assert executed > 0, (
        "integration job executed zero tests — secret-gated skips must not satisfy "
        f"the meta-gate (pytest rc={proc.returncode})\n{combined[-2000:]}"
    )
