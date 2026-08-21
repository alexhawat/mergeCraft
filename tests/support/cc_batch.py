"""Shared helpers for sweep 20c Batch CC RED pins (#354-#360)."""

from __future__ import annotations

import ast
import importlib
import importlib.util
import re
from typing import Any

import pytest
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE
from tests.support.dead_package_wiring import SRC_ROOT

runner = CliRunner()
ANSI = re.compile(r"\x1b\[[0-9;]*m")
DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}

VERIFIER_STATES = frozenset(
    {
        "proven",
        "strongly-supported",
        "supported",
        "unverified",
        "disproven",
        "inconclusive",
    }
)

PACKET_EVIDENCE_KINDS = frozenset(
    {
        "changed_lines",
        "related_definitions",
        "callers_callees",
        "related_tests",
        "analyzer_findings",
        "compiler_typechecker",
        "git_history",
        "contract_schema",
        "cross_repo",
        "policy",
        "ticket_spec",
    }
)

POLICY_PACK_IDS = (
    "security",
    "public_api",
    "migrations",
    "dependency_changes",
    "authentication_authorization",
    "testing",
    "operational_readiness",
)

MEMORY_KINDS = frozenset(
    {
        "factual_repository",
        "engineering_policy",
        "reviewer_preference",
        "false_positive_suppression",
    }
)


def plain(text: str) -> str:
    return ANSI.sub("", text)


def invoke(*argv: str) -> Any:
    return runner.invoke(app, list(argv), env=DUMB_ENV)


def require_registered(*argv: str, label: str) -> Any:
    """Fail until a CLI verb is registered (avoids XPASS on Typer usage exit)."""
    result = invoke(*argv)
    if result.exit_code != CLI_SUCCESS_EXIT_CODE:
        pytest.fail(f"{label} is not registered yet")
    return result


def load_module(module_name: str) -> Any:
    spec = importlib.util.find_spec(module_name)
    if spec is None:
        pytest.fail(f"expected module {module_name}")
    return importlib.import_module(module_name)


def require_callable(module: Any, name: str) -> Any:
    fn = getattr(module, name, None)
    if not callable(fn):
        pytest.fail(f"expected callable {module.__name__}.{name}")
    return fn


def decide_approval_defining_files() -> list[str]:
    """Return repo-relative files that define ``decide_approval`` (D14)."""
    hits: list[str] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if any(
            isinstance(node, ast.FunctionDef) and node.name == "decide_approval"
            for node in ast.walk(tree)
        ):
            hits.append(path.relative_to(SRC_ROOT).as_posix())
    return hits
