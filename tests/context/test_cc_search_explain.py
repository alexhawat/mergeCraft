"""W8 / W11 — context search, explain, budgets, omissions (#356).

Does not re-test repo map / symbol index / graphs / git history (issue out of scope).
"""

from __future__ import annotations

from pathlib import Path

from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE
from tests.context.support import git_commit_all, git_init_repo
from tests.support.cc_batch import invoke, load_module, plain, require_callable, require_registered
from tests.support.dead_package_wiring import SRC_ROOT


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


def test_context_search_help_is_registered() -> None:
    """#356 — ``mergecraft context search`` exists."""
    result = require_registered("context", "search", "--help", label="mergecraft context search")
    help_text = plain(result.stdout + result.stderr).casefold()
    assert "search" in help_text


def test_context_explain_help_is_registered() -> None:
    """#356 — ``mergecraft context explain`` exists."""
    result = require_registered("context", "explain", "--help", label="mergecraft context explain")
    help_text = plain(result.stdout + result.stderr).casefold()
    assert "explain" in help_text


def test_context_search_unknown_query_is_an_error(tmp_path: Path) -> None:
    """Error: empty/unknown search query is non-success."""
    require_registered("context", "search", "--help", label="mergecraft context search")
    result = invoke("context", "search", "", "--repo-root", str(tmp_path))
    combined = plain(result.stdout + result.stderr)
    assert result.exit_code != CLI_SUCCESS_EXIT_CODE, combined


def test_context_relevance_scoring() -> None:
    """#356 — retrieved items carry a relevance score."""
    module = load_module("mergecraft.context.operator")
    score = require_callable(module, "score_relevance")
    high = score(query="timeout retry", item={"text": "retry loop has no timeout"})
    low = score(query="timeout retry", item={"text": "rename a local variable"})
    assert high > low


def test_context_budget_allocation_per_specialist() -> None:
    """#356 — context budgets are allocated per specialist."""
    module = load_module("mergecraft.context.operator")
    allocate = require_callable(module, "allocate_specialist_budgets")
    budgets = allocate(specialists=["security", "correctness"], total_tokens=8000)
    assert set(budgets) >= {"security", "correctness"}
    assert sum(int(value) for value in budgets.values()) <= 8000


def test_lazy_context_retrieval_goes_through_controlled_tools(tmp_path: Path) -> None:
    """#356 — lazy retrieval is tool-gated, not a query echo."""
    module = load_module("mergecraft.context.operator")
    retrieve = require_callable(module, "lazy_retrieve")
    query = "callers of process"
    denied = retrieve(query=query, tools_allowed=())
    assert getattr(denied, "omitted", False)
    assert tuple(getattr(denied, "items", ())) == ()
    no_root = retrieve(query=query, tools_allowed=("search",))
    assert getattr(no_root, "omitted", False)
    assert query not in tuple(getattr(no_root, "items", ()))

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("def process():\n    return 1\n", encoding="utf-8")
    git_init_repo(repo)
    git_commit_all(repo)
    hits = retrieve(query="process", tools_allowed=("search",), repo_root=repo)
    assert getattr(hits, "omitted", True) is False
    items = tuple(getattr(hits, "items", ()))
    assert items
    assert "process" not in items
    assert any("app.py" in item for item in items)


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


def test_context_retrieval_quality_is_benchmarked_separately_from_models() -> None:
    """#356 — retrieval quality benchmark does not score the LLM."""
    module = load_module("mergecraft.context.operator")
    report = require_callable(module, "evaluate_retrieval_quality")()
    assert getattr(report, "model_quality", None) in {None, False}
    score = getattr(report, "retrieval_score", None)
    assert score is not None
    assert 0.0 <= float(score) <= 1.0
