"""AST visitors for ``lint_test_honesty`` — test-tree honesty rules."""

from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

RULE_SLEEP_CONSTANT = "sleep_constant"
RULE_FLAKE_MARKER = "flake_marker"
RULE_RERUN_CONFIG = "rerun_config"
RULE_TIMEOUT_INFLATED = "timeout_inflated"
RULE_EXCEPT_SWALLOW = "except_swallow"
RULE_CONDITIONAL_ASSERT = "conditional_assert"
RULE_SELF_MOCK = "self_mock"

FindingLevel = Literal["error", "warning"]

_DEFAULT_TIMEOUT_SECONDS = 180
_TIMEOUT_INFLATION_THRESHOLD = 180

_HONESTY_ALLOW = re.compile(r"#\s*honesty:\s*allow\s+(\S.+)$", re.IGNORECASE)

_RULE_MESSAGES: dict[str, str] = {
    RULE_SLEEP_CONSTANT: (
        "remove fixed sleeps — await the event or poll the real signal instead of sleeping"
    ),
    RULE_FLAKE_MARKER: (
        "remove flake/rerun markers — fix the root cause instead of masking instability"
    ),
    RULE_RERUN_CONFIG: (
        "remove pytest-rerunfailures / reruns= configuration — fix flaky tests instead of retrying"
    ),
    RULE_TIMEOUT_INFLATED: (
        "lower the per-test timeout or speed up the test — do not raise timeouts to hide slowness"
    ),
    RULE_EXCEPT_SWALLOW: (
        "do not swallow exceptions in tests — assert the expected failure or re-raise"
    ),
    RULE_CONDITIONAL_ASSERT: (
        "avoid conditional assertions — assert unconditionally or use pytest.raises / fail()"
    ),
    RULE_SELF_MOCK: (
        "avoid mocking the module under test — patch collaborators instead of the unit under test"
    ),
}


def _ast_anchor(node: ast.AST) -> str:
    """Position-independent digest of an AST subtree (fallback only)."""
    payload = ast.dump(node, annotate_fields=False)
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def _source_line_anchor(lines: list[str], line_no: int, *, prefix: str = "") -> str:
    """Anchor from the physical source line (stable across Python versions)."""
    if 0 < line_no <= len(lines):
        return f"{prefix}{lines[line_no - 1].strip()}"
    return f"{prefix}@{line_no}"


def _except_handler_anchor(handler: ast.ExceptHandler) -> str:
    if handler.type is None:
        return "bare-except"
    return ast.unparse(handler.type) if hasattr(ast, "unparse") else _ast_anchor(handler.type)


@dataclass(frozen=True)
class HonestyFinding:
    """One honesty violation."""

    path: str
    line_no: int
    rule: str
    detail: str
    anchor: str
    level: FindingLevel = "error"

    @property
    def message(self) -> str:
        """Return the user-facing message including the prescribed fix."""
        fix = _RULE_MESSAGES.get(self.rule, "fix this test-honesty violation")
        return f"{self.rule}: {self.detail}. {fix}"

    @property
    def fingerprint(self) -> str:
        """Stable key for baseline entries (path + rule + logical anchor, no line number)."""
        return f"{self.path}:{self.rule}:{self.anchor}"


@dataclass
class HonestyScanResult:
    """Aggregated findings."""

    findings: list[HonestyFinding] = field(default_factory=list)


def _lines(source: str) -> list[str]:
    return source.splitlines()


def _line_has_allow(lines: list[str], line_no: int) -> bool:
    """Return whether an inline honesty allow comment covers ``line_no`` (1-based)."""
    idx = line_no - 1
    for offset in (0, -1):
        pos = idx + offset
        if 0 <= pos < len(lines) and _HONESTY_ALLOW.search(lines[pos]):
            return True
    return False


def _is_const_number(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, (int, float))


def _dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        if base is None:
            return None
        return f"{base}.{node.attr}"
    return None


def _sleep_callee(node: ast.Call) -> str | None:
    name = _dotted_name(node.func)
    if name in {"time.sleep", "asyncio.sleep"}:
        return name
    if isinstance(node.func, ast.Attribute) and node.func.attr == "sleep":
        base = _dotted_name(node.func.value)
        if base in {"time", "asyncio"}:
            return f"{base}.sleep"
    return None


def _module_under_test(rel_path: str) -> str | None:
    """Map ``tests/<pkg>/test_mod.py`` → ``mergecraft.<pkg>.<mod>``."""
    path = Path(rel_path)
    if path.name == "conftest.py":
        parts = path.parts
        if "tests" not in parts:
            return None
        idx = parts.index("tests")
        tail = parts[idx + 1 : -1]
        if not tail:
            return "mergecraft"
        return "mergecraft." + ".".join(tail)
    if path.suffix != ".py":
        return None
    if path.name.startswith("test_"):
        stem = path.stem.removeprefix("test_")
    elif path.name.startswith("violation_"):
        stem = path.stem.removeprefix("violation_")
    else:
        return None
    parts = path.parts
    if "tests" not in parts:
        return None
    idx = parts.index("tests")
    pkg_parts = list(parts[idx + 1 : -1])
    if pkg_parts:
        return "mergecraft." + ".".join([*pkg_parts, stem])
    return f"mergecraft.{stem}"


class _HonestyVisitor(ast.NodeVisitor):
    def __init__(self, *, rel_path: str, lines: list[str]) -> None:
        self.rel_path = rel_path
        self.lines = lines
        self.findings: list[HonestyFinding] = []
        self._under_test = _module_under_test(rel_path)
        self._current_func = "<module>"
        self._anchor_seq: dict[tuple[str, str, str], int] = {}

    def _scoped_anchor(self, rule: str, base: str) -> str:
        """Return ``func:base#n`` with a per-function occurrence index."""
        key = (rule, self._current_func, base)
        seq = self._anchor_seq.get(key, 0) + 1
        self._anchor_seq[key] = seq
        return f"{self._current_func}:{base}#{seq}"

    def _maybe_add(self, finding: HonestyFinding) -> None:
        if _line_has_allow(self.lines, finding.line_no):
            return
        self.findings.append(finding)

    def visit_Call(self, node: ast.Call) -> None:
        sleep_name = _sleep_callee(node)
        if sleep_name and node.args and _is_const_number(node.args[0]):
            arg0 = node.args[0]
            assert isinstance(arg0, ast.Constant)
            value = arg0.value
            if isinstance(value, (int, float)) and value == 0:
                pass
            else:
                base = f"{sleep_name}({value!r})"
                self._maybe_add(
                    HonestyFinding(
                        path=self.rel_path,
                        line_no=node.lineno,
                        rule=RULE_SLEEP_CONSTANT,
                        detail=base,
                        anchor=self._scoped_anchor(RULE_SLEEP_CONSTANT, base),
                    )
                )

        suppress_name = _dotted_name(node.func)
        if suppress_name in {"contextlib.suppress", "suppress"}:
            base = _source_line_anchor(self.lines, node.lineno, prefix="suppress:")
            self._maybe_add(
                HonestyFinding(
                    path=self.rel_path,
                    line_no=node.lineno,
                    rule=RULE_EXCEPT_SWALLOW,
                    detail="contextlib.suppress swallows exceptions",
                    anchor=self._scoped_anchor(RULE_EXCEPT_SWALLOW, base),
                )
            )

        func = _dotted_name(node.func)
        is_patch = func in {"unittest.mock.patch", "mock.patch"} or (
            isinstance(node.func, ast.Name) and node.func.id == "patch"
        )
        if is_patch and node.args:
            target = node.args[0]
            if isinstance(target, ast.Constant) and isinstance(target.value, str):
                self._check_patch_target(target.value, node.lineno)
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "setattr"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            module_path = node.args[0].value
            attr = None
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                attr = node.args[1].value
            if isinstance(attr, str):
                self._check_patch_target(f"{module_path}.{attr}", node.lineno)

        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        if (
            len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "pytest_plugins"
            and isinstance(node.value, ast.List)
        ):
            for elt in node.value.elts:
                if isinstance(elt, ast.Constant) and elt.value == "pytest_rerunfailures":
                    self._maybe_add(
                        HonestyFinding(
                            path=self.rel_path,
                            line_no=node.lineno,
                            rule=RULE_RERUN_CONFIG,
                            detail="pytest_plugins lists pytest_rerunfailures",
                            anchor="pytest_plugins:pytest_rerunfailures",
                        )
                    )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == "pytest_rerunfailures":
            self._maybe_add(
                HonestyFinding(
                    path=self.rel_path,
                    line_no=node.lineno,
                    rule=RULE_RERUN_CONFIG,
                    detail="imports pytest_rerunfailures",
                    anchor="import:pytest_rerunfailures",
                )
            )
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        prev = self._current_func
        self._current_func = node.name
        for dec in node.decorator_list:
            self._visit_decorator(dec, context=node.name)
            self._visit_patch_decorator(dec)
        self._visit_assertions_in_body(node.body)
        self.generic_visit(node)
        self._current_func = prev

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        prev = self._current_func
        self._current_func = node.name
        for dec in node.decorator_list:
            self._visit_decorator(dec, context=node.name)
            self._visit_patch_decorator(dec)
        self._visit_assertions_in_body(node.body)
        self.generic_visit(node)
        self._current_func = prev

    def _visit_patch_decorator(self, dec: ast.expr) -> None:
        if not isinstance(dec, ast.Call):
            return
        name = _dotted_name(dec.func)
        if (
            (
                name in {None, "patch", "mock.patch", "unittest.mock.patch"}
                or (isinstance(dec.func, ast.Name) and dec.func.id == "patch")
            )
            and dec.args
            and isinstance(dec.args[0], ast.Constant)
            and isinstance(dec.args[0].value, str)
        ):
            self._check_patch_target(dec.args[0].value, dec.lineno)

    def _visit_decorator(self, dec: ast.expr, *, context: str) -> None:
        if not isinstance(dec, ast.Call):
            if isinstance(dec, ast.Attribute) and _dotted_name(dec) == "pytest.mark.flaky":
                self._maybe_add(
                    HonestyFinding(
                        path=self.rel_path,
                        line_no=dec.lineno,
                        rule=RULE_FLAKE_MARKER,
                        detail=f"@pytest.mark.flaky on {context}",
                        anchor=f"flaky:{context}",
                    )
                )
            return
        name = _dotted_name(dec.func)
        if name == "pytest.mark.flaky" or (
            isinstance(dec.func, ast.Attribute) and dec.func.attr == "flaky"
        ):
            self._maybe_add(
                HonestyFinding(
                    path=self.rel_path,
                    line_no=dec.lineno,
                    rule=RULE_FLAKE_MARKER,
                    detail=f"flaky marker on {context}",
                    anchor=f"flaky:{context}",
                )
            )
        if name == "pytest.mark.timeout" or (
            isinstance(dec.func, ast.Attribute) and dec.func.attr == "timeout"
        ):
            seconds = _timeout_marker_seconds(dec)
            if seconds is not None and (seconds > _TIMEOUT_INFLATION_THRESHOLD or seconds <= 0):
                reason = (
                    "disables per-test timeout"
                    if seconds <= 0
                    else f"exceeds default {_DEFAULT_TIMEOUT_SECONDS}s"
                )
                anchor = f"timeout:{context}@{seconds}"
                self._maybe_add(
                    HonestyFinding(
                        path=self.rel_path,
                        line_no=dec.lineno,
                        rule=RULE_TIMEOUT_INFLATED,
                        detail=f"@pytest.mark.timeout({seconds}) on {context} ({reason})",
                        anchor=anchor,
                    )
                )
        for kw in dec.keywords:
            if kw.arg == "reruns" and _is_const_number(kw.value):
                reruns_node = kw.value
                assert isinstance(reruns_node, ast.Constant)
                reruns = reruns_node.value
                self._maybe_add(
                    HonestyFinding(
                        path=self.rel_path,
                        line_no=dec.lineno,
                        rule=RULE_RERUN_CONFIG,
                        detail=f"reruns={reruns} on {context}",
                        anchor=f"reruns:{context}@{reruns}",
                    )
                )

    def _check_patch_target(self, target: str, line_no: int) -> None:
        if not self._under_test:
            return
        if target.startswith(self._under_test):
            self._maybe_add(
                HonestyFinding(
                    path=self.rel_path,
                    line_no=line_no,
                    rule=RULE_SELF_MOCK,
                    detail=f"patch({target!r}) targets module under test {self._under_test}",
                    anchor=self._scoped_anchor(RULE_SELF_MOCK, f"patch:{target}"),
                    level="warning",
                )
            )

    def visit_Try(self, node: ast.Try) -> None:
        for handler in node.handlers:
            if _handler_swallows(handler):
                base = f"except-pass:{_except_handler_anchor(handler)}"
                self._maybe_add(
                    HonestyFinding(
                        path=self.rel_path,
                        line_no=handler.lineno,
                        rule=RULE_EXCEPT_SWALLOW,
                        detail="except block with only pass",
                        anchor=self._scoped_anchor(RULE_EXCEPT_SWALLOW, base),
                    )
                )
        self.generic_visit(node)

    def _visit_assertions_in_body(self, body: list[ast.stmt]) -> None:
        for stmt in body:
            self._walk_conditional_asserts(stmt, conditional=False)

    def _walk_conditional_asserts(self, node: ast.stmt, *, conditional: bool) -> None:
        if isinstance(node, ast.Assert):
            if conditional:
                base = _source_line_anchor(self.lines, node.lineno, prefix="assert:")
                self._maybe_add(
                    HonestyFinding(
                        path=self.rel_path,
                        line_no=node.lineno,
                        rule=RULE_CONDITIONAL_ASSERT,
                        detail="assert only runs on a conditional branch",
                        anchor=self._scoped_anchor(RULE_CONDITIONAL_ASSERT, base),
                    )
                )
            return
        if isinstance(node, ast.If):
            for child in node.body:
                self._walk_conditional_asserts(child, conditional=True)
            for child in node.orelse:
                self._walk_conditional_asserts(child, conditional=True)
            return
        if isinstance(node, ast.Try):
            for child in node.body:
                self._walk_conditional_asserts(child, conditional=conditional)
            for handler in node.handlers:
                for child in handler.body:
                    self._walk_conditional_asserts(child, conditional=True)
            for child in node.orelse:
                self._walk_conditional_asserts(child, conditional=conditional)
            for child in node.finalbody:
                self._walk_conditional_asserts(child, conditional=conditional)
            return
        if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            body_conditional = conditional or not _loop_body_always_runs(node)
            for child in node.body:
                self._walk_conditional_asserts(child, conditional=body_conditional)
            for child in node.orelse:
                self._walk_conditional_asserts(child, conditional=conditional)
            return
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for child in node.body:
                self._walk_conditional_asserts(child, conditional=conditional)
            return


def _loop_body_always_runs(node: ast.For | ast.AsyncFor | ast.While) -> bool:
    """Return whether every statement in the loop body is reached at least once.

    True only for ``for`` over a non-empty tuple/list/set literal without ``break`` or
    ``continue``: its asserts run exactly as if they were written out one by one.
    """
    if not isinstance(node, ast.For) or not isinstance(node.iter, (ast.Tuple, ast.List, ast.Set)):
        return False
    if all(isinstance(element, ast.Starred) for element in node.iter.elts):
        return False
    return not any(
        isinstance(child, (ast.Break, ast.Continue))
        for stmt in node.body
        for child in ast.walk(stmt)
    )


def _handler_swallows(handler: ast.ExceptHandler) -> bool:
    if not handler.body:
        return False
    return all(isinstance(stmt, ast.Pass) for stmt in handler.body)


def _timeout_marker_seconds(dec: ast.Call) -> int | float | None:
    if dec.args and _is_const_number(dec.args[0]):
        val = dec.args[0].value
        return val if isinstance(val, (int, float)) else None
    for kw in dec.keywords:
        if kw.arg in {"timeout", "seconds", None} and _is_const_number(kw.value):
            val = kw.value.value
            return val if isinstance(val, (int, float)) else None
    return None


HONESTY_RUFF_EXCLUDE = "tests/scripts/fixtures/test_honesty"


def scan_file(path: Path, *, repo: Path) -> HonestyScanResult:
    """Scan one Python file under ``tests/``."""
    rel = path.relative_to(repo).as_posix()
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return HonestyScanResult()
    lines = _lines(source)
    try:
        tree = ast.parse(source, filename=rel)
    except SyntaxError:
        return HonestyScanResult()
    visitor = _HonestyVisitor(rel_path=rel, lines=lines)
    visitor.visit(tree)
    return HonestyScanResult(findings=visitor.findings)


def _is_honesty_scannable(rel: Path) -> bool:
    posix = rel.as_posix()
    if not posix.startswith("tests/"):
        return False
    if rel.parts[:2] == ("tests", "analyzers") and "fixtures" in rel.parts:
        return False
    return rel.parts[:4] != ("tests", "scripts", "fixtures", "test_honesty")


def iter_test_files(targets: list[Path], *, repo: Path) -> list[Path]:
    """Expand paths to concrete test-tree Python files."""
    files: list[Path] = []
    for target in targets:
        if target.is_file():
            if target.suffix == ".py":
                files.append(target)
            continue
        if not target.is_dir():
            continue
        for path in sorted(target.rglob("*.py")):
            rel = path.relative_to(repo)
            if _is_honesty_scannable(rel):
                files.append(path)
    return files


def _resolve_targets(targets: list[Path], *, repo: Path) -> list[Path]:
    resolved: list[Path] = []
    for target in targets:
        path = Path(target)
        path = (repo / path).resolve() if not path.is_absolute() else path.resolve()
        resolved.append(path)
    return resolved


def scan_paths(targets: list[Path], *, repo: Path) -> HonestyScanResult:
    """Scan many paths and merge findings."""
    merged: list[HonestyFinding] = []
    for path in iter_test_files(_resolve_targets(targets, repo=repo), repo=repo):
        merged.extend(scan_file(path, repo=repo).findings)
    return HonestyScanResult(findings=merged)
