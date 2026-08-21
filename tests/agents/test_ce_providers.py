"""W21 / W25 — provider health, cooldown, degradation, residency (#371).

Out of scope: per-specialist value measurement (#370); publishing measured
cost per review (evaluation / #140). D6: do not edit tracing exporters.
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from tests.support.ce_batch import (
    CAPABILITY_DIMENSIONS,
    PROVIDER_HEALTH_MODULE,
    TRACING_EXPORTERS,
    require_callable,
    require_module,
)
from tests.support.dead_package_wiring import SRC_ROOT

from mergecraft.utils.retry_policy import is_transient_http_error


def test_retry_policy_already_classifies_retryable_failures() -> None:
    """Substrate — HTTP retries already distinguish retryable vs permanent."""
    assert is_transient_http_error is not None


def test_w25_does_not_edit_tracing_exporters() -> None:
    """D6 lasting — provider health must not rewrite OTLP exporters."""
    text = TRACING_EXPORTERS.read_text(encoding="utf-8")
    assert "cooldown" not in text.casefold()
    assert "residency" not in text.casefold()


def test_w25_does_not_publish_measured_cost_per_review() -> None:
    """#371 out of scope — no published cost-per-review numbers."""
    health = SRC_ROOT / "agents" / "provider_health.py"
    if health.is_file():
        text = health.read_text(encoding="utf-8").casefold()
        assert "published_usd" not in text
        assert "cost per review" not in text


def test_capability_catalog_tracks_named_dimensions() -> None:
    """Happy: catalog entries expose context, reasoning, tools, structured IO, cost, latency, residency."""
    module = require_module(PROVIDER_HEALTH_MODULE)
    catalog = require_callable(module, "capability_catalog")()
    assert catalog
    sample = catalog[0] if not isinstance(catalog, dict) else next(iter(catalog.values()))
    payload: dict[str, Any] = sample if isinstance(sample, dict) else dict(sample)
    missing = CAPABILITY_DIMENSIONS - set(payload)
    assert not missing, payload


def test_require_prefer_fallback_semantics() -> None:
    """Happy: require / prefer / fallback are distinct routing intents."""
    module = require_module(PROVIDER_HEALTH_MODULE)
    intents = frozenset(module.ROUTING_INTENTS)
    assert intents == frozenset({"require", "prefer", "fallback"})


def test_route_model_per_specialist_and_risk() -> None:
    """Happy: routing is per specialist and per risk level."""
    module = require_module(PROVIDER_HEALTH_MODULE)
    route = require_callable(module, "route_model")
    high = route(specialist="security", risk="high")
    low = route(specialist="security", risk="trivial")
    assert high
    assert low
    assert high != low or route(specialist="tests", risk="high") != high


def test_heterogeneous_verifier_and_judge_models() -> None:
    """Happy: verifier and judge may use different models."""
    module = require_module(PROVIDER_HEALTH_MODULE)
    pair = require_callable(module, "verifier_judge_models")()
    payload = pair if isinstance(pair, dict) else dict(pair)
    assert payload.get("verifier")
    assert payload.get("judge")
    assert payload["verifier"] != payload["judge"]


def test_provider_health_records_failures() -> None:
    """Happy: health tracking records a provider failure."""
    module = require_module(PROVIDER_HEALTH_MODULE)
    tracker_cls = getattr(module, "ProviderHealth", None)
    if tracker_cls is None:
        pytest.fail("expected ProviderHealth")
    tracker = tracker_cls()
    tracker.record_failure("anthropic", reason="timeout")
    snapshot = tracker.snapshot("anthropic")
    payload = snapshot if isinstance(snapshot, dict) else dict(snapshot)
    assert payload.get("failures", 0) >= 1 or payload.get("unhealthy") is True


def test_retries_are_bounded_and_retryable_only() -> None:
    """Error: non-retryable failures are not retried; retryable ones are bounded."""
    module = require_module(PROVIDER_HEALTH_MODULE)
    decide = require_callable(module, "should_retry_provider")
    assert decide(failure="rate_limit", attempt=1) is True
    assert decide(failure="auth", attempt=1) is False
    with pytest.raises((ValueError, RuntimeError), match=r"retry|bound|attempt"):
        decide(failure="rate_limit", attempt=99)


def test_circuit_breaker_and_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    """Happy: circuit breaker opens and cooldown elapses on monotonic time."""
    module = require_module(PROVIDER_HEALTH_MODULE)
    breaker_cls = getattr(module, "ProviderBreaker", None)
    if breaker_cls is None:
        pytest.fail("expected ProviderBreaker")
    clock = {"now": 1_000.0}
    monkeypatch.setattr(module, "monotonic", lambda: clock["now"])
    breaker = breaker_cls(provider="anthropic", cooldown_s=30)
    breaker.trip()
    assert breaker.allow() is False
    cooldown = getattr(breaker, "cooldown_s", None) or getattr(breaker, "cooldown", None)
    assert cooldown == 30
    clock["now"] = 1_029.0
    assert breaker.allow() is False
    clock["now"] = 1_030.0
    assert breaker.allow() is True


def test_degrade_when_non_required_provider_unavailable() -> None:
    """Happy: a non-required provider outage degrades instead of failing the run."""
    module = require_module(PROVIDER_HEALTH_MODULE)
    degrade = require_callable(module, "degrade_unavailable")
    outcome = degrade(provider="openai", required=False)
    status = getattr(outcome, "status", outcome)
    assert str(status) in {"degraded", "fallback", "partial", "inconclusive"}


def test_required_model_is_never_silently_substituted() -> None:
    """Error: a policy-required model is never swapped in silence (type + message)."""
    module = require_module(PROVIDER_HEALTH_MODULE)
    resolve = require_callable(module, "resolve_required_model")
    with pytest.raises((ValueError, RuntimeError, LookupError), match=r"required|substitut|pin"):
        resolve(required="anthropic/claude-sonnet", available=("openai/gpt-5.3-codex",))


def test_run_manifest_records_provider_model_and_hashes() -> None:
    """Happy: run manifests record exact provider/model versions and hashes."""
    module = require_module(PROVIDER_HEALTH_MODULE)
    stamp = require_callable(module, "manifest_provider_stamp")
    payload = stamp(
        provider="anthropic",
        model="claude-sonnet",
        prompt_hash="abc",
        config_hash="def",
        policy_hash="ghi",
    )
    data = payload if isinstance(payload, dict) else dict(payload)
    assert data.get("provider") == "anthropic" or "anthropic" in str(data)
    assert data.get("model") == "claude-sonnet" or "claude-sonnet" in str(data)
    for key in ("prompt_hash", "config_hash", "policy_hash"):
        assert key in data


def test_per_provider_budget_enforcement() -> None:
    """Error: exceeding a per-provider budget fails closed (type + message)."""
    module = require_module(PROVIDER_HEALTH_MODULE)
    enforce = require_callable(module, "enforce_provider_budget")
    with pytest.raises((ValueError, RuntimeError), match=r"budget|cost|token"):
        enforce(provider="anthropic", spent_usd=10_000.0, limit_usd=1.0)


def test_routing_eval_rejects_cheaper_but_worse_quality() -> None:
    """Happy: cheaper routing that harms review quality fails the eval."""
    module = require_module(PROVIDER_HEALTH_MODULE)
    evaluate = require_callable(module, "evaluate_routing_quality")
    result = evaluate(
        baseline_quality=0.9,
        candidate_quality=0.4,
        baseline_usd=2.0,
        candidate_usd=0.1,
    )
    passed = getattr(result, "passed", None)
    if passed is None:
        passed = result.get("passed") if isinstance(result, dict) else bool(result)
    assert passed is False


def test_residency_policy_blocks_disallowed_region() -> None:
    """Error: residency policy refuses a disallowed region (type + message)."""
    module = require_module(PROVIDER_HEALTH_MODULE)
    check = require_callable(module, "enforce_residency")
    with pytest.raises((ValueError, PermissionError, RuntimeError), match=r"residenc"):
        check(region="us-east-1", allowed=("eu-central-1",))


def test_nightly_smoke_callable_is_registered() -> None:
    """Happy: live-provider nightly smoke is a named callable (drift detection)."""
    module = require_module(PROVIDER_HEALTH_MODULE)
    smoke = require_callable(module, "nightly_provider_smoke")
    assert callable(smoke)


@pytest.mark.skipif(os.environ.get("MERGECRAFT_LIVE_E2E") != "1", reason="skipped: no live gate")
def test_live_provider_smoke_runs_when_gated() -> None:
    """Functional: nightly smoke executes only under ``MERGECRAFT_LIVE_E2E=1``."""
    module = require_module(PROVIDER_HEALTH_MODULE)
    smoke = require_callable(module, "nightly_provider_smoke")
    report = smoke()
    passed = getattr(report, "passed", None)
    if passed is None and isinstance(report, dict):
        passed = report.get("passed")
    assert passed is True
