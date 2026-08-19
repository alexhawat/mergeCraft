"""xpass ratchet tests (#276).

``scripts/check_xpass.py`` provides the shared D6 exclusion list and
``check_xpass`` helper. The live gate runs inside the pytest session via the
``tests/conftest.py`` ``pytest_sessionfinish`` hook.
"""

from __future__ import annotations

import importlib.util
import io
import re
from pathlib import Path
from typing import Any

import pytest

from tests.ci.workflow_support import REPO_ROOT, read_text


def _load_check_xpass() -> Any:
    path = REPO_ROOT / "scripts" / "check_xpass.py"
    assert path.is_file(), "scripts/check_xpass.py missing"
    spec = importlib.util.spec_from_file_location("check_xpass", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_script_exists() -> None:
    assert (REPO_ROOT / "scripts" / "check_xpass.py").is_file()


def test_d6_paths_cover_plan_test_files() -> None:
    module = _load_check_xpass()
    expected = {
        "tests/agents/test_codex_custom_provider.py",
        "tests/analyzers/test_scope.py",
        "tests/cli/test_auth_logfire_cmd.py",
        "tests/cli/test_gha_cmd.py",
        "tests/cli/test_gha_failure_outputs.py",
        "tests/evals/test_live_context.py",
        "tests/mcp/test_check_runs.py",
        "tests/mcp/test_git_tool.py",
        "tests/mcp/test_labels.py",
        "tests/mcp/test_submit_review_verdict.py",
        "tests/mcp/test_upload.py",
        "tests/review/test_terminal_verdict_policy.py",
    }
    assert expected <= set(module.D6_TEST_PATHS)


@pytest.mark.parametrize(
    ("nodeid", "d6"),
    [
        ("tests/agents/test_codex_custom_provider.py::test_foo", True),
        (
            "tests/agents/test_codex_custom_provider.py::test_foo[set_indexed0]",
            True,
        ),
        ("tests/mcp/test_upload.py::test_bar", True),
        ("tests/evidence/test_gate_actions.py::test_new_gates_default_to_shadow", False),
        ("tests/agents/test_minimax_routing.py::test_minimax_routes_via_opencode", False),
    ],
)
def test_is_d6_nodeid(nodeid: str, d6: bool) -> None:
    module = _load_check_xpass()
    assert module.is_d6_nodeid(nodeid) is d6


def test_parse_xpass_log_splits_d6_and_allowed() -> None:
    module = _load_check_xpass()
    log = """\
XPASS tests/agents/test_codex_custom_provider.py::test_codex_indexed_wins_singleton_ignored - green after W3
XPASS tests/evidence/test_gate_actions.py::test_new_gates_default_to_shadow - green after W9/W10
XPASS tests/cli/test_models_list_minimax.py::test_mergecraft_models_list_renders_minimax_row_with_credentials - green after W6
2989 passed, 30 skipped, 13 xfailed, 121 xpassed, 10 warnings in 156.09s
"""
    inventory = module.parse_xpass_log(log)
    assert inventory.total == 3
    assert inventory.d6_count == 1
    assert inventory.allowed_count == 2
    assert [r.nodeid for r in inventory.allowed_records] == [
        "tests/evidence/test_gate_actions.py::test_new_gates_default_to_shadow",
        "tests/cli/test_models_list_minimax.py::test_mergecraft_models_list_renders_minimax_row_with_credentials",
    ]


def test_parse_xpass_log_empty_is_zero() -> None:
    module = _load_check_xpass()
    inventory = module.parse_xpass_log("2989 passed, 30 skipped in 1.00s\n")
    assert inventory.total == 0
    assert inventory.allowed_count == 0
    assert inventory.d6_count == 0


def test_check_xpass_fails_on_allowed_tree() -> None:
    module = _load_check_xpass()
    inventory = module.parse_xpass_log(
        "XPASS tests/evidence/test_gate_actions.py::test_shadow_mode - leftover\n"
    )
    buf = io.StringIO()
    rc = module.check_xpass(inventory, stream=buf)
    assert rc == 1
    text = buf.getvalue()
    assert "xpass-check FAILED" in text
    assert "1 allowed-tree xpassed" in text
    assert "tests/evidence/test_gate_actions.py::test_shadow_mode" in text


def test_check_xpass_ok_when_only_d6_xpasses() -> None:
    module = _load_check_xpass()
    inventory = module.parse_xpass_log(
        "XPASS tests/agents/test_codex_custom_provider.py::test_codex_config_toml_writes_both_indexed_providers - D6\n"
        "XPASS tests/mcp/test_git_tool.py::test_clone - D6\n"
    )
    buf = io.StringIO()
    rc = module.check_xpass(inventory, stream=buf)
    assert rc == 0, buf.getvalue()
    assert "xpass-check OK" in buf.getvalue()
    assert "2 D6-excluded" in buf.getvalue()


def test_check_xpass_ok_when_zero_xpasses() -> None:
    module = _load_check_xpass()
    inventory = module.parse_xpass_log("1 passed in 0.01s\n")
    buf = io.StringIO()
    assert module.check_xpass(inventory, stream=buf) == 0


def test_main_from_log_exits_one_on_allowed_xpass(tmp_path: Path) -> None:
    module = _load_check_xpass()
    log = tmp_path / "pytest.log"
    log.write_text(
        "XPASS tests/agents/test_minimax_routing.py::test_minimax_missing_credential_fails_loud - leftover\n",
        encoding="utf-8",
    )
    assert module.main(["--from-log", str(log)]) == 1


def test_main_from_log_missing_file_exits_two(tmp_path: Path) -> None:
    module = _load_check_xpass()
    missing = tmp_path / "no-such-pytest.log"
    assert module.main(["--from-log", str(missing)]) == 2


def test_xpass_hook_wired_in_conftest() -> None:
    """CQ-1: xpass ratchet runs as a pytest session hook in ``tests/conftest.py``."""
    conftest = read_text("tests/conftest.py")
    assert "pytest_sessionfinish" in conftest, (
        "pytest_sessionfinish hook missing from tests/conftest.py — "
        "the xpass ratchet must run inside the pytest session, not as a standalone script"
    )
    assert (
        "is_d6_nodeid" in conftest or "D6_TEST_PATHS" in conftest or "_load_check_xpass" in conftest
    ), "D6 exclusion must be imported from scripts/check_xpass.py in the conftest hook"


def test_coverage_gate_streams_live() -> None:
    """CQ-1: ``make coverage-gate`` must not redirect pytest output to a log file."""
    makefile = read_text("Makefile")
    gate = re.search(r"^coverage-gate:.*?(?=^\S)", makefile, re.MULTILINE | re.DOTALL)
    assert gate, "coverage-gate target not found in Makefile"
    body = gate.group(0)
    assert "PYTEST_XPASS_LOG" not in body, (
        "coverage-gate still redirects to PYTEST_XPASS_LOG — restore streaming"
    )
    assert "> " not in body.replace("--cov-report=", ""), (
        "coverage-gate still redirects pytest stdout — restore live streaming"
    )


def test_ci_recipe_runs_xpass_policy() -> None:
    """CQ-1: ``make ci`` must exercise the xpass policy (hook in coverage-gate run)."""
    makefile = read_text("Makefile")
    # The hook runs inside coverage-gate's pytest invocation, so make ci must call coverage-gate.
    ci_line = re.search(r"^ci:.*$", makefile, re.MULTILINE)
    assert ci_line, "ci: target missing"
    assert "coverage-gate" in ci_line.group(0), (
        "make ci must call coverage-gate (which runs the xpass conftest hook)"
    )
