"""DQ1 RED — mutation harness plumbing unit tests (#502, DQ5)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.ci.workflow_support import REPO_ROOT


def _load_mutate_module() -> Any:
    path = REPO_ROOT / "scripts" / "mutate_decision_modules.py"
    name = "mutate_decision_modules_test"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_enumerate_line_mutants_counts_and_labels() -> None:
    """Tiny fixture with known operators yields predictable mutant labels."""
    module = _load_mutate_module()
    source = "if value == 0:\n    return True\n"
    mutants = module._enumerate_line_mutants(source)
    assert mutants, "expected at least one mutant for a comparison line"
    assert any(mutant.label == "L1:'=='->'!='" for mutant in mutants)


def test_comments_and_blank_lines_are_skipped() -> None:
    """Comments and blank lines must not produce mutants."""
    module = _load_mutate_module()
    source = "# comment only\n\nif x == y:\n    pass\n"
    mutants = module._enumerate_line_mutants(source)
    line_numbers = {mutant.line_no for mutant in mutants}
    assert 1 not in line_numbers
    assert 2 not in line_numbers
    assert 3 in line_numbers


def test_replacements_inside_string_literals_are_not_mutated() -> None:
    """Tokenize-safe enumeration must not mutate operators inside string literals."""
    module = _load_mutate_module()
    source = 'message = "a == b"\nif x == y:\n    pass\n'
    mutants = module._enumerate_line_mutants(source)
    assert not any(mutant.line_no == 1 for mutant in mutants)
    assert any(mutant.line_no == 2 for mutant in mutants)


def test_apply_mutant_changes_only_the_target_line() -> None:
    """``_apply_mutant`` round-trips a single enumerated mutant on its line."""
    module = _load_mutate_module()
    source = "if a == b:\n    keep = 1\n"
    mutants = module._enumerate_line_mutants(source)
    target = next(mutant for mutant in mutants if mutant.line_no == 1)
    mutated = module._apply_mutant(source, target)
    lines = mutated.splitlines()
    assert "!=" in lines[0]
    assert lines[1] == "    keep = 1"


def test_apply_mutant_label_matches_the_enumerated_label() -> None:
    """Applied mutant must match the label produced by enumeration."""
    module = _load_mutate_module()
    source = "if flag is True:\n    pass\n"
    mutants = module._enumerate_line_mutants(source)
    labeled = next(mutant for mutant in mutants if "True" in mutant.label)
    assert labeled.label in {mutant.label for mutant in mutants}
    applied = module._apply_mutant(source, labeled)
    assert "False" in applied.splitlines()[labeled.line_no - 1]


def _sandbox(module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    source = tmp_path / "sample.py"
    source.write_text("result = True\n")
    monkeypatch.setattr(module, "resolve_module_path", lambda *args, **kwargs: source)
    monkeypatch.setattr(module, "_module_test_dirs", lambda: {"sample.py": ("tests",)})
    return source


@pytest.mark.parametrize("exit_code", [0, 1, 2, 3, 4, 5, -9])
def test_only_test_failures_kill_mutants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exit_code: int
) -> None:
    module = _load_mutate_module()
    source = _sandbox(module, tmp_path, monkeypatch)
    calls = []

    def run(*args: Any, **kwargs: Any) -> tuple[int, str]:
        calls.append(source.read_text())
        return (0 if len(calls) == 1 else exit_code, "pytest output")

    monkeypatch.setattr(module, "_run_pytest", run)
    result = module._mutate_module(
        "sample.py",
        sandbox_root=tmp_path,
        python=tmp_path / "python",
        max_mutants=1,
        seed=42,
        verbose=0,
    )
    assert calls == ["result = True\n", "result = False\n"]
    assert source.read_text() == "result = True\n"
    assert result.killed == int(exit_code == 1)
    assert result.survived == int(exit_code == 0)
    assert result.errors == int(exit_code not in {0, 1})
    assert result.mutants == int(exit_code in {0, 1})


@pytest.mark.parametrize("exit_code", [1, 2, 3, 4, 5, -9])
def test_failed_baseline_prevents_scoring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exit_code: int
) -> None:
    module = _load_mutate_module()
    source = _sandbox(module, tmp_path, monkeypatch)
    calls = []

    def run(*args: Any, **kwargs: Any) -> tuple[int, str]:
        calls.append(source.read_text())
        return exit_code, "baseline diagnostic"

    monkeypatch.setattr(module, "_run_pytest", run)
    with pytest.raises(module.BaselineFailure, match="baseline diagnostic"):
        module._mutate_module(
            "sample.py",
            sandbox_root=tmp_path,
            python=tmp_path / "python",
            max_mutants=1,
            seed=42,
            verbose=0,
        )
    assert calls == ["result = True\n"]
    assert source.read_text() == "result = True\n"


@pytest.mark.parametrize("baseline_failure", [False, True])
def test_cli_fails_invalid_runs_and_cleans_up(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    baseline_failure: bool,
) -> None:
    module = _load_mutate_module()
    _sandbox(module, tmp_path, monkeypatch)
    cleaned = []
    monkeypatch.setattr(
        module,
        "_prepare_mutation_sandbox",
        lambda: (tmp_path, tmp_path, tmp_path / "python", lambda: cleaned.append(True)),
    )
    codes = iter([2] if baseline_failure else [0, 2])
    monkeypatch.setattr(module, "_run_pytest", lambda *a, **kw: (next(codes), "collection failed"))
    assert module.main(["--module", "sample.py", "--max-mutants", "1"]) == 2
    assert cleaned == [True]
