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


@pytest.mark.parametrize("failure", ["dataclass-import", "collection-interrupt", "test-interrupt"])
def test_real_pytest_distinguishes_import_kills_from_interrupts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """Exercise pytest's real collection exits after a passing baseline."""
    module = _load_mutate_module()
    source = _sandbox(module, tmp_path, monkeypatch)
    if failure == "dataclass-import":
        original = (
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\nclass Base:\n    pass\n"
            "@dataclass(frozen=True)\nclass Child(Base):\n    pass\n"
            "def test_instance():\n    assert isinstance(Child(), Base)\n"
        )
    elif failure == "collection-interrupt":
        original = (
            "ready = True\nif not ready:\n    raise KeyboardInterrupt\ndef test_ok():\n    pass\n"
        )
    else:
        original = (
            "ready = True\ndef test_ok():\n    if not ready:\n        raise KeyboardInterrupt\n"
        )
    source.write_text(original)
    mutant = next(
        m for m in module._enumerate_line_mutants(original) if "'True'->'False'" in m.label
    )
    monkeypatch.setattr(module, "_enumerate_line_mutants", lambda text: [mutant])
    monkeypatch.setattr(module, "_module_test_dirs", lambda: {"sample.py": ("sample.py",)})
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    monkeypatch.setenv("PYTEST_ADDOPTS", "")
    result = module._mutate_module(
        "sample.py",
        sandbox_root=tmp_path,
        python=Path(sys.executable),
        max_mutants=1,
        seed=42,
        verbose=0,
    )
    assert source.read_text() == original
    assert result.killed == int(failure == "dataclass-import")
    assert result.errors == int(failure != "dataclass-import")
    assert result.survived == 0


def _run_cli_with_exit_codes(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, codes: list[int], *argv: str
) -> int:
    _sandbox(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module,
        "_prepare_mutation_sandbox",
        lambda: (tmp_path, tmp_path, tmp_path / "python", lambda: None),
    )
    queue = iter(codes)
    monkeypatch.setattr(module, "_run_pytest", lambda *a, **kw: (next(queue), "out"))
    return int(module.main(["--module", "sample.py", "--max-mutants", "1", *argv]))


def test_survivors_are_listed_without_verbose_and_written_to_the_job_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """W3.3-3: a survivor must be readable, not just counted."""
    module = _load_mutate_module()
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    rc = _run_cli_with_exit_codes(module, tmp_path, monkeypatch, [0, 0])
    assert rc == 1  # 100% escape against the default 45% threshold
    out = capsys.readouterr().out
    assert "Surviving mutants" in out
    assert "sample.py L1" in out
    assert "result = True" in out
    text = summary.read_text(encoding="utf-8")
    assert "Mutation survivors" in text
    assert "sample.py L1" in text


def test_summary_says_so_when_nothing_survived(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_mutate_module()
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert _run_cli_with_exit_codes(module, tmp_path, monkeypatch, [0, 1]) == 0
    assert "No survivors." in summary.read_text(encoding="utf-8")


def test_a_module_over_its_own_limit_fails_even_when_the_overall_rate_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_mutate_module()
    monkeypatch.setattr(module, "_load_module_thresholds", lambda: {"sample.py": 10.0})
    rc = _run_cli_with_exit_codes(module, tmp_path, monkeypatch, [0, 0], "--threshold", "100")
    assert rc == 1
    assert "sample.py: escape rate 100.0%" in capsys.readouterr().err


def test_no_module_thresholds_flag_restores_the_overall_gate_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_mutate_module()
    monkeypatch.setattr(module, "_load_module_thresholds", lambda: {"sample.py": 10.0})
    rc = _run_cli_with_exit_codes(
        module, tmp_path, monkeypatch, [0, 0], "--threshold", "100", "--no-module-thresholds"
    )
    assert rc == 0


def test_the_approval_gate_has_a_module_limit_and_a_dedicated_test_file() -> None:
    module = _load_mutate_module()
    assert "agents/gates.py" in module._load_module_thresholds()
    targets = module._load_module_test_dirs()["agents/gates.py"]
    assert "tests/agents/test_gates_decision_contract.py" in targets
    assert (REPO_ROOT / "tests/agents/test_gates_decision_contract.py").is_file()
