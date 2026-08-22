"""Batch GF — shared ``tests/docs`` helpers (#405).

Pins D12: ``tests/docs/support.py`` exports ``git_ref_exists``,
``action_uses_pattern``, ``ci_steps``, and ``load_script_module`` for the
RV1-RV6 contract suite. W12 refactors the listed modules to import these
helpers (~80 lines deduped). Implementation lands in W12.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from types import ModuleType

import pytest

from tests.ci.workflow_support import REPO_ROOT
from tests.docs import support

_GEN_SCRIPT = REPO_ROOT / "scripts" / "gen_agent_packages.py"
_CHECK_CLI_SCRIPT = REPO_ROOT / "scripts" / "check_cli_examples.py"
_SAMPLE_ACTION_USES = """jobs:
  review:
    steps:
      - uses: alexhawat/mergeCraft@pre-0.0.1
      - uses: ALEXHAWAT/mergeCraft@v0.1.0a1
"""

# Issue #405 — modules W12 migrates to ``tests.docs.support``.
_MIGRATION_MODULES = (
    "tests.docs.test_landing_readme",
    "tests.docs.test_agent_surfaces",
    "tests.docs.test_docs_gate",
    "tests.docs.test_agent_packages",
    "tests.docs.test_docs_manifest",
    "tests.docs.test_cli_examples",
    "tests.docs.test_gen_agent_packages_blob_ref",
    "tests.docs.test_reference_docs",
)

_DOCS_TEST_MODULES = tuple(
    f"tests.docs.{path.stem}" for path in sorted((REPO_ROOT / "tests" / "docs").glob("test_*.py"))
)


@pytest.mark.parametrize("module_name", _DOCS_TEST_MODULES)
def test_docs_contract_modules_still_collect(module_name: str) -> None:
    """Every ``tests/docs/test_*.py`` module imports cleanly before the W12 refactor."""
    importlib.import_module(module_name)


def test_support_module_is_importable() -> None:
    assert support.__name__ == "tests.docs.support"


def test_support_exports_git_ref_exists() -> None:
    assert callable(support.git_ref_exists)
    assert support.git_ref_exists("pre-0.0.1") is True
    assert support.git_ref_exists("mergecraft-issue-405-nonexistent-ref") is False


def test_support_exports_action_uses_pattern() -> None:
    pattern = support.action_uses_pattern
    assert isinstance(pattern, re.Pattern)
    assert pattern.flags & re.IGNORECASE, "action_uses_pattern must be case-insensitive (D12)"
    lower = pattern.search("uses: alexhawat/mergeCraft@pre-0.0.1")
    assert lower is not None
    assert lower.group(1) == "pre-0.0.1"
    upper = pattern.search("uses: ALEXHAWAT/mergeCraft@v0.1.0a1")
    assert upper is not None
    assert upper.group(1) == "v0.1.0a1"
    assert pattern.findall(_SAMPLE_ACTION_USES) == ["pre-0.0.1", "v0.1.0a1"]


def test_support_exports_ci_steps() -> None:
    assert callable(support.ci_steps)
    steps = support.ci_steps()
    assert isinstance(steps, list)
    assert steps, "ci_steps() must return Makefile CI_STEPS tokens"
    assert "lint" in steps
    assert "docs-check" in steps
    assert "agent-packages-check" in steps


def test_support_exports_load_script_module() -> None:
    assert callable(support.load_script_module)
    gen: ModuleType = support.load_script_module(_GEN_SCRIPT)
    assert callable(getattr(gen, "main", None)), "gen_agent_packages.py must expose main()"
    cli = support.load_script_module(_CHECK_CLI_SCRIPT)
    assert callable(getattr(cli, "main", None)), "check_cli_examples.py must expose main()"


def test_load_script_module_accepts_relative_path() -> None:
    gen = support.load_script_module(Path("scripts/gen_agent_packages.py"))
    assert callable(getattr(gen, "main", None))


def test_git_ref_exists_fetches_shallow_checkout_sha(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mirror ``test_landing_readme`` shallow-checkout behaviour."""
    sha = "f" * 40
    calls: list[list[str]] = []
    rev_parse_attempts = 0

    def fake_run(cmd: list[str], **kwargs: object) -> object:
        nonlocal rev_parse_attempts
        calls.append(cmd)
        if cmd[:3] == ["git", "rev-parse", "--verify"] and len(cmd) > 3 and sha in cmd[3]:
            rev_parse_attempts += 1
            if rev_parse_attempts == 1:
                return type("R", (), {"returncode": 1})()
            return type("R", (), {"returncode": 0})()
        if cmd[:3] == ["git", "fetch", "origin"] and len(cmd) > 3 and cmd[3] == sha:
            return type("R", (), {"returncode": 0})()
        return type("R", (), {"returncode": 1})()

    monkeypatch.setattr("tests.docs.support.subprocess.run", fake_run)
    assert support.git_ref_exists(sha) is True
    assert any(cmd[:3] == ["git", "fetch", "origin"] for cmd in calls), (
        "git_ref_exists must fetch missing SHAs before re-verify (landing_readme contract)"
    )


@pytest.mark.parametrize("module_name", _MIGRATION_MODULES)
def test_migration_module_imports_shared_support(module_name: str) -> None:
    """W12 switches listed modules from local duplicates to ``tests.docs.support``."""
    mod = importlib.import_module(module_name)
    source = Path(mod.__file__).read_text(encoding="utf-8")
    assert (
        "from tests.docs import support" in source or "from tests.docs.support import" in source
    ), f"{module_name} must import shared helpers from tests.docs.support (#405)"
    assert "_git_ref_exists" not in source or "tests.docs.support" in source, (
        f"{module_name} must not keep a private _git_ref_exists after W12"
    )
    assert "_ci_steps" not in source or "tests.docs.support" in source, (
        f"{module_name} must not keep a private _ci_steps after W12"
    )
