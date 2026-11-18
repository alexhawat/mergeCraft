"""PR-tier pytest selection helper (#1493)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from tests.ci.workflow_support import REPO_ROOT, as_list, job, load_workflow


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
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module, "_changed_files", lambda _base: changed)
    monkeypatch.setattr(sys, "argv", ["ci_select_tests.py"])
    assert module.main() == 0
    return capsys.readouterr().out.strip()


def test_tests_for_path_maps_src_tests_and_ci_touchpoints() -> None:
    module = _module()
    assert module._tests_for_path("src/mergecraft/review/budget_trend.py") == {
        "tests/review/test_budget_trend.py"
    }
    assert module._tests_for_path("tests/review/test_budget_trend.py") == {
        "tests/review/test_budget_trend.py"
    }
    for touchpoint in (".github/workflows/ci.yml", "Makefile"):
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


def test_main_selects_the_mapped_test_and_the_anchor(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    selected = _select(
        monkeypatch,
        capsys,
        tmp_path,
        changed=["src/mergecraft/review/budget_trend.py"],
        present=["tests/review/test_budget_trend.py", "tests/ci/test_ci_select_tests.py"],
    )
    assert selected == "tests/ci/test_ci_select_tests.py tests/review/test_budget_trend.py"


def test_a_workflow_only_change_narrows_to_the_ci_contract_tests(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    selected = _select(
        monkeypatch,
        capsys,
        tmp_path,
        changed=[".github/workflows/ci.yml", "Makefile"],
        present=["tests/ci/test_ci_select_tests.py"],
    )
    assert selected == "tests/ci tests/ci/test_ci_select_tests.py"


@pytest.mark.parametrize(
    "changed",
    [
        ["uv.lock", "src/mergecraft/review/budget_trend.py"],
        ["pyproject.toml", "tests/review/test_budget_trend.py"],
        ["scripts/gen_docs.py"],
        ["src/mergecraft/review/has_no_same_named_test.py"],
        [],
    ],
    ids=["lockfile", "pyproject", "scripts-only", "src-without-test", "no-changes"],
)
def test_main_runs_everything_when_the_change_cannot_be_narrowed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    changed: list[str],
) -> None:
    """A dependency change, or nothing that maps to an existing test, is not narrowed."""
    selected = _select(
        monkeypatch,
        capsys,
        tmp_path,
        changed=changed,
        present=["tests/review/test_budget_trend.py", "tests/ci/test_ci_select_tests.py"],
    )
    assert selected == "tests"


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
    assert selected == "tests/review/test_kept.py"


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


def test_the_required_shards_still_run_the_whole_unit_lane() -> None:
    """The selection is an extra early signal; it must not narrow a required check."""
    ci = load_workflow("ci.yml")
    steps = job(ci, "test")["steps"]
    shard = next(step for step in steps if str(step.get("name", "")).startswith("Unit tests"))
    assert shard["run"] == "make test"
    assert "MERGECRAFT_TEST_NODES" not in shard["env"]
    assert all("ci_select_tests" not in str(step.get("run", "")) for step in steps)
    assert "changed-tests" not in as_list(job(ci, "static")["needs"])


def test_the_selection_reaches_pytest_as_data_through_make_test() -> None:
    """Changed file names must never be spliced into a shell script."""
    fast = job(load_workflow("ci.yml"), "changed-tests")
    assert "github.event_name == 'pull_request'" in fast["if"]
    run = next(step for step in fast["steps"] if step.get("name") == "Changed tests")
    assert run["run"] == "make test", "keeps make test's markers, xdist and seed"
    assert run["env"]["MERGECRAFT_TEST_NODES"] == "${{ steps.pr_tests.outputs.nodes }}"
    assert run["if"] == "steps.pr_tests.outputs.nodes != 'tests'", (
        "an un-narrowed selection would repeat the whole lane the shards already run"
    )
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "$(PYTEST) $${MERGECRAFT_TEST_NODES:-tests} " in makefile
