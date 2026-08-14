"""Drift guard: every artifact path a prompt promises must be produced by a tool.

A prompt that names an artifact key no MCP tool ever returns costs tokens, invites
hallucinated compliance, and silently drops the step it claims to run. Two such
keys shipped this way (`impactPath`, `incrementalDiffPath`), so the contract is
now checked mechanically rather than by reading prompts.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Final

from mergecraft.agents.reviewer import REVIEWER_SYSTEM_PROMPT
from mergecraft.modes import compute_modes
from mergecraft.types import AgentId

_MCP_DIR: Final[Path] = Path(__file__).resolve().parent.parent / "src" / "mergecraft" / "mcp"

# An artifact key is a backticked camelCase identifier ending in `Path` — the
# shape every on-disk handoff between a tool result and a prompt uses.
_ARTIFACT_KEY_RE: Final[re.Pattern[str]] = re.compile(r"`([a-z][A-Za-z0-9]*Path)`")
_KEY_SHAPE_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][A-Za-z0-9]*Path$")

_AGENT_IDS: Final[tuple[AgentId, ...]] = ("claude", "opencode")


def _prompt_sources() -> dict[str, str]:
    """Return every prompt that can name a tool artifact, keyed for error messages."""
    sources = {"agents/reviewer.py::REVIEWER_SYSTEM_PROMPT": REVIEWER_SYSTEM_PROMPT}
    for agent_id in _AGENT_IDS:
        for mode in compute_modes(agent_id):
            sources[f"modes.py::{mode.name} ({agent_id})"] = mode.prompt or ""
    return sources


def _artifact_keys(text: str) -> set[str]:
    return set(_ARTIFACT_KEY_RE.findall(text))


def _keys_produced_by_mcp_tools() -> set[str]:
    """Return every artifact-shaped string literal appearing in an MCP tool module.

    A superset of the keys tools actually return — string literals are collected
    without tracking which dict they land in. That keeps the check robust against
    refactors while still catching the failure that matters: a prompt naming a key
    that appears nowhere in the tool layer at all.
    """
    produced: set[str] = set()
    for module in sorted(_MCP_DIR.glob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        for node in ast.walk(tree):
            is_key = isinstance(node, ast.Constant) and isinstance(node.value, str)
            if is_key and _KEY_SHAPE_RE.match(node.value):
                produced.add(node.value)
    return produced


def test_mcp_layer_produces_the_known_diff_artifacts() -> None:
    """Guards the guard: a scan that silently found nothing would pass vacuously."""
    produced = _keys_produced_by_mcp_tools()
    assert "diffPath" in produced
    assert "incrementalDiffPath" in produced
    assert "impactPath" in produced, (
        "impactPath landed in checkout_pr but was not detected; rerun drift check"
    )


def test_every_prompt_artifact_key_is_returned_by_some_mcp_tool() -> None:
    produced = _keys_produced_by_mcp_tools()
    dangling: dict[str, set[str]] = {}
    for label, text in _prompt_sources().items():
        missing = _artifact_keys(text) - produced
        if missing:
            dangling[label] = missing
    assert not dangling, "prompt promises artifact key(s) no MCP tool returns: " + "; ".join(
        f"{label}: {sorted(keys)}" for label, keys in sorted(dangling.items())
    )
