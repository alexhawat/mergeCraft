"""Tests for mechanical review gates (discovery, planning, execution)."""

from __future__ import annotations

import shutil
import sys
from typing import TYPE_CHECKING

import pytest

from mergecraft.review_checks import (
    MAX_OUTPUT_CHARS,
    StaticCheck,
    StaticCheckConfig,
    discover_makefile_targets,
    plan_checks,
    run_checks,
)

if TYPE_CHECKING:
    from pathlib import Path

needs_make = pytest.mark.skipif(shutil.which("make") is None, reason="requires make on PATH")


def test_discover_makefile_targets_returns_gate_targets_in_order(tmp_path: Path) -> None:
    (tmp_path / "Makefile").write_text(
        "help:\n\t@echo hi\ntypecheck:\n\tmypy src\nlint:\n\truff check .\ntest:\n\tpytest\n",
        encoding="utf-8",
    )
    assert discover_makefile_targets(tmp_path) == ("lint", "typecheck")


def test_discover_makefile_targets_ignores_recipe_lines(tmp_path: Path) -> None:
    (tmp_path / "Makefile").write_text(
        "build:\n\tdocker build -t x:lint .\n# lint: commented out\n", encoding="utf-8"
    )
    assert discover_makefile_targets(tmp_path) == ()


def test_discover_makefile_targets_without_makefile(tmp_path: Path) -> None:
    assert discover_makefile_targets(tmp_path) == ()


@needs_make
def test_plan_checks_falls_back_to_makefile(tmp_path: Path) -> None:
    (tmp_path / "Makefile").write_text("lint:\n\truff check .\n", encoding="utf-8")
    assert plan_checks(root=tmp_path) == [StaticCheck(name="lint", argv=("make", "lint"))]


def test_plan_checks_skips_makefile_fallback_without_make(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Action image ships no make, so every discovered target would be unrunnable."""
    (tmp_path / "Makefile").write_text("lint:\n\truff check .\n", encoding="utf-8")
    monkeypatch.setattr("mergecraft.review_checks.shutil.which", lambda _: None)
    assert plan_checks(root=tmp_path) == []
    # A declared gate is still planned; availability is judged when it runs.
    assert plan_checks(
        root=tmp_path, configured=[StaticCheckConfig(name="lint", command="make lint")]
    ) == [StaticCheck(name="lint", argv=("make", "lint"))]


def test_plan_checks_prefers_declared_over_makefile(tmp_path: Path) -> None:
    (tmp_path / "Makefile").write_text("lint:\n\truff check .\n", encoding="utf-8")
    planned = plan_checks(
        root=tmp_path,
        configured=[StaticCheckConfig(name="custom", command="echo hi")],
    )
    assert planned == [StaticCheck(name="custom", argv=("echo", "hi"))]


def test_plan_checks_substitutes_files_token(tmp_path: Path) -> None:
    planned = plan_checks(
        root=tmp_path,
        configured=[StaticCheckConfig(name="lint", command="ruff check {files} --quiet")],
        changed_files=["src/a.py", "src/b.py"],
    )
    assert planned[0].argv == ("ruff", "check", "src/a.py", "src/b.py", "--quiet")


def test_plan_checks_drops_gate_with_no_matching_suffix(tmp_path: Path) -> None:
    configured = [
        StaticCheckConfig(name="py", command="ruff check {files}", suffixes=(".py",)),
        StaticCheckConfig(name="all", command="make lint"),
    ]
    planned = plan_checks(root=tmp_path, configured=configured, changed_files=["README.md"])
    assert [c.name for c in planned] == ["all"]


def test_plan_checks_drops_files_gate_when_nothing_changed(tmp_path: Path) -> None:
    planned = plan_checks(
        root=tmp_path,
        configured=[StaticCheckConfig(name="lint", command="ruff check {files}")],
        changed_files=[],
    )
    assert planned == []


def test_run_checks_reports_pass_and_failure(tmp_path: Path) -> None:
    outcomes = run_checks(
        [
            StaticCheck(name="ok", argv=(sys.executable, "-c", "print('fine')")),
            StaticCheck(name="bad", argv=(sys.executable, "-c", "raise SystemExit(3)")),
        ],
        root=tmp_path,
    )
    assert [o.name for o in outcomes] == ["ok", "bad"]
    assert outcomes[0].status == "passed"
    assert outcomes[0].passed is True
    assert "fine" in outcomes[0].output
    assert outcomes[1].status == "failed"
    assert outcomes[1].exit_code == 3
    assert all(o.ran for o in outcomes)


def test_missing_executable_is_unavailable_not_failed(tmp_path: Path) -> None:
    """An uninstalled linter says nothing about the diff, so it must not read as a failure."""
    outcomes = run_checks(
        [StaticCheck(name="missing", argv=("mergecraft-no-such-binary",))], root=tmp_path
    )
    assert outcomes[0].status == "unavailable"
    assert outcomes[0].ran is False
    assert outcomes[0].passed is False
    assert outcomes[0].exit_code is None
    assert "not installed" in outcomes[0].output


def test_run_checks_truncates_long_output(tmp_path: Path) -> None:
    outcomes = run_checks(
        [
            StaticCheck(
                name="loud",
                argv=(sys.executable, "-c", f"print('x' * {MAX_OUTPUT_CHARS * 2})"),
            )
        ],
        root=tmp_path,
    )
    assert "truncated" in outcomes[0].output
    assert len(outcomes[0].output) < MAX_OUTPUT_CHARS * 2
