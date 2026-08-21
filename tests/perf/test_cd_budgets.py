"""W14 / W20 — latency/cost budgets, compression, early stop (#367).

Token/cost/tool-call budgets already exist on ``ReviewProfile``. This wave
adds latency budgets, ensemble cost ceilings, compression, early stop, and
regression benches.

Out of scope: publishing measured cost and latency numbers (evaluation issue /
#140). D8: do not implement gated P12-P31 here.
"""

from __future__ import annotations

import dataclasses

import pytest

from mergecraft.cli.profiles import ReviewProfile, resolve_profile
from tests.support.cd_batch import (
    PERF_MODULE,
    d10_root_callback_owns_globals,
    require_callable,
    require_module,
)


def test_profile_token_cost_and_tool_budgets_already_exist() -> None:
    """W14 current state — cost/token/tool budgets ship on ``ReviewProfile``."""
    names = {field.name for field in dataclasses.fields(ReviewProfile)}
    assert "token_budget" in names
    assert "cost_budget_usd" in names
    assert "tool_call_budget" in names
    deep = resolve_profile("deep")
    assert deep is not None
    assert deep.cost_budget_usd == 100.0


def test_w20_does_not_publish_measured_cost_or_latency_numbers() -> None:
    """#367 out of scope + D8 — no published benchmark numbers in this program."""
    d10_root_callback_owns_globals()
    module = require_module(PERF_MODULE)
    bench = require_callable(module, "run_perf_regression_benchmark")
    report = bench(kind="regression")
    payload = report.model_dump() if hasattr(report, "model_dump") else dict(report)
    for banned in ("published_usd", "published_p95_ms", "precision", "recall"):
        assert banned not in payload


@pytest.mark.parametrize("name", ["fast", "deep", "security"])
def test_each_profile_has_an_explicit_latency_budget(name: str) -> None:
    """Happy: every review profile carries ``latency_budget_ms``."""
    profile = resolve_profile(name)
    assert profile is not None
    assert profile.latency_budget_ms > 0


def test_ensemble_cost_ceiling_is_enforced() -> None:
    """Error: exceeding the profile cost ceiling fails closed (type + message)."""
    module = require_module(PERF_MODULE)
    enforce = require_callable(module, "enforce_cost_ceiling")
    with pytest.raises((ValueError, RuntimeError), match=r"cost|budget|ceiling"):
        enforce(profile="fast", spent_usd=10_000.0)


def test_cheap_classification_runs_before_expensive_specialists() -> None:
    """Happy: routing order classifies cheaply before specialist fan-out."""
    module = require_module(PERF_MODULE)
    order = list(require_callable(module, "review_stage_order")())
    assert order[0] in {"classify", "classification", "cheap_classification"}
    assert "specialist" in {str(stage).casefold() for stage in order[1:]} or any(
        "specialist" in str(stage).casefold() for stage in order
    )


def test_independent_work_is_marked_parallelizable() -> None:
    """Happy: independent specialist work is tagged for parallel dispatch."""
    module = require_module(PERF_MODULE)
    plan = require_callable(module, "parallelizable_work")(["security", "tests"])
    assert plan
    parallel = getattr(plan, "parallel", None)
    if parallel is None:
        parallel = plan if isinstance(plan, list) else plan.get("parallel")
    assert parallel


def test_repo_map_symbol_analyzer_and_summary_caches_exist() -> None:
    """Happy: cache keys cover repo map, symbols, analyzers, immutable summaries."""
    module = require_module(PERF_MODULE)
    cache = require_callable(module, "ReviewContextCache")()
    for key in ("repo_map", "symbol_index", "analyzer_results", "immutable_summaries"):
        assert hasattr(cache, key) or key in cache


def test_identical_context_is_not_resent_to_every_agent() -> None:
    """Edge: shared evidence is reused instead of duplicated per agent."""
    module = require_module(PERF_MODULE)
    reuse = require_callable(module, "shared_evidence_payload")
    first = reuse(agent="a", evidence_id="e1")
    second = reuse(agent="b", evidence_id="e1")
    first_id = getattr(first, "fingerprint", None) or first.get("fingerprint")
    second_id = getattr(second, "fingerprint", None) or second.get("fingerprint")
    assert first_id == second_id


def test_semantic_compression_and_structural_summaries_precede_llm() -> None:
    """Happy: deterministic structural summaries run before LLM summaries."""
    module = require_module(PERF_MODULE)
    pipeline = list(require_callable(module, "summary_pipeline")())
    joined = " ".join(str(step).casefold() for step in pipeline)
    assert "structural" in joined
    assert pipeline.index("structural") < pipeline.index("llm") or joined.find(
        "structural"
    ) < joined.find("llm")


def test_early_stop_when_sufficient_evidence_exists() -> None:
    """Happy: early-stop fires once evidence is sufficient."""
    module = require_module(PERF_MODULE)
    decide = require_callable(module, "should_early_stop")
    assert decide(evidence_complete=True, remaining_specialists=("style",)) is True
    assert decide(evidence_complete=False, remaining_specialists=("security",)) is False


def test_budget_aware_specialist_and_model_routing() -> None:
    """Happy: specialist routing considers remaining budget and model cost."""
    module = require_module(PERF_MODULE)
    route = require_callable(module, "route_specialist")
    choice = route(remaining_usd=0.01, remaining_ms=50)
    model = getattr(choice, "model", None) or choice.get("model")
    assert model


def test_per_agent_token_accounting_and_cache_hit_metrics() -> None:
    """Happy: per-agent tokens and cache hit/miss counters are recorded."""
    module = require_module(PERF_MODULE)
    stats = require_callable(module, "perf_metrics")()
    payload = stats if isinstance(stats, dict) else dict(stats)
    token_key = "tokens_by_agent" if "tokens_by_agent" in payload else "per_agent_tokens"
    assert token_key in payload
    assert "cache_hits" in payload
    assert "cache_misses" in payload


def test_performance_regression_and_monorepo_benchmarks_exist() -> None:
    """Happy: regression + large-monorepo benches exist without published numbers."""
    module = require_module(PERF_MODULE)
    bench = require_callable(module, "run_perf_regression_benchmark")
    report = bench(kind="monorepo")
    payload = report.model_dump() if hasattr(report, "model_dump") else dict(report)
    assert payload.get("status") == "not_run"
    for banned in ("published_usd", "published_p95_ms", "precision", "recall"):
        assert banned not in payload
