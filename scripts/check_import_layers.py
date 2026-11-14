#!/usr/bin/env python3
"""Enforce the dependency boundaries for the Action entry point and utilities.

Module: scripts.check_import_layers
Depends: ast, importlib.util, pathlib

Exports:
    Functions:
        check_import_layers — Report disallowed static imports across package boundaries.
        main — Run the check against the repository's source tree.
"""

from __future__ import annotations

import ast
import sys
from importlib.util import resolve_name
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "src" / "mergecraft"
_ENTRY_POINT = "mergecraft.main"
_UTILITY_FORBIDDEN = (
    "mergecraft.agents",
    "mergecraft.cli",
    "mergecraft.mcp",
)

# Exact pre-existing imports retained until their callers and types can move.
# A new symbol, a second import of the same symbol, or a stale entry fails the check.
_LEGACY_UTILITY_IMPORTS: dict[str, frozenset[str]] = {
    "utils/agent_resolve.py": frozenset(
        {
            "mergecraft.agents.agents",
            "mergecraft.agents.curated_model_catalog.require_opencode_harness_for_model",
            "mergecraft.agents.openai_compatible_gateways._LEGACY_GATEWAY_PRESETS",
            "mergecraft.agents.openai_compatible_gateways._has_env",
            "mergecraft.agents.openai_compatible_gateways._legacy_gateway_preset_credentials",
            "mergecraft.agents.openai_compatible_gateways._resolve_indexed_providers",
            "mergecraft.agents.registry.AgentRole",
            "mergecraft.agents.registry.load_registry",
            "mergecraft.agents.resolve_agent",
            "mergecraft.agents.shared.Agent",
            "mergecraft.agents.shared.AgentResult",
            "mergecraft.agents.shared.FAILOVER_ELIGIBLE_KEY",
            "mergecraft.mcp.tool_state.ToolState",
        }
    ),
    "utils/code_scanning.py": frozenset({"mergecraft.mcp.context.ToolContext"}),
    "utils/git_setup.py": frozenset(
        {
            "mergecraft.mcp.tool_state.ToolState",
            "mergecraft.mcp.tool_state.primary_repo_state",
            "mergecraft.mcp.tool_state.require_repo_state",
        }
    ),
    "utils/learnings.py": frozenset(
        {
            "mergecraft.mcp.context.ToolContext",
            "mergecraft.mcp.tool_state.ToolState",
        }
    ),
    "utils/review_cost.py": frozenset({"mergecraft.agents.shared.AgentUsage"}),
    "utils/run_bounds.py": frozenset({"mergecraft.agents.shared.AgentUsage"}),
    "utils/status_checks.py": frozenset(
        {
            "mergecraft.agents.gates.approval_decision_inputs",
            "mergecraft.agents.gates.blocking_findings",
            "mergecraft.agents.gates.decision_summary_lines",
            "mergecraft.agents.gates.log_decision",
            "mergecraft.mcp.context.ToolContext",
            "mergecraft.mcp.tool_state.ApprovalRecord",
            "mergecraft.mcp.tool_state.primary_repo_state",
        }
    ),
}


def _imports(tree: ast.AST, package: str) -> Iterator[tuple[int, str]]:
    """Yield imported qualified names with their statement line numbers."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            module = resolve_name("." * node.level + (node.module or ""), package)
            for alias in node.names:
                yield node.lineno, f"{module}.{alias.name}"


def _belongs_to(target: str, layer: str) -> bool:
    """Match the layer itself and names below its dotted package boundary."""
    return target == layer or target.startswith(f"{layer}.")


def check_import_layers(
    root: Path,
    legacy_imports: dict[str, frozenset[str]],
) -> list[str]:
    """Return file and line diagnostics for prohibited imports and stale exceptions."""
    remaining = {path: set(targets) for path, targets in legacy_imports.items()}
    violations = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        name = relative.as_posix()
        layer = relative.parts[0]
        package = ".".join(("mergecraft", *relative.parts[:-1]))
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=name)
        for line, target in _imports(tree, package):
            if layer != "cli" and _belongs_to(target, _ENTRY_POINT):
                violations.append(f"{name}:{line}: only cli/ may import {target}")
            elif name == "errors.py" and _belongs_to(target, "mergecraft"):
                violations.append(f"{name}:{line}: shared errors must not depend on {target}")
            elif layer == "utils" and any(_belongs_to(target, item) for item in _UTILITY_FORBIDDEN):
                exemptions = remaining.get(name)
                if exemptions is not None and target in exemptions:
                    exemptions.remove(target)
                else:
                    violations.append(f"{name}:{line}: utilities must not import {target}")

    for name, targets in sorted(remaining.items()):
        violations.extend(
            f"{name}: remove stale import exception for {target}" for target in sorted(targets)
        )
    return violations


def main() -> int:
    """Print violations and exit nonzero when an import crosses a boundary."""
    violations = check_import_layers(PACKAGE_ROOT, _LEGACY_UTILITY_IMPORTS)
    for violation in violations:
        print(f"src/mergecraft/{violation}", file=sys.stderr)
    return int(bool(violations))


if __name__ == "__main__":
    raise SystemExit(main())
