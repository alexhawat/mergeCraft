"""PR-tier pytest selection helper (#1493)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from tests.ci.workflow_support import REPO_ROOT, job, load_workflow


def _module() -> ModuleType:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import ci_select_tests as module

    return module


def _select(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    *,
    changed: list[str],
    present: list[str],
) -> str:
    """Run the selector in a scratch tree where only ``present`` paths exist."""
    module = _module()
    for name in present:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    (tmp_path / "tests" / "ci").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "conftest.py").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module, "_changed_files", lambda _base: changed)
    monkeypatch.setattr(sys, "argv", ["ci_select_tests.py"])
    assert module.main() == 0
    return capsys.readouterr().out.strip()


def test_tests_for_path_maps_src_and_ci_touchpoints() -> None:
    module = _module()
    assert module._tests_for_path("src/mergecraft/review/budget_trend.py") == {
        "tests/review/test_budget_trend.py"
    }
    assert module._tests_for_path("tests/review/test_budget_trend.py") == {
        "tests/review/test_budget_trend.py"
    }
    for touchpoint in (".github/workflows/ci.yml", "Makefile", "pyproject.toml", "uv.lock"):
        assert module._tests_for_path(touchpoint) == {"tests/ci"}
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


def test_main_selects_the_mapped_test_beside_the_always_on_seeds(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    selected = _select(
        monkeypatch,
        capsys,
        tmp_path,
        changed=["src/mergecraft/review/budget_trend.py"],
        present=["tests/review/test_budget_trend.py"],
    )
    assert selected == "tests/ci tests/conftest.py tests/review/test_budget_trend.py"


@pytest.mark.parametrize(
    "changed",
    [
        ["uv.lock"],
        ["scripts/gen_docs.py"],
        ["src/mergecraft/review/has_no_same_named_test.py"],
    ],
    ids=["dependency-bump", "scripts-only", "src-without-test"],
)
def test_main_runs_everything_when_the_change_cannot_be_narrowed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    changed: list[str],
) -> None:
    """Only the seeds survive, so the shards must fall back to the full tree."""
    assert _select(monkeypatch, capsys, tmp_path, changed=changed, present=[]) == "tests"


def test_main_drops_selected_nodes_that_do_not_exist(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    selected = _select(
        monkeypatch,
        capsys,
        tmp_path,
        changed=["src/mergecraft/review/kept.py", "tests/review/test_deleted.py"],
        present=["tests/review/test_kept.py"],
    )
    assert selected == "tests/ci tests/conftest.py tests/review/test_kept.py"


def test_main_runs_everything_when_a_selected_path_has_whitespace(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """A space-separated list cannot carry such a path as one node."""
    selected = _select(
        monkeypatch,
        capsys,
        tmp_path,
        changed=["tests/review/test_a b.py"],
        present=["tests/review/test_a b.py"],
    )
    assert selected == "tests"


def test_the_selection_reaches_pytest_as_data_through_make_test() -> None:
    """Changed file names must never be spliced into the shard's shell script."""
    steps = job(load_workflow("ci.yml"), "test")["steps"]
    shard = next(step for step in steps if str(step.get("name", "")).startswith("Unit tests"))
    assert shard["run"] == "make test", "the PR lane keeps make test's markers, xdist and seed"
    assert shard["env"]["MERGECRAFT_TEST_NODES"] == "${{ steps.pr_tests.outputs.nodes }}"
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "$(PYTEST) $${MERGECRAFT_TEST_NODES:-tests} " in makefile
