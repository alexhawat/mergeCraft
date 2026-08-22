"""Batch HF RED — called-workflow permissions lint (#425).

Pins that ``make lint`` rejects a caller job whose ``uses:`` target is a local
reusable workflow declaring ``permissions:`` the caller does not hold. The
#424 ``ci-cd.yml`` ``e2e-gate`` incident is the regression anchor: top-level
``permissions: {}`` plus a job with no scopes calling ``e2e.yml`` (which
declares ``contents: read``) produced ``startup_failure`` with no logs.

Implementation lands in W12 via ``scripts/check_called_workflow_permissions.py``
wired into ``make lint`` (D5). Branch-protection documentation is operator-only.
"""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.ci.workflow_support import REPO_ROOT, job, load_workflow

_CHECKER_SCRIPT = REPO_ROOT / "scripts" / "check_called_workflow_permissions.py"
_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "workflow_permissions_hf"
_W12_XFAIL = pytest.mark.xfail(
    reason="green after W12: called-workflow permissions lint (#425)",
    strict=False,
)


def _load_checker() -> Any:
    assert _CHECKER_SCRIPT.is_file(), (
        f"{_CHECKER_SCRIPT.relative_to(REPO_ROOT)} missing — W12 adds the hygiene script"
    )
    spec = importlib.util.spec_from_file_location(
        "check_called_workflow_permissions", _CHECKER_SCRIPT
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _install_hf_fixtures(tmp_path: Path) -> Path:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    for src in sorted(_FIXTURES_DIR.glob("*.yml")):
        shutil.copyfile(src, workflows / src.name)
    return workflows


def _load_fixture_workflow(name: str) -> dict[str, Any]:
    path = _FIXTURES_DIR / name
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), f"{name} did not parse as a mapping"
    return loaded


class TestFixtureAnchors:
    """Sanity: fixtures model the #424/#425 permissions relationship without the linter."""

    def test_bad_fixture_job_permissions_are_empty(self) -> None:
        gate = job(_load_fixture_workflow("caller_empty_permissions.yml"), "gate")
        assert gate.get("permissions") == {}

    def test_bad_fixture_calls_local_reusable_workflow(self) -> None:
        gate = job(_load_fixture_workflow("caller_empty_permissions.yml"), "gate")
        uses = gate.get("uses")
        assert isinstance(uses, str)
        assert uses.endswith("callee_contents_read.yml")

    def test_callee_declares_contents_read(self) -> None:
        callee = _load_fixture_workflow("callee_contents_read.yml")
        assert callee.get("permissions") == {"contents": "read"}

    def test_sufficient_fixture_grants_contents_read(self) -> None:
        gate = job(_load_fixture_workflow("caller_sufficient_permissions.yml"), "gate")
        permissions = gate.get("permissions")
        assert isinstance(permissions, dict)
        assert permissions.get("contents") == "read"

    def test_inherit_fixture_has_workflow_level_contents_read(self) -> None:
        caller = _load_fixture_workflow("caller_inherits_workflow_level.yml")
        assert caller.get("permissions") == {"contents": "read"}
        gate = job(caller, "gate")
        assert "permissions" not in gate


class TestScanCalledWorkflowPermissions:
    """Unit coverage for ``scripts/check_called_workflow_permissions.py``."""

    @_W12_XFAIL
    def test_empty_job_permissions_fail_when_callee_needs_contents_read(
        self, tmp_path: Path
    ) -> None:
        module = _load_checker()
        _install_hf_fixtures(tmp_path)
        offenses = module.scan_workflows(tmp_path)
        assert offenses, "caller_empty_permissions.yml must be flagged (#425)"

    @_W12_XFAIL
    def test_offense_names_caller_job_and_missing_scope(self, tmp_path: Path) -> None:
        module = _load_checker()
        _install_hf_fixtures(tmp_path)
        offenses = module.scan_workflows(tmp_path)
        assert len(offenses) == 1
        offense = offenses[0]
        assert offense.job == "gate"
        assert offense.workflow.endswith("caller_empty_permissions.yml")
        assert offense.missing == {"contents": "read"}

    @_W12_XFAIL
    def test_sufficient_job_permissions_pass(self, tmp_path: Path) -> None:
        module = _load_checker()
        workflows = _install_hf_fixtures(tmp_path)
        (workflows / "caller_empty_permissions.yml").unlink()
        (workflows / "caller_partial_permissions.yml").unlink()
        offenses = module.scan_workflows(tmp_path)
        assert offenses == []

    @_W12_XFAIL
    def test_workflow_level_permissions_satisfy_callee(self, tmp_path: Path) -> None:
        module = _load_checker()
        workflows = _install_hf_fixtures(tmp_path)
        for name in (
            "caller_empty_permissions.yml",
            "caller_sufficient_permissions.yml",
            "caller_partial_permissions.yml",
        ):
            (workflows / name).unlink()
        offenses = module.scan_workflows(tmp_path)
        assert offenses == []

    @_W12_XFAIL
    def test_partial_job_permissions_fail_when_callee_needs_more(self, tmp_path: Path) -> None:
        module = _load_checker()
        workflows = _install_hf_fixtures(tmp_path)
        (workflows / "caller_empty_permissions.yml").unlink()
        offenses = module.scan_workflows(tmp_path)
        assert len(offenses) == 1
        assert offenses[0].missing == {"packages": "read"}

    @_W12_XFAIL
    def test_third_party_uses_are_out_of_scope(self, tmp_path: Path) -> None:
        module = _load_checker()
        workflows = _install_hf_fixtures(tmp_path)
        for path in workflows.glob("*.yml"):
            path.unlink()
        (workflows / "third_party_only.yml").write_text(
            "name: third party\n"
            "on: workflow_dispatch\n"
            "permissions: {}\n"
            "jobs:\n"
            "  checkout:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - uses: actions/checkout@0000000000000000000000000000000000000000\n",
            encoding="utf-8",
        )
        offenses = module.scan_workflows(tmp_path)
        assert offenses == []


class TestMain:
    """CLI orchestration for the hygiene script."""

    @_W12_XFAIL
    def test_main_fails_on_under_permissioned_uses_job(self, tmp_path: Path) -> None:
        module = _load_checker()
        _install_hf_fixtures(tmp_path)
        module.REPO = tmp_path
        assert module.main() != 0

    @_W12_XFAIL
    def test_main_passes_when_only_good_fixtures_remain(self, tmp_path: Path) -> None:
        module = _load_checker()
        workflows = _install_hf_fixtures(tmp_path)
        (workflows / "caller_empty_permissions.yml").unlink()
        (workflows / "caller_partial_permissions.yml").unlink()
        module.REPO = tmp_path
        assert module.main() == 0


class TestRepoWorkflows:
    """Integration: the real tree must pass once W12 lands (post-#424 fix)."""

    @_W12_XFAIL
    def test_repo_workflows_pass_called_workflow_permissions_lint(self) -> None:
        module = _load_checker()
        offenses = module.scan_workflows(REPO_ROOT)
        assert offenses == []

    def test_e2e_gate_job_grants_contents_read(self) -> None:
        """Regression anchor for #424 — do not re-break while adding the linter."""
        gate = job(load_workflow("ci-cd.yml"), "e2e-gate")
        permissions = gate.get("permissions")
        assert isinstance(permissions, dict)
        assert permissions.get("contents") == "read"


class TestMakeLintWiring:
    """``make lint`` must invoke the new guard (D5 part 1)."""

    @_W12_XFAIL
    def test_makefile_lint_invokes_called_workflow_permissions_check(self) -> None:
        makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
        assert "check_called_workflow_permissions" in makefile


__all__ = [
    "TestFixtureAnchors",
    "TestMain",
    "TestMakeLintWiring",
    "TestRepoWorkflows",
    "TestScanCalledWorkflowPermissions",
]
