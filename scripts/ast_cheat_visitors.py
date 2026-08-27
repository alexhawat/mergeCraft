"""AST helpers for ``check_test_cheat_signatures`` (D16)."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pathlib import Path

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
    if isinstance(node, ast.Constant):
        return node.value
    return None


def _is_getattr_call(node: ast.AST) -> ast.Call | None:
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Name) and func.id == "getattr":
        return node
    if isinstance(func, ast.Attribute) and func.attr == "getattr":
        return node
    return None


def _getattr_default_literal(call: ast.Call) -> object | None:
    if len(call.args) < 3:
        return None
    return _const_value(call.args[2])


def _is_object_constructor_call(node: ast.AST) -> bool:
    """Return whether ``node`` is a bare ``object()`` call."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "object"
        and not node.keywords
    )


def _getattr_target_cannot_have_attr(
    call: ast.Call,
    bindings: dict[str, ast.AST],
) -> bool:
    """Return whether ``getattr``'s object can never expose the requested name."""
    if not call.args:
        return False
    obj = call.args[0]
    if _is_object_constructor_call(obj):
        return True
    if isinstance(obj, ast.Name):
        bound = bindings.get(obj.id)
        if bound is not None and _is_object_constructor_call(bound):
            return True
    return False


def _is_getattr_tautology_compare(
    node: ast.Compare,
    bindings: dict[str, ast.AST],
) -> str | None:
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
    if not _getattr_target_cannot_have_attr(call, bindings):
        return None
    return f"getattr default {default!r} compared to the same literal"


def _is_verdict_auto_merge_tautology(node: ast.Compare) -> str | None:
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
    return not any(marker in rel for marker in _SKIP_PATH_MARKERS)


def _names_in_expr(node: ast.AST) -> set[str]:
    return {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}


def _assert_kind_for_var(test: ast.AST, var: str) -> str:
    if (
        isinstance(test, ast.Attribute)
        and test.attr == "passed"
        and isinstance(test.value, ast.Name)
        and test.value.id == var
    ):
        return "passed"
    return "other"


def _is_evaluate_decision_case(call: ast.Call) -> bool:
    func = call.func
    if isinstance(func, ast.Name) and func.id == "evaluate_decision_case":
        return _is_expected_answer_kwarg(call)
    if isinstance(func, ast.Attribute) and func.attr == "evaluate_decision_case":
        return _is_expected_answer_kwarg(call)
    return False


class _FunctionCheatVisitor(ast.NodeVisitor):
    """Collect cheat signatures inside one function body (including nested scopes)."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.errors: list[Finding] = []
        self.warnings: list[Finding] = []
        self._eval_result_vars: dict[str, int] = {}
        self._result_assertions: dict[str, list[tuple[int, str]]] = {}
        self._simple_bindings: dict[str, ast.AST] = {}

    def visit_Assert(self, node: ast.Assert) -> None:
        test = node.test
        if isinstance(test, ast.Compare):
            detail = _is_getattr_tautology_compare(test, self._simple_bindings)
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
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Name):
                self._simple_bindings[target.id] = node.value
        if isinstance(node.value, ast.Call) and _is_evaluate_decision_case(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self._eval_result_vars[target.id] = node.lineno
        self.generic_visit(node)

    def finish(self) -> None:
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
    """Walk a module and scan every function (top-level, method, nested)."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.errors: list[Finding] = []
        self.warnings: list[Finding] = []

    def _scan_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        visitor = _FunctionCheatVisitor(self.path)
        for child in node.body:
            visitor.visit(child)
        visitor.finish()
        self.errors.extend(visitor.errors)
        self.warnings.extend(visitor.warnings)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._scan_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._scan_function(node)
        self.generic_visit(node)


def _relative_path(file_path: Path, *, repo: Path) -> str:
    try:
        return file_path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return file_path.resolve().as_posix()


def scan_file(path: Path, *, repo: Path) -> ScanResult:
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


def scan_paths(paths: list[Path], *, repo: Path) -> ScanResult:
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
