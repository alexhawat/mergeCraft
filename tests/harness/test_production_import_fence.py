"""RH1.1 pin — production code must not import the test-only provider harness (D2)."""

from __future__ import annotations

import ast
from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "mergecraft"
_FORBIDDEN = frozenset(
    {
        "tests.support.provider_harness",
        "provider_harness",
    }
)


def _imports_provider_harness(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if any(token in alias.name for token in _FORBIDDEN):
                    hits.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            if any(token in node.module for token in _FORBIDDEN):
                hits.append(f"from {node.module} import …")
            for alias in node.names:
                if alias.name == "provider_harness":
                    hits.append(f"from {node.module} import {alias.name}")
    return hits


def test_src_mergecraft_does_not_import_provider_harness() -> None:
    """No ``src/mergecraft/**/*.py`` may reference ``tests.support.provider_harness``."""
    violations: list[str] = []
    for path in sorted(_SRC_ROOT.rglob("*.py")):
        hits = _imports_provider_harness(path)
        if hits:
            rel = path.relative_to(_SRC_ROOT)
            violations.append(f"{rel}: {', '.join(hits)}")
    assert violations == []
