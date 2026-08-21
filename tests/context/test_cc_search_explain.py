"""W8 / W11 — context search, explain, budgets, omissions (#356).

Does not re-test repo map / symbol index / graphs / git history (issue out of scope).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE, CLI_USAGE_EXIT_CODE
from tests.support.cc_batch import invoke, load_module, plain, require_callable, require_registered
from tests.support.dead_package_wiring import SRC_ROOT

_W11 = pytest.mark.xfail(
    reason="green after W11: context search/explain/budgets (#356)",
    strict=False,
)


def test_retrieval_half_already_ships_under_context() -> None:
    """#356 out of scope — retrieval half is already shipped (current state)."""
    for name in (
        "repo_map.py",
        "symbol_index.py",
        "call_graph.py",
        "change_graph.py",
        "git_history.py",
    ):
        assert (SRC_ROOT / "context" / name).is_file()


def test_context_search_is_currently_a_usage_error() -> None:
    """W8 current state: ``context search`` is not registered."""
    result = invoke("context", "search", "--help")
    assert result.exit_code == CLI_USAGE_EXIT_CODE, plain(result.stdout + result.stderr)


def test_context_explain_is_currently_a_usage_error() -> None:
    """W8 current state: ``context explain`` is not registered."""
    result = invoke("context", "explain", "--help")
    assert result.exit_code == CLI_USAGE_EXIT_CODE, plain(result.stdout + result.stderr)


@_W11
def test_context_search_help_is_registered() -> None:
    """#356 — ``mergecraft context search`` exists."""
    result = require_registered("context", "search", "--help", label="mergecraft context search")
    help_text = plain(result.stdout + result.stderr).casefold()
    assert "search" in help_text


@_W11
def test_context_explain_help_is_registered() -> None:
    """#356 — ``mergecraft context explain`` exists."""
    result = require_registered("context", "explain", "--help", label="mergecraft context explain")
    help_text = plain(result.stdout + result.stderr).casefold()
    assert "explain" in help_text


@_W11
def test_context_search_unknown_query_is_an_error(tmp_path: Path) -> None:
    """Error: empty/unknown search query is non-success."""
    require_registered("context", "search", "--help", label="mergecraft context search")
    result = invoke("context", "search", "", "--repo-root", str(tmp_path))
    combined = plain(result.stdout + result.stderr)
    assert result.exit_code != CLI_SUCCESS_EXIT_CODE, combined


@_W11
def test_context_relevance_scoring() -> None:
    """#356 — retrieved items carry a relevance score."""
    module = load_module("mergecraft.context.operator")
    score = require_callable(module, "score_relevance")
    high = score(query="timeout retry", item={"text": "retry loop has no timeout"})
    low = score(query="timeout retry", item={"text": "rename a local variable"})
    assert high > low


@_W11
def test_context_budget_allocation_per_specialist() -> None:
    """#356 — context budgets are allocated per specialist."""
    module = load_module("mergecraft.context.operator")
    allocate = require_callable(module, "allocate_specialist_budgets")
    budgets = allocate(specialists=["security", "correctness"], total_tokens=8000)
    assert set(budgets) >= {"security", "correctness"}
    assert sum(int(value) for value in budgets.values()) <= 8000


@_W11
def test_lazy_context_retrieval_goes_through_controlled_tools() -> None:
    """#356 — lazy retrieval is tool-gated, not a bulk dump."""
    module = load_module("mergecraft.context.operator")
    retrieve = require_callable(module, "lazy_retrieve")
    result = retrieve(query="callers of process", tools_allowed=("search",))
    assert result
    denied = retrieve(query="callers of process", tools_allowed=())
    assert not denied or getattr(denied, "omitted", False)


@_W11
def test_context_omission_reporting_downgrades_the_outcome() -> None:
    """#356 — omitted scope is recorded and the outcome is downgraded."""
    module = load_module("mergecraft.context.operator")
    report = require_callable(module, "report_omissions")(
        requested=["src/app.py:process"],
        retrieved=[],
    )
    omitted = getattr(report, "omitted", report)
    assert omitted
    outcome = getattr(report, "outcome", None) or require_callable(
        module, "downgrade_for_omissions"
    )(
        "supported",
        omitted=omitted,
    )
    assert str(outcome) != "proven"


@_W11
def test_context_retrieval_quality_is_benchmarked_separately_from_models() -> None:
    """#356 — retrieval quality benchmark does not score the LLM."""
    module = load_module("mergecraft.context.operator")
    report = require_callable(module, "evaluate_retrieval_quality")()
    assert getattr(report, "model_quality", None) in {None, False}
    score = getattr(report, "retrieval_score", None)
    assert score is not None
    assert 0.0 <= float(score) <= 1.0
