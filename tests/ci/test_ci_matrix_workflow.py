"""W3.2-1 — the macOS / Python 3.12-3.13 / optional-extras matrix stays outside the required graph."""

from __future__ import annotations

import re
import shlex
import subprocess
from typing import TYPE_CHECKING, Any

import pytest

from tests.ci.workflow_support import REPO_ROOT, job, load_workflow, workflow_on

if TYPE_CHECKING:
    from pathlib import Path

_MATRIX = "ci-matrix.yml"
_REQUIRED = [
    line.strip()
    for line in (REPO_ROOT / "scripts" / "ci_required_verify_checks.txt")
    .read_text(encoding="utf-8")
    .splitlines()
    if line.strip() and not line.startswith("#")
]
_NEW_JOBS = ["compat-smoke", "compat-unit", "extras", "macos-unit"]


def _matrix_values(doc: dict[str, Any], job_id: str, key: str) -> list[str]:
    return [str(v) for v in job(doc, job_id)["strategy"]["matrix"][key]]


def test_the_matrix_covers_the_advertised_interpreters_macos_and_the_extras() -> None:
    doc = load_workflow(_MATRIX)
    assert _matrix_values(doc, "compat-smoke", "python") == ["3.12", "3.13"]
    assert _matrix_values(doc, "compat-unit", "python") == ["3.12", "3.13"]
    assert job(doc, "macos-unit")["runs-on"] == "macos-latest"
    extras = job(doc, "extras")
    setup = next(s for s in extras["steps"] if s.get("uses") == "./.github/actions/bootstrap")
    assert "agents" in setup["env"]["MERGECRAFT_UV_EXTRAS"]
    assert "harbor" in setup["env"]["MERGECRAFT_UV_EXTRAS"]


def test_the_classifiers_the_package_advertises_are_the_ones_the_matrix_runs() -> None:
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for version in ("3.12", "3.13"):
        assert f"Programming Language :: Python :: {version}" in pyproject


@pytest.mark.parametrize("job_id", _NEW_JOBS)
def test_no_new_job_name_collides_with_a_required_check(job_id: str) -> None:
    name = str(job(load_workflow(_MATRIX), job_id)["name"])
    rendered = re.sub(r"\$\{\{[^}]*\}\}", "X", name)
    assert not rendered.startswith("Verify"), "the Verify prefix is reserved for required checks"
    assert all(rendered != re.sub(r"\$\{\{[^}]*\}\}", "X", req) for req in _REQUIRED)


def test_required_check_names_and_jobs_in_ci_yml_are_untouched() -> None:
    ci = load_workflow("ci.yml")
    names = {str(j.get("name")) for j in ci["jobs"].values() if isinstance(j, dict)}
    for expected in (
        "Verify (static + build py${{ matrix.python }})",
        "Verify (tests py${{ matrix.python }} ${{ matrix.group }}/2)",
        "Verify (security audit py${{ matrix.python }})",
        "Verify (coverage gate py3.14)",
    ):
        assert expected in names


def test_the_required_graph_does_not_wait_on_the_matrix() -> None:
    ci = load_workflow("ci.yml")
    needs = {str(n) for j in ci["jobs"].values() for n in _as_list(j.get("needs"))}
    assert needs.isdisjoint(_NEW_JOBS), "a required job must not depend on the matrix"
    assert "ci-matrix" not in (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")


def _as_list(value: object) -> list[object]:
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]


@pytest.mark.parametrize("job_id", _NEW_JOBS)
def test_every_matrix_job_is_bounded_and_does_not_persist_credentials(job_id: str) -> None:
    body = job(load_workflow(_MATRIX), job_id)
    assert 0 < int(body["timeout-minutes"]) <= 45
    for step in body["steps"]:
        if str(step.get("uses", "")).startswith("actions/checkout@"):
            assert step["with"]["persist-credentials"] is False


def test_heavy_legs_run_on_main_nightly_and_on_prs_that_change_platform_support() -> None:
    doc = load_workflow(_MATRIX)
    on = workflow_on(doc)
    assert "schedule" in on
    assert "push" in on
    for job_id in ("compat-unit", "macos-unit"):
        body = job(doc, job_id)
        assert body["needs"] == "scope"
        assert body["if"] == "needs.scope.outputs.full == 'true'"
    scope = next(s for s in job(doc, "scope")["steps"] if s.get("id") == "scope")
    for trigger in ("ci-matrix", "bootstrap", "Makefile", "pyproject", "uv"):
        assert trigger in scope["run"], f"{trigger} must make a PR run the full matrix"


def test_default_token_is_read_only() -> None:
    assert load_workflow(_MATRIX)["permissions"] == {"contents": "read"}


# -- matrix known-failures list --------------------------------------------------------


def _known_failures() -> list[str]:
    text = (REPO_ROOT / ".github" / "matrix-known-failures.txt").read_text(encoding="utf-8")
    return [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]


def test_the_macos_debt_list_names_only_tests_that_still_exist() -> None:
    for node in _known_failures():
        path, _, test = node.partition("::")
        source = REPO_ROOT / path
        assert source.is_file(), f"{node}: file is gone, delete the line"
        assert re.search(rf"def {re.escape(test.split('[')[0])}\b", source.read_text("utf-8")), (
            f"{node}: test no longer exists, delete the line"
        )


@pytest.mark.parametrize("job_id", ["compat-unit", "macos-unit"])
def test_every_unit_leg_deselects_the_debt_list_through_pytest_addopts(job_id: str) -> None:
    step = next(
        s
        for s in job(load_workflow(_MATRIX), job_id)["steps"]
        if str(s.get("name", "")).startswith("Unit tests")
    )
    assert "scripts/ci_known_failures_addopts.sh .github/matrix-known-failures.txt" in step["run"]
    assert "PYTEST_ADDOPTS" in step["run"]


def test_the_addopts_helper_emits_one_quoted_deselect_per_node(tmp_path: Path) -> None:
    listing = tmp_path / "known.txt"
    listing.write_text(
        "# comment\n\ntests/a.py::test_one\ntests/b.py::test_two[x y]\n", encoding="utf-8"
    )
    out = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "ci_known_failures_addopts.sh"), str(listing)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert shlex.split(out) == [
        "--deselect",
        "tests/a.py::test_one",
        "--deselect",
        "tests/b.py::test_two[x y]",
    ]


# -- the cache a PR seeds must never hold head coverage under the base key (CIR-F7) ----


def test_integration_never_saves_workspace_coverage_under_the_base_sha_key() -> None:
    steps = job(load_workflow("integration.yml"), "integration-pr")["steps"]
    for step in steps:
        uses = str(step.get("uses", ""))
        key = str((step.get("with") or {}).get("key", ""))
        saves = uses.startswith("actions/cache/save") or (
            uses.startswith("actions/cache@") and "path" in (step.get("with") or {})
        )
        assert not (saves and "coverage-main" in key), (
            "a PR run must not seed mergecraft-coverage-main-<base sha> from its own coverage.json"
        )
