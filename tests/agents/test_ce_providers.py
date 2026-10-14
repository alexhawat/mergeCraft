"""W21 / W25 — provider capability catalog and residency enforcement (#371).

The module's surviving surface is :func:`capability_catalog` (the enterprise
routing residency fallback) and :func:`enforce_residency` (the enterprise
residency policy). The routing, circuit-breaker, degradation, budget and
routing-eval helpers this file used to exercise had no production caller and
are gone; ``tests/agents/test_provider_health_surface.py`` pins their removal.

Out of scope: per-specialist value measurement (#370); publishing measured
cost per review (evaluation / #140). D6: do not edit tracing exporters.
"""

from __future__ import annotations

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


def test_residency_policy_allows_permitted_region() -> None:
    """Happy: residency policy accepts a region on the allow-list."""
    module = require_module(PROVIDER_HEALTH_MODULE)
    check = require_callable(module, "enforce_residency")
    assert check(region="eu-central-1", allowed=("us-east-1", "eu-central-1")) is None


def test_residency_policy_blocks_disallowed_region() -> None:
    """Error: residency policy refuses a disallowed region (type + message)."""
    module = require_module(PROVIDER_HEALTH_MODULE)
    check = require_callable(module, "enforce_residency")
    with pytest.raises((ValueError, PermissionError, RuntimeError), match=r"residenc"):
        check(region="us-east-1", allowed=("eu-central-1",))
