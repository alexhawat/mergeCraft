"""W4.1 — ``mergecraft.requirements`` production wiring pins (#352 / W6).

Library mapping lives in ``requirements/criteria.py``. This file pins ingest,
nonce fencing, requirement states, CLI inspect/explain, and the D14 rule that
policy may require evidence without a second ``decide_approval``.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import re
from pathlib import Path
from typing import Any

import pytest
from tests.support.dead_package_wiring import (
    SRC_ROOT,
    cli_cmd_path,
    production_importers,
    production_invoked_names,
    root_callback_source,
)
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}

REQUIREMENT_STATES = frozenset(
    {
        "satisfied",
        "partially_satisfied",
        "contradicted",
        "not_evidenced",
        "out_of_scope",
    }
)


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def _invoke(*argv: str) -> Any:
    return runner.invoke(app, list(argv), env=_DUMB_ENV)


def _require_requirements() -> None:
    """Fail until ``requirements`` is registered (avoids XPASS on Typer usage)."""
    result = _invoke("requirements", "--help")
    if result.exit_code != CLI_SUCCESS_EXIT_CODE:
        pytest.fail("mergecraft requirements is not registered yet")


def test_requirements_has_a_review_or_cli_production_call_site() -> None:
    """W6 — review path or CLI imports ``mergecraft.requirements``."""
    importers = production_importers("requirements")
    assert importers, "expected a production import of mergecraft.requirements"
    assert any(
        path.startswith(("cli/", "modes/", "mcp/", "action/", "agents/", "policy/"))
        or path == "main.py"
        for path in importers
    )


def test_requirements_cli_is_a_new_cmd_module() -> None:
    """D10 — inspect/explain live in ``cli/requirements_cmd.py``."""
    path = cli_cmd_path("requirements")
    assert path is not None, "expected src/mergecraft/cli/requirements_cmd.py"
    source = path.read_text(encoding="utf-8")
    assert "inspect" in source
    assert "explain" in source


def test_root_help_lists_requirements() -> None:
    """Happy: root help advertises the requirements command group."""
    result = _invoke("--help")
    help_text = _plain(result.stdout + result.stderr).casefold()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, help_text
    assert "requirements" in help_text


def test_requirements_inspect_help_is_registered() -> None:
    """Happy: ``mergecraft requirements inspect --help`` exists."""
    result = _invoke("requirements", "inspect", "--help")
    help_text = _plain(result.stdout + result.stderr).casefold()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, help_text
    assert "inspect" in help_text


def test_requirements_explain_help_is_registered() -> None:
    """Happy: ``mergecraft requirements explain --help`` exists."""
    result = _invoke("requirements", "explain", "--help")
    help_text = _plain(result.stdout + result.stderr).casefold()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, help_text
    assert "explain" in help_text


def test_ingest_fences_external_requirement_text_with_nonce() -> None:
    """#352 — ticket/spec ingest uses the existing nonce fence."""
    invoked = production_invoked_names(exclude_package="utils")
    fenced = invoked & {"render_untrusted", "fence_unless_trusted"}
    assert fenced, "requirements ingest must call render_untrusted or fence_unless_trusted"
    assert production_importers("requirements"), "ingest needs a production importer"


def test_requirement_states_are_the_five_named_outcomes() -> None:
    """#352 — states: satisfied / partially_satisfied / contradicted /
    not_evidenced / out_of_scope.
    """
    module = importlib.import_module("mergecraft.requirements")
    states = getattr(module, "REQUIREMENT_STATES", None)
    if states is None:
        for attr in ("RequirementState", "requirement_states"):
            candidate = getattr(module, attr, None)
            if candidate is not None:
                states = candidate
                break
    assert states is not None, "mergecraft.requirements must export requirement states"
    as_text = {str(item).rsplit(".", maxsplit=1)[-1] for item in states}
    assert as_text >= REQUIREMENT_STATES or {str(item) for item in states} >= REQUIREMENT_STATES


@pytest.mark.parametrize(
    "source",
    [
        "pr_description",
        "linked_issue",
        "local_spec",
    ],
)
def test_ingest_accepts_named_requirement_sources(source: str) -> None:
    """#352 — ingest covers PR description, linked issue, and local spec (min)."""
    invoked = production_invoked_names(exclude_package="requirements")
    assert "ingest_requirements" in invoked or "ingest" in invoked
    module = importlib.import_module("mergecraft.requirements")
    ingest = getattr(module, "ingest_requirements", None) or getattr(module, "ingest", None)
    assert callable(ingest)
    names = set(inspect.signature(ingest).parameters)
    source_ok = source in names or any("source" in name for name in names)
    assert source_ok, f"ingest contract does not admit source {source!r}"


def test_inspect_cli_lists_states(tmp_path: Path) -> None:
    """Happy: ``requirements inspect`` reports requirement states."""
    (tmp_path / "SPEC.md").write_text("## Acceptance criteria\n\n- [ ] login works\n")
    result = _invoke("requirements", "inspect", "--repo-root", str(tmp_path))
    output = _plain(result.stdout + result.stderr).casefold()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert any(state.replace("_", " ") in output or state in output for state in REQUIREMENT_STATES)


def test_explain_unknown_requirement_id_is_an_error() -> None:
    """Error: ``requirements explain`` on a missing id is not a silent success."""
    _require_requirements()
    result = _invoke("requirements", "explain", "REQ-DOES-NOT-EXIST")
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code != CLI_SUCCESS_EXIT_CODE, combined


def test_decide_approval_is_the_only_approval_gate() -> None:
    """D14 current state: ``decide_approval`` exists; no requirements fork."""
    invoked = production_invoked_names()
    assert "decide_approval" in invoked
    gates = (SRC_ROOT / "agents" / "gates.py").read_text(encoding="utf-8")
    tree = ast.parse(gates)
    defs = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name.startswith("decide_")
    ]
    assert "decide_approval" in defs
    extra = [
        name
        for name in defs
        if name in {"decide_approval_from_requirements", "decide_requirements_approval"}
    ]
    assert extra == []
    source = root_callback_source()
    assert "def _root(" in source


def test_policy_may_require_requirements_evidence() -> None:
    """#352 — policy can require requirements evidence before a review passes."""
    invoked = production_invoked_names(exclude_package="requirements")
    assert invoked & {
        "require_requirements_evidence",
        "requirements_evidence_required",
    }, "policy must be able to require requirements evidence"
