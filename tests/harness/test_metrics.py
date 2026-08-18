"""RH5 — harness metrics."""

from __future__ import annotations

import httpx

from tests.support.provider_harness import DUMMY_API_KEY
from tests.support.provider_harness.pytest_plugin import load_harness_fixtures


def test_metrics_count_matches_mismatches_statuses_and_retries(provider_harness) -> None:
    provider_harness.reload(load_harness_fixtures("no-findings"))
    httpx.post(
        provider_harness.base_url + "/chat/completions",
        headers={"Authorization": f"Bearer {DUMMY_API_KEY}"},
        json={"model": "default/dummy", "messages": []},
        timeout=5.0,
    )
    httpx.post(
        provider_harness.base_url + "/chat/completions",
        headers={"Authorization": f"Bearer {DUMMY_API_KEY}"},
        json={"model": "default/unknown", "messages": []},
        timeout=5.0,
    )
    snap = provider_harness.metrics.snapshot()
    assert snap["matches"] >= 1
    assert snap["mismatches"] >= 1


def test_metrics_are_bounded_and_reset_per_server(provider_harness) -> None:
    provider_harness.reload(load_harness_fixtures("no-findings"))
    httpx.post(
        provider_harness.base_url + "/chat/completions",
        headers={"Authorization": f"Bearer {DUMMY_API_KEY}"},
        json={"model": "default/dummy", "messages": []},
        timeout=5.0,
    )
    provider_harness.reload(load_harness_fixtures("no-findings"))
    snap = provider_harness.metrics.snapshot()
    assert snap["request_count"] >= 0
