"""Batch AD RED — CLI exit-code contract (#341).

Wave plan: ``.ignorelocal/waves/open-issues-sweep-2026-08-20-wave-plan.md``
Authoring wave: **W8** (Batch AD RED). Implementation: **W9** (#341 named exits + docs).

Pins (D11):
- Parametrized outcome → process exit table (clean 0, blocked 11, infra 40, timeout 50,
  usage 2).
- No bare integer ``typer.Exit(N)`` under ``src/mergecraft/cli/``.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from tests.analyzers.support import import_module as import_analyzer_module
from tests.ci.workflow_support import REPO_ROOT
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.offline_review import OfflineReviewResult
from mergecraft.run_outcome import (
    CLI_BLOCKED_EXIT_CODE,
    RunOutcome,
    exit_code_for_outcome,
)

runner = CliRunner()
_CLI_ROOT = REPO_ROOT / "src" / "mergecraft" / "cli"
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_W9_XFAIL = pytest.mark.xfail(
    reason="green after W9: named exit constants + EXIT-CODES.md",
    strict=False,
)

_SAMPLE_PATCH = (
    "diff --git a/demo.py b/demo.py\n--- a/demo.py\n+++ b/demo.py\n@@ -0,0 +1 @@\n+print(1)\n"
)


@dataclass(frozen=True, slots=True)
class BareExitViolation:
    """A ``typer.Exit(<int-literal>)`` site under ``src/mergecraft/cli/``."""

    path: str
    line: int
    col: int
    snippet: str


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def _write_cli_module(tmp_path: Path, rel: str, body: str) -> None:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _is_typer_exit_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "typer"
        and func.attr == "Exit"
    )


def _literal_int(node: ast.AST) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    return None


def _typer_exit_uses_bare_int_literal(node: ast.Call) -> bool:
    if not _is_typer_exit_call(node):
        return False
    if node.args and _literal_int(node.args[0]) is not None:
        return True
    return any(
        keyword.arg == "code" and _literal_int(keyword.value) is not None
        for keyword in node.keywords
    )


def find_cli_bare_exit_violations(root: Path = _CLI_ROOT) -> list[BareExitViolation]:
    """Return ``typer.Exit(<int-literal>)`` sites under ``src/mergecraft/cli/``."""
    display_base = REPO_ROOT if root == _CLI_ROOT else root
    violations: list[BareExitViolation] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(display_base).as_posix()
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=rel)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _typer_exit_uses_bare_int_literal(node):
                continue
            snippet = ast.get_source_segment(source, node) or "typer.Exit(...)"
            violations.append(
                BareExitViolation(
                    path=rel,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    snippet=snippet.splitlines()[0].strip(),
                )
            )
    return violations


def _minor_finding_dict() -> dict[str, object]:
    finding_mod = import_analyzer_module("mergecraft.analyzers.finding")
    finding = finding_mod.make_finding(
        tool="ruff",
        rule_id="F401",
        category="Maintainability & Code Quality",
        severity="Minor",
        confidence="likely",
        message="unused import",
        path="demo.py",
        start_line=1,
        end_line=1,
        source="analyzer",
        introduced_by_pr="unknown",
    )
    return finding.model_dump()


def _blocker_finding_dict() -> dict[str, object]:
    finding_mod = import_analyzer_module("mergecraft.analyzers.finding")
    finding = finding_mod.make_finding(
        tool="mergecraft",
        rule_id="SEC-001",
        category="Security & Privacy",
        severity="Critical",
        confidence="certain",
        message="hard blocker",
        path="demo.py",
        start_line=1,
        end_line=1,
        source="agent",
        introduced_by_pr="unknown",
    )
    return finding.model_dump()


def _patch_offline_review(
    monkeypatch: pytest.MonkeyPatch,
    *,
    outcome: RunOutcome,
    findings: list[dict[str, object]] | None = None,
    success: bool = True,
    error: str | None = None,
) -> None:
    async def fake_run_offline_diff_review(**kwargs: object) -> OfflineReviewResult:
        materialization_path = kwargs.get("diff_file")
        diff_path = str(materialization_path) if materialization_path else None
        structured = json.dumps({"findings": findings or []}) if findings else None
        return OfflineReviewResult(
            success=success and outcome is RunOutcome.passed,
            output="# Review\n\nDone.",
            structured_output=structured,
            diff_path=diff_path,
            outcome=outcome,
            error=error,
        )

    monkeypatch.setattr(
        "mergecraft.cli.diff_review_cmd.run_offline_diff_review",
        fake_run_offline_diff_review,
    )


def _invoke_review(tmp_path: Path) -> Any:
    patch = tmp_path / "change.diff"
    patch.write_text(_SAMPLE_PATCH, encoding="utf-8")
    return runner.invoke(
        app,
        ["review", "--diff", str(patch), "--cwd", str(tmp_path)],
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )


def _review_exit_for_label(label: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> int:
    if label == "clean_pass":
        _patch_offline_review(monkeypatch, outcome=RunOutcome.passed, findings=[])
    elif label == "blocking_findings":
        _patch_offline_review(
            monkeypatch,
            outcome=RunOutcome.failed,
            findings=[_blocker_finding_dict()],
            success=False,
            error="blocking findings",
        )
    elif label == "missing_credential_infra":
        _patch_offline_review(
            monkeypatch,
            outcome=RunOutcome.infra_error,
            success=False,
            error="missing credential",
        )
    elif label == "timeout":
        _patch_offline_review(
            monkeypatch,
            outcome=RunOutcome.timed_out,
            success=False,
            error="timed out",
        )
    else:
        msg = f"unsupported review label {label!r}"
        raise ValueError(msg)
    result = _invoke_review(tmp_path)
    return int(result.exit_code)


def _usage_exit_code() -> int:
    result = runner.invoke(
        app,
        ["auth", "codex", "--scope", "everywhere"],
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )
    return int(result.exit_code)


@pytest.mark.parametrize(
    ("source", "violations"),
    [
        ("import typer\nraise typer.Exit(1)\n", 1),
        ("import typer\nraise typer.Exit(code=2)\n", 1),
        ("import typer\ncode = 11\nraise typer.Exit(code)\n", 0),
        ("import typer\nraise typer.Exit(exit_code)\n", 0),
    ],
)
def test_find_cli_bare_exit_violations_parametrized(
    tmp_path: Path, source: str, violations: int
) -> None:
    """Scanner flags literal ``typer.Exit(N)`` and accepts named exit variables."""
    cli_root = tmp_path / "src" / "mergecraft" / "cli"
    _write_cli_module(cli_root, "sample_cmd.py", source)
    found = find_cli_bare_exit_violations(cli_root)
    assert len(found) == violations


@_W9_XFAIL
def test_no_bare_integer_typer_exit_in_cli_module() -> None:
    """Every CLI exit must route through named constants, not bare ``typer.Exit(N)``."""
    violations = find_cli_bare_exit_violations()
    assert not violations, "\n".join(
        f"{item.path}:{item.line}:{item.col} {item.snippet}" for item in violations[:12]
    )


@pytest.mark.parametrize(
    ("label", "expected_code", "resolver"),
    [
        ("clean_pass", 0, lambda: exit_code_for_outcome(RunOutcome.passed)),
        (
            "blocking_findings",
            11,
            lambda: exit_code_for_outcome(RunOutcome.failed, blocked=True),
        ),
        (
            "missing_credential_infra",
            40,
            lambda: exit_code_for_outcome(RunOutcome.infra_error),
        ),
        ("timeout", 50, lambda: exit_code_for_outcome(RunOutcome.timed_out)),
    ],
)
def test_run_outcome_exit_code_contract_pins(
    label: str,
    expected_code: int,
    resolver: Callable[[], int],
) -> None:
    """D11 table — ``RunOutcome`` helpers map to the documented process exit codes."""
    assert resolver() == expected_code, label
    if label == "blocking_findings":
        assert expected_code == CLI_BLOCKED_EXIT_CODE


@_W9_XFAIL
def test_cli_usage_exit_code_constant_is_two() -> None:
    """Usage / operator-input errors reserve exit code 2 (D11)."""
    mod = import_analyzer_module("mergecraft.run_outcome")
    usage_code = getattr(mod, "CLI_USAGE_EXIT_CODE", None)
    assert usage_code == 2


@pytest.mark.parametrize(
    ("label", "expected_code", "observed"),
    [
        ("clean_pass", 0, "review_passed"),
        ("blocking_findings", 11, "review_blocked"),
        ("missing_credential_infra", 40, "review_infra"),
        ("timeout", 50, "review_timeout"),
        pytest.param(
            "usage_error",
            2,
            "auth_invalid_scope",
            marks=_W9_XFAIL,
        ),
    ],
)
def test_cli_exit_code_contract_pins(
    label: str,
    expected_code: int,
    observed: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Functional pins — CLI commands emit the D11 exit-code table."""
    if observed == "auth_invalid_scope":
        assert _usage_exit_code() == expected_code, label
        return
    assert _review_exit_for_label(label, tmp_path, monkeypatch) == expected_code, label
