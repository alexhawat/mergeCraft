"""xpass ratchet tests (#276).

``scripts/check_xpass.py`` provides the shared ``check_xpass`` helper. The live
gate runs inside the pytest session via the ``tests/conftest.py``
``pytest_sessionfinish`` hook.
"""

from __future__ import annotations

import importlib.util
import io
import re
from pathlib import Path
from typing import Any

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


def test_parse_xpass_log_collects_all_xpasses() -> None:
    module = _load_check_xpass()
    log = """\
XPASS tests/agents/test_codex_custom_provider.py::test_codex_indexed_wins_singleton_ignored - leftover
XPASS tests/evidence/test_gate_actions.py::test_new_gates_default_to_shadow - leftover
XPASS tests/cli/test_models_list_minimax.py::test_mergecraft_models_list_renders_minimax_row_with_credentials - leftover
2989 passed, 30 skipped, 13 xfailed, 121 xpassed, 10 warnings in 156.09s
"""
    inventory = module.parse_xpass_log(log)
    assert inventory.total == 3
    assert inventory.xpass_count == 3
    assert [r.nodeid for r in inventory.xpass_records] == [
        "tests/agents/test_codex_custom_provider.py::test_codex_indexed_wins_singleton_ignored",
        "tests/evidence/test_gate_actions.py::test_new_gates_default_to_shadow",
        "tests/cli/test_models_list_minimax.py::test_mergecraft_models_list_renders_minimax_row_with_credentials",
    ]


def test_parse_xpass_log_empty_is_zero() -> None:
    module = _load_check_xpass()
    inventory = module.parse_xpass_log("2989 passed, 30 skipped in 1.00s\n")
    assert inventory.total == 0
    assert inventory.xpass_count == 0


def test_check_xpass_fails_on_any_xpass() -> None:
    module = _load_check_xpass()
    inventory = module.parse_xpass_log(
        "XPASS tests/evidence/test_gate_actions.py::test_shadow_mode - leftover\n"
    )
    buf = io.StringIO()
    rc = module.check_xpass(inventory, stream=buf)
    assert rc == 1
    text = buf.getvalue()
    assert "xpass-check FAILED" in text
    assert "1 xpassed" in text
    assert "tests/evidence/test_gate_actions.py::test_shadow_mode" in text


def test_check_xpass_ok_when_zero_xpasses() -> None:
    module = _load_check_xpass()
    inventory = module.parse_xpass_log("1 passed in 0.01s\n")
    buf = io.StringIO()
    assert module.check_xpass(inventory, stream=buf) == 0


def test_main_from_log_exits_one_on_xpass(tmp_path: Path) -> None:
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
    assert "_load_check_xpass" in conftest, (
        "conftest must load scripts/check_xpass.py for the session hook"
    )
    assert "check_xpass" in conftest, (
        "conftest hook must call check_xpass on an XpassInventory built from xpassed stats"
    )
    assert "XpassInventory" in conftest, (
        "conftest hook must build an XpassInventory from xpassed stats"
    )


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
