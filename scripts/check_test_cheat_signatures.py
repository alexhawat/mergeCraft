#!/usr/bin/env python3
"""Flag tautological test patterns in the ``tests/`` tree (D16).

Detects:

* ``getattr(mod, "NAME", <literal>)`` compared for equality to the same literal.
* ``evaluate_decision_case(..., answer=case.expected_answer)`` when the only
  assertion on the result is ``assert result.passed``.
* ``verdict != "auto_merge"`` comparisons (warning only).

Scans top-level function bodies only; nested scopes (inner functions, lambdas)
are not walked.

By default the gate **blocks** (exit 1 on errors). Pass ``--advisory`` to print
findings but exit 0 so grandfathered sites do not block ``make lint``.

Module: scripts.check_test_cheat_signatures
Depends: argparse, ast, pathlib, sys, typing

Exports:
    scan_file — AST scan one Python file.
    scan_paths — scan many files and return errors and warnings.
    main — CLI entry.
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, TextIO

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"

FindingKind = Literal["getattr_tautology", "decision_eval_tautology", "verdict_tautology"]


@dataclass
class Finding:
    """One cheat-signature hit."""

    path: str
    line_no: int
    kind: FindingKind
    detail: str

    @property
    def level(self) -> Literal["error", "warning"]:
        """Return whether this finding fails the gate."""
        if self.kind == "verdict_tautology":
            return "warning"
        return "error"


@dataclass
class ScanResult:
    """Aggregated scan output."""

    errors: list[Finding] = field(default_factory=list)
    warnings: list[Finding] = field(default_factory=list)


def _const_value(node: ast.AST) -> object | None:
    """Return a constant value when ``node`` is a literal."""
    if isinstance(node, ast.Constant):
        return node.value
    return None


def _is_getattr_call(node: ast.AST) -> ast.Call | None:
    """Return the ``getattr`` call when ``node`` is ``getattr(...)``."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Name) and func.id == "getattr":
        return node
    if isinstance(func, ast.Attribute) and func.attr == "getattr":
        return node
    return None


def _getattr_default_literal(call: ast.Call) -> object | None:
    """Return the third positional default literal for a ``getattr`` call."""
    if len(call.args) < 3:
        return None
    return _const_value(call.args[2])


def _is_getattr_tautology_compare(node: ast.Compare) -> str | None:
    """Return a detail string when ``node`` is a getattr literal tautology."""
    left = node.left
    call = _is_getattr_call(left)
    if call is None or len(node.ops) != 1 or not isinstance(node.ops[0], ast.Eq):
        return None
    if len(node.comparators) != 1:
        return None
    default = _getattr_default_literal(call)
    comparator = _const_value(node.comparators[0])
    if default is None or comparator is None or default != comparator:
        return None
    return f"getattr default {default!r} compared to the same literal"


def _is_verdict_auto_merge_tautology(node: ast.Compare) -> str | None:
    """Return detail when ``node`` compares a verdict field to ``auto_merge`` with ``!=``."""
    if len(node.ops) != 1 or not isinstance(node.ops[0], ast.NotEq):
        return None
    if len(node.comparators) != 1:
        return None
    target: str | None = None
    if isinstance(node.left, ast.Attribute) and node.left.attr == "verdict":
        target = "verdict"
    elif isinstance(node.left, ast.Name) and node.left.id in {"verdict", "decision"}:
        target = node.left.id
    if target is None:
        return None
    comparator = _const_value(node.comparators[0])
    if comparator != "auto_merge":
        return None
    return f'{target} != "auto_merge" is tautological for self-assessment packets'


def _is_expected_answer_kwarg(call: ast.Call) -> bool:
    """Return True when ``answer=case.expected_answer``."""
    for keyword in call.keywords:
        if keyword.arg != "answer":
            continue
        value = keyword.value
        if (
            isinstance(value, ast.Attribute)
            and isinstance(value.value, ast.Name)
            and value.value.id == "case"
            and value.attr == "expected_answer"
        ):
            return True
    return False


_SKIP_PATH_MARKERS = ("/fixtures/", "/analyzer-cache/", "/node_modules/")


def _should_scan(rel: str) -> bool:
    """Return False for vendored trees under test fixtures."""
    return not any(marker in rel for marker in _SKIP_PATH_MARKERS)


def _names_in_expr(node: ast.AST) -> set[str]:
    """Return variable names referenced in ``node``."""
    return {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}


def _assert_kind_for_var(test: ast.AST, var: str) -> str:
    """Classify how ``test`` uses ``var`` inside an assert."""
    if (
        isinstance(test, ast.Attribute)
        and test.attr == "passed"
        and isinstance(test.value, ast.Name)
        and test.value.id == var
    ):
        return "passed"
    return "other"


def _is_evaluate_decision_case(call: ast.Call) -> bool:
    """Return True when ``call`` invokes ``evaluate_decision_case``."""
    func = call.func
    if isinstance(func, ast.Name) and func.id == "evaluate_decision_case":
        return _is_expected_answer_kwarg(call)
    if isinstance(func, ast.Attribute) and func.attr == "evaluate_decision_case":
        return _is_expected_answer_kwarg(call)
    return False


class _FunctionCheatVisitor(ast.NodeVisitor):
    """Collect cheat signatures inside one function body."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.errors: list[Finding] = []
        self.warnings: list[Finding] = []
        self._eval_result_vars: dict[str, int] = {}
        self._result_assertions: dict[str, list[tuple[int, str]]] = {}

    def visit_Assert(self, node: ast.Assert) -> None:
        test = node.test
        if isinstance(test, ast.Compare):
            detail = _is_getattr_tautology_compare(test)
            if detail is not None:
                self.errors.append(Finding(self.path, node.lineno, "getattr_tautology", detail))
            warn = _is_verdict_auto_merge_tautology(test)
            if warn is not None:
                self.warnings.append(Finding(self.path, node.lineno, "verdict_tautology", warn))
        for var in self._eval_result_vars:
            if var not in _names_in_expr(test):
                continue
            kind = _assert_kind_for_var(test, var)
            self._result_assertions.setdefault(var, []).append((node.lineno, kind))

    def visit_Assign(self, node: ast.Assign) -> None:
        if isinstance(node.value, ast.Call) and _is_evaluate_decision_case(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self._eval_result_vars[target.id] = node.lineno

    def finish(self) -> None:
        """Emit decision-eval tautologies after the function body is walked."""
        for var, assign_line in self._eval_result_vars.items():
            assertions = self._result_assertions.get(var, [])
            if not assertions:
                continue
            if any(kind != "passed" for _, kind in assertions):
                continue
            self.errors.append(
                Finding(
                    self.path,
                    assign_line,
                    "decision_eval_tautology",
                    "evaluate_decision_case(answer=case.expected_answer) "
                    f"with only assert {var}.passed",
                )
            )


class _ModuleCheatVisitor(ast.NodeVisitor):
    """Walk a module and delegate per-function analysis."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.errors: list[Finding] = []
        self.warnings: list[Finding] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        visitor = _FunctionCheatVisitor(self.path)
        for child in node.body:
            visitor.visit(child)
        visitor.finish()
        self.errors.extend(visitor.errors)
        self.warnings.extend(visitor.warnings)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        visitor = _FunctionCheatVisitor(self.path)
        for child in node.body:
            visitor.visit(child)
        visitor.finish()
        self.errors.extend(visitor.errors)
        self.warnings.extend(visitor.warnings)


def _relative_path(file_path: Path, *, repo: Path) -> str:
    """Return a repo-relative path when possible, else an absolute path string."""
    try:
        return file_path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return file_path.resolve().as_posix()


def scan_file(path: Path, *, repo: Path = REPO) -> ScanResult:
    """Scan one Python file for cheat signatures."""
    rel = _relative_path(path, repo=repo)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
    except SyntaxError as exc:
        return ScanResult(
            errors=[Finding(rel, exc.lineno or 1, "getattr_tautology", f"syntax error: {exc}")]
        )

    visitor = _ModuleCheatVisitor(rel)
    visitor.visit(tree)
    return ScanResult(errors=visitor.errors, warnings=visitor.warnings)


def scan_paths(paths: list[Path], *, repo: Path = REPO) -> ScanResult:
    """Scan many files (files or directories)."""
    files: list[Path] = []
    for path in paths:
        resolved = path if path.is_absolute() else repo / path
        if resolved.is_dir():
            files.extend(sorted(resolved.rglob("*.py")))
        elif resolved.is_file():
            files.append(resolved)

    combined = ScanResult()
    for file_path in files:
        rel = _relative_path(file_path, repo=repo)
        if not _should_scan(rel):
            continue
        result = scan_file(file_path, repo=repo)
        combined.errors.extend(result.errors)
        combined.warnings.extend(result.warnings)
    return combined


def _print_findings(result: ScanResult, *, stream: TextIO = sys.stderr) -> None:
    """Print errors and warnings."""
    for finding in [*result.errors, *result.warnings]:
        prefix = "ERROR" if finding.level == "error" else "WARN"
        print(
            f"cheat-signature {prefix} {finding.path}:{finding.line_no}: "
            f"{finding.kind}: {finding.detail}",
            file=stream,
        )


def main(argv: list[str] | None = None) -> int:
    """CLI entry."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        help="Files or directories to scan (default: tests/).",
    )
    parser.add_argument(
        "--advisory",
        action="store_true",
        help="Print findings but exit 0 (opt-out from the default blocking gate).",
    )
    args = parser.parse_args(argv)

    scan_targets = [Path(p) for p in args.paths] if args.paths else [TESTS]
    if not scan_targets and not TESTS.is_dir():
        print(f"missing tests tree: {TESTS}", file=sys.stderr)
        return 1

    result = scan_paths(scan_targets)
    if result.errors or result.warnings:
        _print_findings(result)

    if result.errors and not args.advisory:
        print(
            f"cheat-signature: {len(result.errors)} error(s), {len(result.warnings)} warning(s)",
            file=sys.stderr,
        )
        return 1

    if result.warnings:
        print(f"cheat-signature: {len(result.warnings)} warning(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
