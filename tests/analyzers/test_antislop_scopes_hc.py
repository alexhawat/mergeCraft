"""Batch HC RED — antislop scopes wiring #423.

Pins that ``__init__.py`` and ``matcher.py`` import shared suffix constants
from ``scopes.py`` instead of maintaining duplicate local tuples. Implementation
lands in W6 (D3).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from mergecraft.analyzers.antislop import scopes
from mergecraft.analyzers.antislop.matcher import apply_rules
from mergecraft.analyzers.antislop.policy import load_native_rules

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ANTISLOP_DIR = _REPO_ROOT / "src" / "mergecraft" / "analyzers" / "antislop"
_INIT_PATH = _ANTISLOP_DIR / "__init__.py"
_MATCHER_PATH = _ANTISLOP_DIR / "matcher.py"
_SCOPES_PATH = _ANTISLOP_DIR / "scopes.py"

_RULES = load_native_rules()

_SCOPED_IMPORT = "ANTISLOP_SCOPED_SUFFIXES"
_JS_IMPORT = "ANTISLOP_JS_SUFFIXES"


def _module_ast(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports_name_from_scopes(path: Path, name: str) -> bool:
    tree = _module_ast(path)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module not in {"mergecraft.analyzers.antislop.scopes", "scopes", ".scopes"}:
            continue
        if any(alias.name == name for alias in node.names):
            return True
    return False


def _defines_module_level_name(path: Path, name: str) -> bool:
    tree = _module_ast(path)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return True
    return False


# --- #423 import contract (RED until W6) -------------------------------------


@pytest.mark.xfail(
    reason="green after W6: import ANTISLOP_SCOPED_SUFFIXES from scopes (#423)",
    strict=False,
)
def test_init_imports_antislop_scoped_suffixes_from_scopes() -> None:
    """``__init__.py`` must import the shared scoped suffix tuple from ``scopes``."""
    assert _imports_name_from_scopes(_INIT_PATH, _SCOPED_IMPORT)


@pytest.mark.xfail(
    reason="green after W6: delete local _SCOPED_SUFFIXES duplicate (#423)",
    strict=False,
)
def test_init_does_not_define_local_scoped_suffixes() -> None:
    """``__init__.py`` must not keep a module-local ``_SCOPED_SUFFIXES`` copy."""
    assert not _defines_module_level_name(_INIT_PATH, "_SCOPED_SUFFIXES")


@pytest.mark.xfail(
    reason="green after W6: import ANTISLOP_JS_SUFFIXES from scopes (#423)",
    strict=False,
)
def test_matcher_imports_antislop_js_suffixes_from_scopes() -> None:
    """``matcher.py`` must import the shared JS suffix set from ``scopes``."""
    assert _imports_name_from_scopes(_MATCHER_PATH, _JS_IMPORT)


@pytest.mark.xfail(
    reason="green after W6: delete local _JS_SUFFIXES duplicate (#423)",
    strict=False,
)
def test_matcher_does_not_define_local_js_suffixes() -> None:
    """``matcher.py`` must not keep a module-local ``_JS_SUFFIXES`` copy."""
    assert not _defines_module_level_name(_MATCHER_PATH, "_JS_SUFFIXES")


# --- compatibility pins (pass on baseline; guard W6 refactor) ----------------


def test_scopes_module_exports_shared_suffix_constants() -> None:
    """``scopes.py`` remains the canonical suffix definitions (#423)."""
    assert _SCOPES_PATH.is_file()
    assert scopes.ANTISLOP_SCOPED_SUFFIXES == (
        ".py",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".mjs",
        ".cjs",
    )
    assert frozenset({".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}) == scopes.ANTISLOP_JS_SUFFIXES
    assert set(scopes.__all__) == {_SCOPED_IMPORT, _JS_IMPORT}


@pytest.mark.parametrize("suffix", scopes.ANTISLOP_SCOPED_SUFFIXES)
def test_every_scoped_suffix_is_scanned(tmp_path: Path, suffix: str) -> None:
    """Each scoped suffix must still reach ``scan_changed_files`` after wiring."""
    from mergecraft.analyzers.antislop import scan_changed_files

    rel = f"src/sample{suffix}"
    repo = tmp_path / "repo"
    target = repo / rel
    target.parent.mkdir(parents=True)
    if suffix == ".py":
        target.write_text("# Step 1: load\n", encoding="utf-8")
    else:
        target.write_text("// Step 1: load\n", encoding="utf-8")

    result = scan_changed_files(repo_root=repo, changed_files=[rel])
    assert not result.skipped, result.skip_reason


@pytest.mark.parametrize("suffix", sorted(scopes.ANTISLOP_JS_SUFFIXES))
def test_every_js_suffix_reaches_matcher(suffix: str) -> None:
    """Each JS-family suffix must still classify as a JS/TS language path."""
    source = "try {\n  load();\n} catch (e) {\n}\n"
    rel = f"src/sample{suffix}"
    matches = apply_rules(rel_path=rel, source=source, rules=_RULES)
    assert any(match.rule.rule_id == "antislop/empty-error-handler" for match in matches)
