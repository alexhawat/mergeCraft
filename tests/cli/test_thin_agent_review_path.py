"""W9 / #383 — thin integrations: one review path, no per-agent fork.

Wave plan: ``.ignorelocal/waves/open-issues-sweep-2026-08-20d-a-engine-wave-plan.md``
(W9.3). Source/AST pin only for agent-name forks — not a live LLM test.
Packaging Codex/Gemini/OpenCode is out of scope (file 8 RV3).
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.ci.workflow_support import REPO_ROOT

from mergecraft.offline_review import run_offline_diff_review
from mergecraft.review import ReviewEngine

_AGENT_FORK_VALUES: frozenset[str] = frozenset({"codex", "gemini", "opencode", "cursor", "claude"})
_REVIEW_PATH_FILES: tuple[Path, ...] = (
    REPO_ROOT / "src" / "mergecraft" / "cli" / "diff_review_cmd.py",
    REPO_ROOT / "src" / "mergecraft" / "cli" / "agent_protocol.py",
    REPO_ROOT / "src" / "mergecraft" / "review" / "engine.py",
    REPO_ROOT / "src" / "mergecraft" / "offline_review.py",
)


def _compare_constants(node: ast.Compare) -> list[str]:
    values: list[str] = []
    for comparator in (node.left, *node.comparators):
        if isinstance(comparator, ast.Constant) and isinstance(comparator.value, str):
            values.append(comparator.value)
    return values


def _is_agent_name(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id in {"agent", "agent_id", "agent_binary"}
    return isinstance(node, ast.Attribute) and node.attr in {
        "agent",
        "agent_id",
        "agent_binary",
    }


def _agent_behaviour_forks(source: str) -> list[str]:
    """Return ``if agent == "codex"``-style comparisons that fork review behaviour."""
    tree = ast.parse(source)
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        constants = [value for value in _compare_constants(node) if value in _AGENT_FORK_VALUES]
        if not constants:
            continue
        operands = (node.left, *node.comparators)
        if any(_is_agent_name(operand) for operand in operands):
            hits.append(f"agent compared to {constants!r}")
    return hits


def test_review_entry_is_not_forked_per_agent_binary() -> None:
    """Happy: CLI review admits ``run_offline_diff_review`` once; no per-agent fork."""
    from mergecraft.cli import diff_review_cmd

    assert callable(diff_review_cmd.run)
    assert callable(run_offline_diff_review)
    source = (REPO_ROOT / "src" / "mergecraft" / "cli" / "diff_review_cmd.py").read_text(
        encoding="utf-8"
    )
    assert "run_offline_diff_review" in source
    forks = _agent_behaviour_forks(source)
    assert not forks, f"diff_review_cmd forks review behaviour per agent: {forks}"


def test_cli_agent_review_path_has_no_per_agent_behaviour_fork() -> None:
    """Edge: no ``if agent == "codex":`` (or sibling) in the agent/review CLI path."""
    missing: list[str] = []
    forks: list[str] = []
    for path in _REVIEW_PATH_FILES:
        if not path.is_file():
            missing.append(str(path.relative_to(REPO_ROOT)))
            continue
        hits = _agent_behaviour_forks(path.read_text(encoding="utf-8"))
        forks.extend(f"{path.relative_to(REPO_ROOT)}: {hit}" for hit in hits)
    assert not missing, f"review path files missing: {missing}"
    assert not forks, f"per-agent review-behaviour forks: {forks}"


def test_shared_engine_callable_is_agent_agnostic() -> None:
    """Unit: ``ReviewEngine`` does not branch on agent binary."""
    source = (REPO_ROOT / "src" / "mergecraft" / "review" / "engine.py").read_text(encoding="utf-8")
    assert "class ReviewEngine" in source
    forks = _agent_behaviour_forks(source)
    assert not forks, f"ReviewEngine forks per agent: {forks}"
    assert "codex" not in source
    assert "gemini" not in source
    assert "opencode" not in source
    assert "cursor" not in source
    snapshot = __import__(
        "mergecraft.review.snapshot", fromlist=["canonical_review_snapshot"]
    ).canonical_review_snapshot(entry="cli")
    engine = ReviewEngine(snapshot=snapshot)
    assert engine.snapshot.entry == "cli"
