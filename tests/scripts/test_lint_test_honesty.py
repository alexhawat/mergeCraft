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
    result = visitors.scan_file(target, repo=_ROOT)
    rules = {item.rule for item in result.findings}
    assert visitors.RULE_SLEEP_CONSTANT in rules


def test_scan_flags_conditional_assert(visitors) -> None:
    target = _FIXTURES / "violation_conditional_assert.py"
    result = visitors.scan_file(target, repo=_ROOT)
    assert any(item.rule == visitors.RULE_CONDITIONAL_ASSERT for item in result.findings)


def test_scan_flags_swallowed_exception(visitors) -> None:
    target = _FIXTURES / "violation_swallow.py"
    result = visitors.scan_file(target, repo=_ROOT)
    assert any(item.rule == visitors.RULE_EXCEPT_SWALLOW for item in result.findings)


def test_suppression_comment_skips_sleep(visitors) -> None:
    target = _FIXTURES / "allowed_with_suppression.py"
    result = visitors.scan_file(target, repo=_ROOT)
    assert not result.findings


def test_baseline_filters_grandfathered_findings(checker, visitors, tmp_path: Path) -> None:
    target = _FIXTURES / "violation_sleep.py"
    result = visitors.scan_file(target, repo=_ROOT)
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
        repo=_ROOT,
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


def test_scan_flags_flake_and_rerun(visitors) -> None:
    target = _FIXTURES / "violation_flake.py"
    result = visitors.scan_file(target, repo=_ROOT)
    rules = {item.rule for item in result.findings}
    assert visitors.RULE_FLAKE_MARKER in rules
    assert visitors.RULE_RERUN_CONFIG in rules


def test_scan_flags_inflated_timeout(visitors) -> None:
    target = _FIXTURES / "violation_timeout.py"
    result = visitors.scan_file(target, repo=_ROOT)
    assert any(item.rule == visitors.RULE_TIMEOUT_INFLATED for item in result.findings)


def test_scan_flags_timeout_disabled(visitors) -> None:
    target = _FIXTURES / "violation_timeout_disabled.py"
    result = visitors.scan_file(target, repo=_ROOT)
    assert any(item.rule == visitors.RULE_TIMEOUT_INFLATED for item in result.findings)


def test_scan_flags_self_mock_warning(visitors) -> None:
    target = _FIXTURES / "violation_self_mock.py"
    result = visitors.scan_file(target, repo=_ROOT)
    hits = [f for f in result.findings if f.rule == visitors.RULE_SELF_MOCK]
    assert hits
    assert hits[0].level == "warning"


def test_scan_flags_contextlib_suppress(visitors) -> None:
    target = _FIXTURES / "violation_suppress.py"
    result = visitors.scan_file(target, repo=_ROOT)
    assert any(item.rule == visitors.RULE_EXCEPT_SWALLOW for item in result.findings)


def test_sleep_zero_not_flagged(visitors, tmp_path: Path) -> None:
    path = tmp_path / "test_yield.py"
    path.write_text(
        "import asyncio\n\nasync def test_yield():\n    await asyncio.sleep(0)\n",
        encoding="utf-8",
    )
    result = visitors.scan_file(path, repo=tmp_path)
    assert not result.findings


def test_duplicate_sleep_gets_distinct_anchors(visitors, tmp_path: Path) -> None:
    text = (
        "import time\n\n"
        "def test_one():\n"
        "    time.sleep(0.5)\n"
        "def test_two():\n"
        "    time.sleep(0.5)\n"
    )
    path = tmp_path / "tests" / "test_dup.py"
    path.parent.mkdir(parents=True)
    path.write_text(text, encoding="utf-8")
    result = visitors.scan_file(path, repo=tmp_path)
    sleep_hits = [f for f in result.findings if f.rule == visitors.RULE_SLEEP_CONSTANT]
    assert len(sleep_hits) == 2
    assert sleep_hits[0].anchor != sleep_hits[1].anchor


def test_conditional_assert_inside_with_under_if(visitors) -> None:
    target = _FIXTURES / "violation_conditional_with.py"
    result = visitors.scan_file(target, repo=_ROOT)
    assert any(item.rule == visitors.RULE_CONDITIONAL_ASSERT for item in result.findings)


def test_fingerprint_stable_when_lines_shift(visitors, tmp_path: Path) -> None:
    body = "def test_branch():\n    flag = True\n    if flag:\n        assert flag\n"
    path = tmp_path / "tests" / "test_shift.py"
    path.parent.mkdir(parents=True)
    path.write_text(body, encoding="utf-8")
    first = visitors.scan_file(path, repo=tmp_path).findings
    path.write_text("# header comment\n" + body, encoding="utf-8")
    second = visitors.scan_file(path, repo=tmp_path).findings
    assert len(first) == 1
    assert len(second) == 1
    assert first[0].fingerprint == second[0].fingerprint


def test_ruff_pass_excludes_honesty_fixtures(checker) -> None:
    code = checker.run_ruff_test_honesty(repo=_ROOT)
    assert code == 0


def test_relative_path_arguments_resolve_against_repo(checker, visitors) -> None:
    code, result, new, _ = checker.check_test_honesty(
        [Path("tests/scripts/fixtures/test_honesty/violation_sleep.py")],
        repo=_ROOT,
        baseline=checker.BaselineFile(fingerprints=frozenset(), documented_count=0),
        skip_ruff=True,
    )
    assert result.findings
    assert new
    assert code == 1


def _conditional_hits(visitors, tmp_path: Path, body: str) -> list[int]:
    path = tmp_path / "tests" / "test_loop.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("def test_loop(items, flag):\n" + body, encoding="utf-8")
    result = visitors.scan_file(path, repo=tmp_path)
    return [f.line_no for f in result.findings if f.rule == visitors.RULE_CONDITIONAL_ASSERT]


@pytest.mark.parametrize("literal", ["(1, 2)", "[1]", "{1, 2}", "(1, *items)"])
def test_assert_in_for_over_non_empty_literal_is_unconditional(
    visitors, tmp_path: Path, literal: str
) -> None:
    body = f"    for value in {literal}:\n        assert value\n"
    assert _conditional_hits(visitors, tmp_path, body) == []


@pytest.mark.parametrize(
    "body",
    [
        "    for value in items:\n        assert value\n",
        "    for value in ():\n        assert value\n",
        "    for value in (*items,):\n        assert value\n",
        "    for value in (1, 2):\n        if flag:\n            assert value\n",
        "    for value in (1, 2):\n        if flag:\n            continue\n        assert value\n",
        "    for value in (1, 2):\n        if flag:\n            break\n        assert value\n",
        "    if flag:\n        for value in (1, 2):\n            assert value\n",
        "    for item in items:\n        for value in (1, 2):\n            assert value\n",
        "    while flag:\n        assert flag\n",
    ],
)
def test_assert_in_loop_that_may_not_run_stays_conditional(
    visitors, tmp_path: Path, body: str
) -> None:
    assert len(_conditional_hits(visitors, tmp_path, body)) == 1


@pytest.fixture(name="baseline_repo")
def fixture_baseline_repo(checker, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the checker at a throwaway repo with one grandfathered sleep."""
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_old.py").write_text(
        "import time\n\ndef test_old():\n    time.sleep(0.5)\n", encoding="utf-8"
    )
    monkeypatch.setattr(checker, "REPO", tmp_path)
    monkeypatch.setattr(checker, "TESTS", tests)
    monkeypatch.setattr(checker, "BASELINE_PATH", tmp_path / "baseline.json")
    load = checker.load_baseline
    monkeypatch.setattr(checker, "load_baseline", lambda: load(tmp_path / "baseline.json"))
    return tmp_path


def test_write_baseline_records_the_tree_and_makes_it_pass(checker, baseline_repo: Path) -> None:
    assert checker.main(["--skip-ruff"]) == 1
    assert checker.main(["--write-baseline", "--skip-ruff"]) == 0
    payload = json.loads((baseline_repo / "baseline.json").read_text(encoding="utf-8"))
    assert payload == {
        "violation_count": 1,
        "fingerprints": ["tests/test_old.py:sleep_constant:test_old:time.sleep(0.5)#1"],
    }
    assert checker.main(["--skip-ruff"]) == 0


def test_prune_baseline_drops_fixed_entries_without_adding_new_ones(
    checker, baseline_repo: Path
) -> None:
    assert checker.main(["--write-baseline", "--skip-ruff"]) == 0
    (baseline_repo / "tests" / "test_old.py").write_text(
        "import asyncio\n\nasync def test_new():\n    await asyncio.sleep(0.7)\n",
        encoding="utf-8",
    )
    assert checker.main(["--prune-baseline", "--skip-ruff"]) == 0
    payload = json.loads((baseline_repo / "baseline.json").read_text(encoding="utf-8"))
    assert payload == {"violation_count": 0, "fingerprints": []}
    assert checker.main(["--skip-ruff"]) == 1


def test_baseline_rewrite_refuses_partial_scan(checker, baseline_repo: Path) -> None:
    target = str(baseline_repo / "tests" / "test_old.py")
    assert checker.main(["--write-baseline", target]) == 2
    assert not (baseline_repo / "baseline.json").exists()
