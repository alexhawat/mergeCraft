"""Unit tests for ``scripts/lint_test_honesty.py``."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "lint_test_honesty.py"
_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "test_honesty"


def _load_module(name: str, path: Path):
    import sys

    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_checker():
    assert _SCRIPT.is_file()
    return _load_module("lint_test_honesty", _SCRIPT)


@pytest.fixture(name="checker")
def fixture_checker():
    return _load_checker()


@pytest.fixture(name="visitors")
def fixture_visitors():
    return _load_module("test_honesty_visitors", _ROOT / "scripts" / "test_honesty_visitors.py")


def test_scan_flags_constant_sleep(visitors) -> None:
    target = _FIXTURES / "violation_sleep.py"
    result = visitors.scan_file(target, repo=_FIXTURES.parents[2])
    rules = {item.rule for item in result.findings}
    assert visitors.RULE_SLEEP_CONSTANT in rules


def test_scan_flags_conditional_assert(visitors) -> None:
    target = _FIXTURES / "violation_conditional_assert.py"
    result = visitors.scan_file(target, repo=_FIXTURES.parents[2])
    assert any(item.rule == visitors.RULE_CONDITIONAL_ASSERT for item in result.findings)


def test_scan_flags_swallowed_exception(visitors) -> None:
    target = _FIXTURES / "violation_swallow.py"
    result = visitors.scan_file(target, repo=_FIXTURES.parents[2])
    assert any(item.rule == visitors.RULE_EXCEPT_SWALLOW for item in result.findings)


def test_suppression_comment_skips_sleep(visitors) -> None:
    target = _FIXTURES / "allowed_with_suppression.py"
    result = visitors.scan_file(target, repo=_FIXTURES.parents[2])
    assert not result.findings


def test_baseline_filters_grandfathered_findings(checker, visitors, tmp_path: Path) -> None:
    target = _FIXTURES / "violation_sleep.py"
    result = visitors.scan_file(target, repo=_FIXTURES.parents[2])
    assert result.findings
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps({"fingerprints": [result.findings[0].fingerprint]}),
        encoding="utf-8",
    )
    baseline = checker.load_baseline(baseline_path)
    new, grandfathered = checker.filter_findings(result, baseline)
    assert grandfathered
    assert not new


def test_check_fixture_files_fail_without_baseline(checker) -> None:
    targets = [
        _FIXTURES / "violation_sleep.py",
        _FIXTURES / "violation_conditional_assert.py",
        _FIXTURES / "violation_swallow.py",
    ]
    code, result, new, _grandfathered = checker.check_test_honesty(
        targets,
        repo=_FIXTURES.parents[2],
        baseline=checker.BaselineFile(fingerprints=frozenset(), documented_count=0),
        skip_ruff=True,
    )
    assert result.findings
    assert new
    assert code == 1


def test_honesty_allow_regex_requires_reason(visitors) -> None:
    lines = ["time.sleep(1)", "pass"]
    assert not visitors._line_has_allow(lines, 1)
    lines = ["time.sleep(1)  # honesty: allow polling window"]
    assert visitors._line_has_allow(lines, 1)
