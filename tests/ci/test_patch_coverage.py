"""W3.3-1 — the patch coverage gate fails a PR whose new lines are not exercised."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING, Any

import pytest

from tests.ci.workflow_support import REPO_ROOT, job, load_workflow

if TYPE_CHECKING:
    from pathlib import Path

_SCRIPT = REPO_ROOT / "scripts" / "check_patch_coverage.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("check_patch_coverage_under_test", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_DIFF = """\
diff --git a/src/mergecraft/a.py b/src/mergecraft/a.py
index 111..222 100644
--- a/src/mergecraft/a.py
+++ b/src/mergecraft/a.py
@@ -3,0 +4,3 @@ def f():
+x = 1
+y = 2
+z = 3
@@ -10 +13 @@ def g():
-old
+new
@@ -20,2 +22,0 @@ def h():
-gone
-gone too
diff --git a/src/mergecraft/new.py b/src/mergecraft/new.py
new file mode 100644
--- /dev/null
+++ b/src/mergecraft/new.py
@@ -0,0 +1,2 @@
+a = 1
+b = 2
diff --git a/tests/test_a.py b/tests/test_a.py
--- a/tests/test_a.py
+++ b/tests/test_a.py
@@ -1 +1 @@
-a
+b
diff --git a/src/mergecraft/gone.py b/src/mergecraft/gone.py
deleted file mode 100644
--- a/src/mergecraft/gone.py
+++ /dev/null
@@ -1,2 +0,0 @@
-a
-b
"""


def test_parse_changed_lines_reads_new_side_ranges_and_skips_deletions_and_tests() -> None:
    changed = _load().parse_changed_lines(_DIFF)
    assert changed == {
        "src/mergecraft/a.py": {4, 5, 6, 13},
        "src/mergecraft/new.py": {1, 2},
    }


def _report(**files: dict[str, list[int]]) -> dict[str, Any]:
    return {"files": {f"src/mergecraft/{name}.py": entry for name, entry in files.items()}}


def test_only_executable_changed_lines_count_toward_the_percentage() -> None:
    module = _load()
    changed = {"src/mergecraft/a.py": {4, 5, 6, 7}}
    # 7 is a comment: in neither list, so it is neither covered nor missing.
    report = _report(a={"executed_lines": [4, 5, 6], "missing_lines": []})
    result = module.evaluate(changed, report)
    assert (result.executable, result.covered, result.percent) == (3, 3, 100.0)


def test_uncovered_lines_are_reported_per_file() -> None:
    module = _load()
    changed = {"src/mergecraft/a.py": {1, 2, 3, 4}}
    report = _report(a={"executed_lines": [1], "missing_lines": [2, 3, 4]})
    result = module.evaluate(changed, report)
    assert result.percent == 25.0
    assert result.uncovered == {"src/mergecraft/a.py": [2, 3, 4]}


def test_a_changed_file_with_no_coverage_data_is_skipped_not_failed() -> None:
    """(c) A file the coverage config omits has no entry: it must not fail the gate."""
    module = _load()
    result = module.evaluate({"src/mergecraft/new.py": {1, 2}}, {"files": {}})
    assert (result.executable, result.covered, result.percent) == (0, 0, 100.0)
    assert result.skipped == ("src/mergecraft/new.py",)


def test_lines_excluded_by_pragma_or_config_never_count() -> None:
    """(b) Excluded lines sit in ``excluded_lines``, not in executed or missing."""
    module = _load()
    changed = {"src/mergecraft/a.py": {1, 2, 3}}
    report = _report(a={"executed_lines": [1], "missing_lines": [], "excluded_lines": [2, 3]})
    result = module.evaluate(changed, report)
    assert (result.executable, result.covered, result.percent) == (1, 1, 100.0)


def test_report_keys_with_a_different_root_still_match() -> None:
    module = _load()
    report = {"files": {"/runner/work/mergecraft/src/mergecraft/a.py": {"executed_lines": [1]}}}
    result = module.evaluate({"src/mergecraft/a.py": {1}}, report)
    assert result.covered == 1


def test_ranges_collapse_consecutive_lines() -> None:
    assert _load()._ranges([3, 4, 5, 9, 11, 12]) == "3-5, 9, 11-12"


# -- end to end against a real repository ---------------------------------------------


def _git(cwd: Path, *args: str) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }
    subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True)


def _repo_with_new_lines(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    module = repo / "src" / "mergecraft" / "a.py"
    module.parent.mkdir(parents=True)
    module.write_text("def f():\n    return 1\n", encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "topic")
    module.write_text(
        "def f():\n    return 1\n\n\ndef g(x):\n    if x:\n        return 2\n    return 3\n",
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add g")
    return repo


def _run(repo: Path, report: dict[str, Any], *extra: str) -> subprocess.CompletedProcess[str]:
    coverage = repo / "coverage.json"
    coverage.write_text(json.dumps(report), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(_SCRIPT), str(coverage), "--base", "main", *extra],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_fails_when_new_lines_are_untested(tmp_path: Path) -> None:
    repo = _repo_with_new_lines(tmp_path)
    report = _report(a={"executed_lines": [1, 2, 5], "missing_lines": [6, 7, 8]})
    result = _run(repo, report)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "patch coverage 25.0%" in result.stderr
    assert "src/mergecraft/a.py: uncovered lines 6-8" in result.stderr


def test_cli_passes_when_new_lines_are_covered(tmp_path: Path) -> None:
    repo = _repo_with_new_lines(tmp_path)
    report = _report(a={"executed_lines": [1, 2, 5, 6, 7, 8], "missing_lines": []})
    result = _run(repo, report)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "meets 80%" in result.stdout


def test_threshold_is_adjustable(tmp_path: Path) -> None:
    repo = _repo_with_new_lines(tmp_path)
    report = _report(a={"executed_lines": [1, 2, 5, 6], "missing_lines": [7, 8]})
    assert _run(repo, report).returncode == 1
    assert _run(repo, report, "--threshold", "50").returncode == 0


def test_cli_passes_when_the_diff_touches_no_source(tmp_path: Path) -> None:
    repo = _repo_with_new_lines(tmp_path)
    (repo / "README.md").write_text("docs\n", encoding="utf-8")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "checkout", "-q", "-b", "docs-only")
    (repo / "README.md").write_text("docs\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "docs")
    result = _run(repo, {"files": {}})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "adds no executable lines" in result.stdout


def test_cli_reports_a_missing_report_as_an_error(tmp_path: Path) -> None:
    repo = _repo_with_new_lines(tmp_path)
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), str(repo / "nope.json"), "--base", "main"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "patch coverage error" in result.stderr


# -- wiring ---------------------------------------------------------------------------


def test_the_required_coverage_gate_runs_the_patch_and_delta_checks_on_pull_requests() -> None:
    steps = job(load_workflow("ci.yml"), "coverage-gate")["steps"]
    by_name = {s.get("name"): s for s in steps}
    patch = by_name["Patch coverage (changed src lines)"]
    assert "scripts/check_patch_coverage.py" in patch["run"]
    assert "pull_request" in patch["if"]
    delta = by_name["Coverage delta vs main"]
    assert "scripts/check_coverage_delta.py" in delta["run"]
    assert "pull_request" in delta["if"]


@pytest.mark.parametrize("name", ["Patch coverage (changed src lines)", "Coverage delta vs main"])
def test_the_new_gates_run_after_the_coverage_run_and_the_artifact_upload(name: str) -> None:
    """The head artifact is published first, so a failed gate never starves Integration."""
    names = [s.get("name") for s in job(load_workflow("ci.yml"), "coverage-gate")["steps"]]
    assert names.index("Coverage floors and ratchet") < names.index(name)
    assert names.index("Upload coverage.json for integration delta reuse") < names.index(name)


def test_the_coverage_gate_may_list_workflow_runs_but_nothing_else() -> None:
    permissions = job(load_workflow("ci.yml"), "coverage-gate")["permissions"]
    assert permissions == {"contents": "read", "actions": "read"}


def test_the_delta_step_skips_without_a_baseline_instead_of_failing_the_required_check() -> None:
    steps = job(load_workflow("ci.yml"), "coverage-gate")["steps"]
    delta = next(s for s in steps if s.get("name") == "Coverage delta vs main")
    assert "Coverage delta skipped" in delta["run"]
    assert delta["env"]["MERGECRAFT_COVERAGE_ARTIFACT_REQUIRE_SUCCESS"] == "1"
    assert delta["env"]["MERGECRAFT_COVERAGE_ARTIFACT_BRANCH"] == "${{ github.base_ref }}"


def test_cli_passes_when_a_changed_file_has_no_coverage_data(tmp_path: Path) -> None:
    repo = _repo_with_new_lines(tmp_path)
    result = _run(repo, {"files": {}})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "no coverage data for src/mergecraft/a.py" in result.stdout


def test_cli_passes_when_the_pr_changes_only_tests(tmp_path: Path) -> None:
    """(a) A code PR with no changed src lines has nothing to cover."""
    repo = _repo_with_new_lines(tmp_path)
    _git(repo, "checkout", "-q", "main")
    _git(repo, "checkout", "-q", "-b", "tests-only")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "tests")
    result = _run(repo, {"files": {}})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "adds no executable lines" in result.stdout
