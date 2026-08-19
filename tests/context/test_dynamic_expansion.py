"""DG4 dynamic expansion — on-demand scope retrieval within budget (CC3).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG4).
Implementation: **DG4.2** — ``mergecraft.context.dynamic_expansion``.
"""

from __future__ import annotations

from pathlib import Path

from mergecraft.utils.run_bounds import BudgetTracker, RunBounds
from tests.context.support import (
    git_commit_all,
    git_init_repo,
    import_context_module,
    write_dynamic_expansion_fixture_repo,
)


def _tight_bounds() -> RunBounds:
    return RunBounds(
        token_budget=40,
        cost_budget_usd=1.0,
        tool_call_budget=10,
        run_timeout_s=60.0,
        context_retrieval_timeout_s=5.0,
        max_diff_lines=10_000,
        external_operation_timeout_s=30.0,
    )


def test_enclosing_scope_is_retrieved_on_demand(tmp_path: Path) -> None:
    """Dynamic expansion retrieves the enclosing scope for a symbol on demand."""
    repo_root = tmp_path / "repo"
    write_dynamic_expansion_fixture_repo(repo_root)
    git_init_repo(repo_root)
    git_commit_all(repo_root)

    expansion_mod = import_context_module("dynamic_expansion")
    result = expansion_mod.expand_enclosing_scope(
        repo_root=repo_root,
        path="src/demo/widget.py",
        symbol="Widget.render",
    )

    combined = "\n".join(item.text for item in result.items)
    assert "class Widget" in combined
    assert "def render" in combined
    assert all(item.path == "src/demo/widget.py" for item in result.items)
    assert all(item.reason == "dynamic_expansion" for item in result.items)


def test_expansion_respects_the_token_budget(tmp_path: Path) -> None:
    """Dynamic expansion stops before exceeding the per-run token budget (CC3)."""
    repo_root = tmp_path / "repo"
    write_dynamic_expansion_fixture_repo(repo_root)
    git_init_repo(repo_root)
    git_commit_all(repo_root)

    expansion_mod = import_context_module("dynamic_expansion")
    tracker = BudgetTracker(_tight_bounds())
    result = expansion_mod.expand_with_budget(
        repo_root=repo_root,
        path="src/demo/widget.py",
        symbol="Widget",
        token_budget=tracker.bounds.token_budget,
        budget_tracker=tracker,
    )

    assert result.truncated is True
    assert result.token_cost <= tracker.bounds.token_budget
    assert tracker.tokens_used <= tracker.bounds.token_budget
    assert tracker.last_exhausted is None


def test_expansion_truncates_without_raising_budget_exhausted(tmp_path: Path) -> None:
    """Shared budget trackers are not exhausted by dynamic expansion clipping."""
    repo_root = tmp_path / "repo"
    write_dynamic_expansion_fixture_repo(repo_root)
    git_init_repo(repo_root)
    git_commit_all(repo_root)

    expansion_mod = import_context_module("dynamic_expansion")
    tracker = BudgetTracker(_tight_bounds())
    tracker.tokens_used = tracker.bounds.token_budget - 1

    result = expansion_mod.expand_with_budget(
        repo_root=repo_root,
        path="src/demo/widget.py",
        symbol="Widget",
        token_budget=tracker.bounds.token_budget,
        budget_tracker=tracker,
    )

    assert result.truncated is True
    assert tracker.last_exhausted is None
