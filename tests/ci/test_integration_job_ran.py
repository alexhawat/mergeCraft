"""TH1 RED — integration job must execute at least one test (H2 / D9).

``make test-integration`` currently selects ``-m 'integration and not live'`` while
every marked test is secret-gated and skips, so CI reports zero executed tests.
TH2 wires ``scripts/check_integration_ran.py`` (or equivalent) into the workflow.
"""

from __future__ import annotations

import ast
import importlib.util
import re
from pathlib import Path
from typing import Any

import pytest

from tests.ci.workflow_support import (
    REPO_ROOT,
    job,
    load_workflow,
    makefile_target_body,
    read_text,
)


def test_integration_job_runs_supported_python_matrix() -> None:
    """The minimum supported Python must execute the non-live integration suite."""
    integration = job(load_workflow("integration.yml"), "integration-pr")
    matrix = integration["strategy"]["matrix"]
    assert {"3.11", "3.14"} <= set(matrix["python"])
    assert not matrix.get("exclude"), "supported integration runtimes must not be excluded"
    for event in ("pull_request", "push", "workflow_dispatch"):
        assert f"github.event_name == '{event}'" in integration["if"]
    doc = load_workflow("integration.yml")
    triggers = doc.get("on", doc.get(True))
    assert {"main", "pre-0.0.1", "release/**"} <= set(triggers["push"]["branches"])
    assert {"main", "pre-0.0.1"} <= set(triggers["pull_request"]["branches"])
    steps = integration["steps"]
    bootstrap = next(step for step in steps if step.get("uses") == "./.github/actions/bootstrap")
    assert bootstrap["with"]["python-version"] == "${{ matrix.python }}"
    execution = next(step for step in steps if step.get("run") == "make test-integration")
    assert not execution.get("if"), "every matrix entry must run the integration suite"
    assert not execution.get("continue-on-error"), "integration failures must block CI"
    assert not integration.get("continue-on-error")


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
        (
            "================== 2 errors in 0.12s ==================",
            2,
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


def test_count_executed_uses_last_summary_line_only() -> None:
    """Earlier spurious matches must not override the final pytest summary."""
    count_executed = _load_count_executed()
    log = (
        "noise: 100 passed, 50 failed in unrelated output\n"
        "============================= 2 passed in 0.42s ==============================\n"
    )
    assert count_executed(log) == 2


_META_MARKERS = {"integration", "hermetic_integration"}

# The genuinely hermetic integration files: no secret, no binary, no root.
_HERMETIC_FILES = (
    "tests/integration/test_provider_failures.py",
    "tests/integration/test_nous_404_failover_466.py",
)


def _marker_names(node: ast.AST) -> set[str]:
    found: set[str] = set()
    if (
        isinstance(node, ast.Attribute)
        and node.attr in _META_MARKERS
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "mark"
    ):
        found.add(node.attr)
    if isinstance(node, (ast.List, ast.Tuple)):
        for element in node.elts:
            found |= _marker_names(element)
    return found


def _declared_markers(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    markers: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "pytestmark" for target in node.targets
        ):
            markers |= _marker_names(node.value)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                markers |= _marker_names(decorator)
    return markers


def test_no_ci_meta_test_carries_integration_or_hermetic_markers() -> None:
    """A tests/ci/ meta-test must never be able to satisfy the integration gate."""
    offenders = []
    for path in sorted((REPO_ROOT / "tests" / "ci").rglob("test_*.py")):
        declared = _declared_markers(path)
        if declared & _META_MARKERS:
            rel = path.relative_to(REPO_ROOT)
            offenders.append(f"{rel}: {sorted(declared & _META_MARKERS)}")
    assert not offenders, (
        "these tests/ci/ tests carry an integration marker and can satisfy the "
        f"integration meta-gate: {offenders}"
    )


def test_test_integration_selects_the_hermetic_marker() -> None:
    body = makefile_target_body("test-integration")
    assert "hermetic_integration" in body, (
        f"make test-integration must select hermetic_integration:\n{body}"
    )
    assert "integration and not live" in body, (
        "the live-integration contract checker reads this substring; keep it"
    )


def test_hermetic_marker_is_registered_in_pytest_ini() -> None:
    section = read_text("pyproject.toml").split("[tool.pytest.ini_options]", 1)[1]
    assert re.search(r'^\s*"hermetic_integration:', section, re.MULTILINE), (
        "hermetic_integration must be registered in [tool.pytest.ini_options].markers"
    )


@pytest.mark.parametrize("relative", _HERMETIC_FILES)
def test_hermetic_integration_files_are_marked_and_skip_free(relative: str) -> None:
    text = read_text(relative)
    assert "hermetic_integration" in text, (
        f"{relative} must carry pytest.mark.hermetic_integration so the PR job runs it"
    )
    assert "pytest.skip" not in text, f"{relative} must not skip; it is keyless and hermetic"
    assert "skipif" not in text, f"{relative} must not gate itself with skipif"
