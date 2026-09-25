"""``pyproject.toml`` must declare every third-party import and nothing unused.

The source tree imports ``click`` and the private ``httpcore`` backend without
declaring either, while ``markdownify`` and ``aiofiles`` are declared and
imported nowhere. PyJWT is the only runtime dependency with a range instead of
an exact pin. This module pins the dependency contract in both directions:

- every third-party top-level import in ``src/mergecraft/`` maps to a declared
  direct dependency (runtime or an extra), and
- every declared runtime dependency is imported somewhere or allowlisted with
  a written reason, and every runtime specifier is an exact ``==`` pin.
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from importlib.metadata import packages_distributions
from typing import Final

from tests.ci.workflow_support import REPO_ROOT

_PYPROJECT: Final = REPO_ROOT / "pyproject.toml"
_SOURCE_ROOT: Final = REPO_ROOT / "src" / "mergecraft"

# Runtime dependencies that are deliberately declared without a direct import.
# Each entry must say why; an unexplained entry fails the test below.
_ALLOWLISTED_RUNTIME: Final[dict[str, str]] = {
    "anyio": "transitive runtime requirement of httpx and starlette; the exact pin is policy",
    "pydantic-settings": (
        "the settings migration adopts it later; declared ahead of the first import"
    ),
}

_NAME_SPLIT: Final = re.compile(r"[<>=!~\[; ]")
_REQUIREMENT: Final = re.compile(
    r"^(?P<name>[A-Za-z0-9._-]+)(?P<extras>\[[^\]]*\])?\s*(?P<spec>.*)$"
)


def _normalize(name: str) -> str:
    return name.lower().replace("_", "-").replace(".", "-")


def _requirement_name(requirement: str) -> str:
    return _normalize(_NAME_SPLIT.split(requirement.strip(), maxsplit=1)[0])


def _runtime_requirements() -> list[str]:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    return list(data["project"]["dependencies"])


def _declared_distributions() -> set[str]:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    declared = {_requirement_name(entry) for entry in data["project"]["dependencies"]}
    for requirements in data["project"].get("optional-dependencies", {}).values():
        declared.update(_requirement_name(entry) for entry in requirements)
    return declared


def _import_roots() -> dict[str, set[str]]:
    roots: dict[str, set[str]] = {}
    for path in sorted(_SOURCE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    roots.setdefault(alias.name.split(".")[0], set()).add(
                        str(path.relative_to(REPO_ROOT))
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.level or not node.module:
                    continue
                roots.setdefault(node.module.split(".")[0], set()).add(
                    str(path.relative_to(REPO_ROOT))
                )
    return roots


def _third_party_roots() -> dict[str, set[str]]:
    stdlib = set(sys.stdlib_module_names)
    return {
        root: files
        for root, files in _import_roots().items()
        if root not in stdlib and root != "mergecraft" and not root.startswith("_")
    }


def _resolves(root: str, mapping: dict[str, list[str]], declared: set[str]) -> bool:
    """True when a top-level module belongs to a declared distribution."""
    installed = [_normalize(name) for name in mapping.get(root, [])]
    if installed:
        return any(name in declared for name in installed)
    # An optional extra that is not installed has no metadata to map through;
    # fall back to the distribution name the module ships under.
    normalized = _normalize(root)
    return normalized in declared or any(name.startswith(f"{normalized}-") for name in declared)


def test_every_third_party_import_is_declared() -> None:
    declared = _declared_distributions()
    mapping = packages_distributions()
    undeclared = {
        root: sorted(files)
        for root, files in _third_party_roots().items()
        if not _resolves(root, mapping, declared)
    }
    assert not undeclared, (
        f"these third-party imports are not backed by a declared direct dependency: {undeclared}"
    )


def test_every_runtime_dependency_is_used_or_allowlisted() -> None:
    mapping = packages_distributions()
    imported: set[str] = set()
    for root in _third_party_roots():
        imported.update(_normalize(name) for name in mapping.get(root, []))
    unused = [
        name
        for name in sorted({_requirement_name(entry) for entry in _runtime_requirements()})
        if name not in imported and name not in _ALLOWLISTED_RUNTIME
    ]
    assert not unused, (
        "declared runtime dependencies with no import and no allowlist reason: "
        f"{unused}; remove them or add a reasoned allowlist entry"
    )
    for name, reason in _ALLOWLISTED_RUNTIME.items():
        assert reason.strip(), f"allowlisted dependency {name} needs a written reason"


def test_runtime_specifiers_are_exact_pins() -> None:
    loose: dict[str, str] = {}
    for requirement in _runtime_requirements():
        head = requirement.split(";", 1)[0].strip()
        match = _REQUIREMENT.match(head)
        assert match is not None, f"cannot parse requirement {requirement!r}"
        specifier = match.group("spec").strip()
        if not specifier.startswith("=="):
            loose[match.group("name").lower()] = requirement.strip()
    assert not loose, (
        f"every runtime dependency must be an exact == pin (uv.lock is the resolver): {loose}"
    )
