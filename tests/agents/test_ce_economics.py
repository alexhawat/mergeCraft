"""W21 / W24 — per-specialist economics (#370 / D11).

Consume ``gen_ai.usage.*`` already stamped on ``llm.call``. Do not
re-instrument ``tracing/exporters.py`` (D6 / D11).

Out of scope: lens registry and risk-based routing; provider health (#371).
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.support.ce_batch import (
    SPECIALIST_ECONOMICS_MODULE,
    TRACING_EXPORTERS,
    USAGE_ATTRS,
    require_callable,
    require_module,
    src_mentions,
)
from tests.support.dead_package_wiring import SRC_ROOT


def test_w24_does_not_edit_tracing_exporters() -> None:
    """D6 / D11 lasting — exporters stay 20b's; this program consumes attrs."""
    text = TRACING_EXPORTERS.read_text(encoding="utf-8")
    assert "unique_useful" not in text
    assert "specialist economics" not in text.casefold()


def test_lens_routing_remains_the_routing_surface() -> None:
    """#370 out of scope — do not rebuild lens registry / risk routing."""
    routing = SRC_ROOT / "review" / "lens_routing.py"
    assert routing.is_file()
    text = routing.read_text(encoding="utf-8")
    assert "route" in text.casefold()


def test_usage_attrs_already_exist_on_llm_call_path() -> None:
    """D11 substrate — ``gen_ai.usage.*`` names already exist for economics to consume."""
    genai = (SRC_ROOT / "tracing" / "genai.py").read_text(encoding="utf-8")
    for attr in USAGE_ATTRS:
        assert attr in genai


def test_unique_useful_findings_are_counted_per_specialist() -> None:
    """Happy: unique useful findings are tracked per specialist."""
    module = require_module(SPECIALIST_ECONOMICS_MODULE)
    count = require_callable(module, "unique_useful_findings")
    findings = [
        {"id": "a", "useful": True, "specialist": "security"},
        {"id": "a", "useful": True, "specialist": "security"},
        {"id": "b", "useful": False, "specialist": "security"},
        {"id": "c", "useful": True, "specialist": "tests"},
    ]
    assert count("security", findings) == 1
    assert count("tests", findings) == 1
    assert count("missing", findings) == 0


def test_agent_metrics_include_latency_cost_precision_recall() -> None:
    """Happy: per-agent metrics expose latency, cost, precision, and recall."""
    module = require_module(SPECIALIST_ECONOMICS_MODULE)
    metrics = require_callable(module, "specialist_metrics")
    spans = [
        {
            "name": "llm.call",
            "specialist": "security",
            "duration_ms": 12.0,
            "gen_ai.usage.input_tokens": 10,
            "gen_ai.usage.output_tokens": 4,
            "gen_ai.usage.cost_usd": 0.02,
        }
    ]
    report = metrics(specialist="security", spans=spans, findings=[{"id": "a", "useful": True}])
    payload: dict[str, Any] = report if isinstance(report, dict) else dict(report)
    for key in ("latency_ms", "cost_usd", "precision", "recall"):
        assert key in payload, payload
        assert payload[key] is not None


def test_economics_consumes_gen_ai_usage_attrs() -> None:
    """Happy: cost is derived from ``gen_ai.usage.*`` on ``llm.call`` spans (D11)."""
    module = require_module(SPECIALIST_ECONOMICS_MODULE)
    cost_of = require_callable(module, "cost_from_usage_spans")
    spans = [
        {
            "name": "llm.call",
            "gen_ai.usage.cost_usd": 1.25,
            "gen_ai.usage.input_tokens": 100,
            "gen_ai.usage.output_tokens": 20,
        }
    ]
    assert cost_of(spans) == pytest.approx(1.25)


def test_zero_value_specialists_are_identified() -> None:
    """Happy: specialists that add cost without review value are named."""
    module = require_module(SPECIALIST_ECONOMICS_MODULE)
    identify = require_callable(module, "low_value_specialists")
    named = identify(
        [
            {"specialist": "security", "cost_usd": 1.0, "unique_useful_findings": 3},
            {"specialist": "style", "cost_usd": 2.0, "unique_useful_findings": 0},
        ]
    )
    names = {item if isinstance(item, str) else item.get("specialist") for item in named}
    assert "style" in names
    assert "security" not in names


def test_empty_metrics_list_yields_no_low_value_specialists() -> None:
    """Edge: empty input is an empty prune list, not an error."""
    module = require_module(SPECIALIST_ECONOMICS_MODULE)
    identify = require_callable(module, "low_value_specialists")
    assert list(identify([])) == []


def test_per_agent_circuit_breaker_opens_on_repeated_waste() -> None:
    """Error: a specialist circuit breaker opens after repeated zero-value runs."""
    module = require_module(SPECIALIST_ECONOMICS_MODULE)
    breaker_cls = getattr(module, "SpecialistBreaker", None)
    if breaker_cls is None:
        pytest.fail("expected SpecialistBreaker")
    breaker = breaker_cls(specialist="style", threshold=2)
    breaker.record(unique_useful_findings=0, cost_usd=1.0)
    breaker.record(unique_useful_findings=0, cost_usd=1.0)
    assert breaker.allow() is False
    with pytest.raises((RuntimeError, ValueError), match=r"circuit|breaker|degrad"):
        breaker.guard()


def test_per_agent_degradation_skips_low_value_specialist() -> None:
    """Happy: degradation skips a specialist that is open on the breaker."""
    module = require_module(SPECIALIST_ECONOMICS_MODULE)
    degrade = require_callable(module, "degraded_specialists")
    skipped = degrade(open_breakers=("style",), requested=("security", "style"))
    assert "style" in set(skipped)
    assert "security" not in set(skipped)


def test_economics_does_not_import_tracing_exporters() -> None:
    """D11 — economics consumes attrs; it must not import exporters."""
    module = require_module(SPECIALIST_ECONOMICS_MODULE)
    source = SRC_ROOT.joinpath(*module.__name__.split(".")[1:]).with_suffix(".py")
    text = source.read_text(encoding="utf-8")
    assert "tracing.exporters" not in text
    assert "tracing/exporters" not in text
    assert src_mentions("unique_useful_findings")  # module exists in src once implemented
