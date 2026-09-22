"""R6 — CLI JSON schema version is independent of the review snapshot version (#777).

Wave plan: ``.ignorelocal/waves/30-verification-evals-receipts-wave-plan.md``
Branch: ``wave/evals-second-target``. Authoring wave: **R6** (``test-creator``).
Trace run.id: ``f8c575d3-5a2f-433a-9e6a-8c978fcd25d9``.

``CLI_JSON_SCHEMA_VERSION`` (``cli/global_surface.py``) and
``REVIEW_SCHEMA_VERSION`` (``review/snapshot.py``) version two different
contracts — every CLI ``--json`` payload and the frozen ``ReviewSnapshot``
model — and each must be able to move without falsely signalling a change to
the other. Decision **R-D9** decouples them **at the same value**: the constant
is defined in ``cli/`` at ``"1.0.0"``, no payload moves, and ``review/`` still
does not import ``cli/``.

The structural pins below are deliberately **RED** until R6 replaces the alias
``from mergecraft.review.snapshot import REVIEW_SCHEMA_VERSION as
CLI_JSON_SCHEMA_VERSION`` with a local assignment. They are **not** ``xfail``:
the implementation wave greens them in the same wave, and the existing literal
pin at ``tests/cli/test_da_protocol_negotiation.py`` is left untouched.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import TYPE_CHECKING

from mergecraft.cli import global_surface as global_surface_mod
from mergecraft.cli.global_surface import CLI_JSON_SCHEMA_VERSION, cli_json_dumps
from mergecraft.review import snapshot as snapshot_mod

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

_SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "mergecraft"
_GLOBAL_SURFACE_PATH = _SRC_ROOT / "cli" / "global_surface.py"
_REVIEW_ROOT = _SRC_ROOT / "review"

_EXPECTED_VERSION = "1.0.0"
_BUMPED_SENTINEL = "9.9.9"


def _module_assignments(tree: ast.Module) -> dict[str, ast.expr]:
    """Map module-level assigned names to their value expression (``None`` skipped)."""
    assignments: dict[str, ast.expr] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments[target.id] = node.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.value is not None
        ):
            assignments[node.target.id] = node.value
    return assignments


def _imported_bindings(tree: ast.Module) -> dict[str, str]:
    """Map each local import binding to ``<module>:<original name>``."""
    bindings: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                bindings[alias.asname or alias.name] = f"{module}:{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                bindings[local] = f"{alias.name}:"
    return bindings


def _imports_cli(path: Path) -> list[str]:
    """Return every ``mergecraft.cli`` import form found in ``path`` (AST, not text)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "mergecraft.cli" or module.startswith("mergecraft.cli."):
                hits.append(f"from {module} import …")
            elif module == "mergecraft" and any(alias.name == "cli" for alias in node.names):
                hits.append("from mergecraft import cli")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "mergecraft.cli" or alias.name.startswith("mergecraft.cli."):
                    hits.append(f"import {alias.name}")
    return hits


# ── R6.1 — the constant is defined in cli/, not aliased from review/ ──────────


def test_cli_json_schema_version_is_assigned_in_global_surface() -> None:
    """R6: ``CLI_JSON_SCHEMA_VERSION`` is a module-level assignment in ``cli/global_surface.py``.

    RED today: the module aliases the review snapshot constant instead of
    defining its own, so there is no module-level assignment to find.
    """
    tree = ast.parse(_GLOBAL_SURFACE_PATH.read_text(encoding="utf-8"))
    assignments = _module_assignments(tree)
    assert "CLI_JSON_SCHEMA_VERSION" in assignments, (
        "CLI_JSON_SCHEMA_VERSION must be assigned directly in cli/global_surface.py; "
        "it is currently imported from mergecraft.review.snapshot"
    )
    value = assignments["CLI_JSON_SCHEMA_VERSION"]
    assert isinstance(value, ast.Constant), (
        "CLI_JSON_SCHEMA_VERSION must be a literal assignment, not a re-export of another "
        f"name (found {type(value).__name__})"
    )
    assert value.value == _EXPECTED_VERSION


def test_cli_json_schema_version_is_not_an_imported_binding() -> None:
    """R6 structural: the name is absent from the module's imported bindings.

    RED today: ``from mergecraft.review.snapshot import REVIEW_SCHEMA_VERSION as
    CLI_JSON_SCHEMA_VERSION`` binds the name at import.
    """
    tree = ast.parse(_GLOBAL_SURFACE_PATH.read_text(encoding="utf-8"))
    bindings = _imported_bindings(tree)
    assert "CLI_JSON_SCHEMA_VERSION" not in bindings, (
        "CLI_JSON_SCHEMA_VERSION is imported as "
        f"{bindings.get('CLI_JSON_SCHEMA_VERSION')!r}; it must be defined locally"
    )


# ── R6.2 — the two constants are independent ─────────────────────────────────


def test_mutating_review_schema_version_does_not_move_the_cli_stamp(
    monkeypatch: MonkeyPatch,
) -> None:
    """R6: bumping ``REVIEW_SCHEMA_VERSION`` must not change what ``cli_json_dumps`` stamps."""
    monkeypatch.setattr(snapshot_mod, "REVIEW_SCHEMA_VERSION", _BUMPED_SENTINEL)
    payload = json.loads(cli_json_dumps({"ok": True}))
    assert payload["schema_version"] == _EXPECTED_VERSION
    assert payload["schema_version"] != _BUMPED_SENTINEL


def test_mutating_cli_json_schema_version_does_not_move_the_review_version(
    monkeypatch: MonkeyPatch,
) -> None:
    """R6: bumping the CLI constant must not move ``REVIEW_SCHEMA_VERSION``."""
    monkeypatch.setattr(global_surface_mod, "CLI_JSON_SCHEMA_VERSION", _BUMPED_SENTINEL)
    assert snapshot_mod.REVIEW_SCHEMA_VERSION == _EXPECTED_VERSION


# ── R6.3 — same value, no payload moved ──────────────────────────────────────


def test_both_schema_versions_hold_the_same_value() -> None:
    """R-D9: decoupled at the same value — no consumer sees a bump."""
    assert CLI_JSON_SCHEMA_VERSION == _EXPECTED_VERSION
    assert snapshot_mod.REVIEW_SCHEMA_VERSION == _EXPECTED_VERSION
    assert CLI_JSON_SCHEMA_VERSION == snapshot_mod.REVIEW_SCHEMA_VERSION


def test_cli_json_dumps_still_stamps_1_0_0() -> None:
    """R-D9: the chokepoint stamps the same literal after decoupling."""
    payload = json.loads(cli_json_dumps({"ok": True}))
    assert payload["schema_version"] == "1.0.0"


# ── R6.4 — the layering rule holds ───────────────────────────────────────────


def test_review_package_does_not_import_cli() -> None:
    """R6 layering: no module under ``src/mergecraft/review/`` imports ``mergecraft.cli``."""
    violations: list[str] = []
    for path in sorted(_REVIEW_ROOT.rglob("*.py")):
        hits = _imports_cli(path)
        if hits:
            rel = path.relative_to(_REVIEW_ROOT)
            violations.append(f"{rel}: {', '.join(hits)}")
    assert violations == []
