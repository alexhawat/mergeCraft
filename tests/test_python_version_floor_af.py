"""Batch AF RED — Python 3.11 floor (#343, option A).

Wave plan: ``.ignorelocal/waves/open-issues-sweep-2026-08-20-wave-plan.md``
Authoring wave: **W12** (Batch AF RED). Implementation: **W13-W14** (parenthesize + floor).

Pins (D8):
- Inventory every unparenthesized PEP 758 ``except A, B:`` under ``src/mergecraft/``.
- ``src/mergecraft/`` must compile under Python 3.11 syntax rules (no PEP 758 bare tuples).
- Audit for other 3.14-only APIs (``annotationlib``, PEP 750 t-strings, …) before lowering
  ``requires-python`` to ``>=3.11``.
"""

from __future__ import annotations

import ast
import re
import shutil
import subprocess
import sys
import tokenize
import tomllib
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

import pytest

from tests.ci.workflow_support import REPO_ROOT

_SRC_ROOT = REPO_ROOT / "src" / "mergecraft"
_PYPROJECT = REPO_ROOT / "pyproject.toml"

# W12 baseline @ AEF (0806d47e) — full RED scope before parenthesize.
W12_UNPAREN_EXCEPT_FILE_COUNT = 27
W12_UNPAREN_EXCEPT_SITE_COUNT = 44

# W13: parenthesize all sites except 19e-active analyzer files (D6).
# W14: detect.py parenthesized for 3.11 compile gate (behavior-neutral).
AF343_19E_SKIPPED_EXCEPT_PARENTHESES: frozenset[str] = frozenset()

# Post-W14: no bare PEP 758 except sites remain.
EXPECTED_UNPAREN_EXCEPT_FILE_COUNT = 0
EXPECTED_UNPAREN_EXCEPT_SITE_COUNT = 0

# Patterns that block lowering ``requires-python`` until gated or removed (W12 audit).
_PYTHON314_ONLY_IMPORTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("annotationlib", re.compile(r"\bannotationlib\b")),
)


@dataclass(frozen=True, slots=True)
class UnparenthesizedExceptViolation:
    """A PEP 758 ``except A, B:`` site that is invalid under Python 3.11 syntax."""

    path: str
    line: int
    snippet: str


@dataclass(frozen=True, slots=True)
class Python314OnlyApiHit:
    """A construct that requires Python 3.14+ and blocks the 3.11 floor."""

    kind: str
    path: str
    line: int
    snippet: str


def _except_handler_is_unparenthesized(source: str, handler: ast.ExceptHandler) -> bool:
    if not isinstance(handler.type, ast.Tuple):
        return False
    line = source.splitlines()[handler.lineno - 1]
    rest = line.lstrip()[len("except") :].lstrip()
    return not rest.startswith("(")


def _filter_skipped_except_violations(
    violations: list[UnparenthesizedExceptViolation],
    *,
    skipped: frozenset[str] = AF343_19E_SKIPPED_EXCEPT_PARENTHESES,
) -> list[UnparenthesizedExceptViolation]:
    if not skipped:
        return violations
    return [item for item in violations if item.path not in skipped]


def find_unparenthesized_except_violations(
    root: Path = _SRC_ROOT,
) -> list[UnparenthesizedExceptViolation]:
    """Return PEP 758 bare ``except A, B:`` sites under ``src/mergecraft/``."""
    display_base = REPO_ROOT / "src" if root == _SRC_ROOT else root
    violations: list[UnparenthesizedExceptViolation] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(display_base).as_posix()
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=rel)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if not _except_handler_is_unparenthesized(source, node):
                continue
            segment = ast.get_source_segment(source, node) or source.splitlines()[node.lineno - 1]
            violations.append(
                UnparenthesizedExceptViolation(
                    path=rel,
                    line=node.lineno,
                    snippet=segment.splitlines()[0].strip(),
                )
            )
    return violations


def _find_pep750_t_string_lines(source: str) -> list[int]:
    """Return 1-based line numbers that contain PEP 750 t-string tokens."""
    if not hasattr(tokenize, "TSTRING_START"):
        return []
    tstring_types = {
        tokenize.TSTRING_START,
        tokenize.TSTRING_MIDDLE,
        tokenize.TSTRING_END,
    }
    hits: list[int] = []
    try:
        tokens = tokenize.generate_tokens(StringIO(source).readline)
    except tokenize.TokenError:
        return hits
    for token in tokens:
        if token.type in tstring_types:
            hits.append(token.start[0])
    return hits


def find_python_314_only_api_hits(root: Path = _SRC_ROOT) -> list[Python314OnlyApiHit]:
    """Scan ``src/mergecraft/`` for 3.14-only imports / syntax called out in the W12 audit."""
    display_base = REPO_ROOT / "src" if root == _SRC_ROOT else root
    hits: list[Python314OnlyApiHit] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(display_base).as_posix()
        source = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(source.splitlines(), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            for kind, pattern in _PYTHON314_ONLY_IMPORTS:
                if pattern.search(line):
                    hits.append(
                        Python314OnlyApiHit(
                            kind=kind,
                            path=rel,
                            line=line_no,
                            snippet=stripped,
                        )
                    )
        for line_no in _find_pep750_t_string_lines(source):
            snippet = source.splitlines()[line_no - 1].strip()[:120]
            hits.append(
                Python314OnlyApiHit(
                    kind="pep750-t-string",
                    path=rel,
                    line=line_no,
                    snippet=snippet,
                )
            )
    return hits


def _py_compile_with_interpreter(python: str, path: Path) -> str | None:
    proc = subprocess.run(
        [python, "-m", "py_compile", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        return None
    return (proc.stderr or proc.stdout or f"py_compile failed for {path}").strip()


def _format_violation_lines(
    violations: list[UnparenthesizedExceptViolation], *, limit: int = 20
) -> str:
    return "\n".join(f"{item.path}:{item.line} {item.snippet}" for item in violations[:limit])


def _write_src_module(tmp_path: Path, rel: str, body: str) -> None:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


@pytest.mark.parametrize(
    ("source", "violations"),
    [
        (
            "try:\n    pass\nexcept ValueError, OSError:\n    pass\n",
            1,
        ),
        (
            "try:\n    pass\nexcept (ValueError, OSError):\n    pass\n",
            0,
        ),
        (
            "try:\n    pass\nexcept ValueError:\n    pass\n",
            0,
        ),
    ],
)
def test_find_unparenthesized_except_violations_parametrized(
    tmp_path: Path, source: str, violations: int
) -> None:
    """Scanner flags bare ``except A, B:`` and accepts parenthesized / single-type handlers."""
    if violations and sys.version_info < (3, 14):
        pytest.skip("PEP 758 bare except is a SyntaxError below 3.14; AST scan is N/A")
    src_root = tmp_path / "src" / "mergecraft"
    _write_src_module(src_root, "sample.py", source)
    found = find_unparenthesized_except_violations(src_root)
    assert len(found) == violations


def test_af_w12_inventory_baseline_file_and_site_counts() -> None:
    """W13 inventory — only 19e-skipped files may retain bare except (1 file / 1 site)."""
    violations = find_unparenthesized_except_violations()
    files = {item.path for item in violations}
    assert len(files) == EXPECTED_UNPAREN_EXCEPT_FILE_COUNT
    assert len(violations) == EXPECTED_UNPAREN_EXCEPT_SITE_COUNT
    assert files == set(AF343_19E_SKIPPED_EXCEPT_PARENTHESES)
    assert W12_UNPAREN_EXCEPT_FILE_COUNT == 27
    assert W12_UNPAREN_EXCEPT_SITE_COUNT == 44


def test_af_no_unparenthesized_except_under_src() -> None:
    """Every multi-type ``except`` must be parenthesized for the 3.11 floor (#343)."""
    violations = _filter_skipped_except_violations(find_unparenthesized_except_violations())
    assert not violations, _format_violation_lines(violations)


def test_af_src_compiles_under_python_311_syntax() -> None:
    """``src/mergecraft/**/*.py`` must compile on Python 3.11 (PEP 758 bare tuples forbidden)."""
    skipped_paths = {
        (REPO_ROOT / "src" / rel).resolve() for rel in AF343_19E_SKIPPED_EXCEPT_PARENTHESES
    }
    python311 = shutil.which("python3.11")
    if python311 is not None:
        failures: list[str] = []
        for path in sorted(_SRC_ROOT.rglob("*.py")):
            if path.resolve() in skipped_paths:
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            error = _py_compile_with_interpreter(python311, path)
            if error is not None:
                failures.append(f"{rel}: {error.splitlines()[-1]}")
        assert not failures, "\n".join(failures[:20])
        return

    # Host may be 3.14 — fall back to the static PEP 758 inventory (same failure surface).
    violations = _filter_skipped_except_violations(find_unparenthesized_except_violations())
    assert not violations, (
        "python3.11 not on PATH; static PEP 758 scan found bare except tuples:\n"
        + _format_violation_lines(violations)
    )


def test_af_no_python_314_only_apis_block_floor() -> None:
    """W12 audit — no ``annotationlib`` / PEP 750 t-strings under ``src/mergecraft/``."""
    hits = find_python_314_only_api_hits()
    assert not hits, "\n".join(
        f"{item.kind} {item.path}:{item.line} {item.snippet}" for item in hits[:12]
    )


def test_af_pyproject_requires_python_floor_is_311() -> None:
    """``requires-python`` must be lowered to ``>=3.11`` once parenthesize + audit land (W14)."""
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    requires = data["project"]["requires-python"]
    assert requires == ">=3.11", f"expected >=3.11, got {requires!r}"


__all__ = [
    "AF343_19E_SKIPPED_EXCEPT_PARENTHESES",
    "EXPECTED_UNPAREN_EXCEPT_FILE_COUNT",
    "EXPECTED_UNPAREN_EXCEPT_SITE_COUNT",
    "W12_UNPAREN_EXCEPT_FILE_COUNT",
    "W12_UNPAREN_EXCEPT_SITE_COUNT",
    "Python314OnlyApiHit",
    "UnparenthesizedExceptViolation",
    "_filter_skipped_except_violations",
    "find_python_314_only_api_hits",
    "find_unparenthesized_except_violations",
    "test_af_no_python_314_only_apis_block_floor",
    "test_af_no_unparenthesized_except_under_src",
    "test_af_pyproject_requires_python_floor_is_311",
    "test_af_src_compiles_under_python_311_syntax",
    "test_af_w12_inventory_baseline_file_and_site_counts",
    "test_find_unparenthesized_except_violations_parametrized",
]
