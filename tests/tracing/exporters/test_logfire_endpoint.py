"""Regression tests for the Logfire OTLP endpoint/header fix.

The Logfire OTLP/HTTP endpoint was ``https://logfire.pydantic.dev/api/v1/otlp/v1/traces``
with a spurious ``x-logfire-project`` header — both wrong, producing a 404
(``Failed to export span batch code: 404, reason: Not Found``). Logfire routes
spans by the token itself; the correct endpoints are region-aware:

- US: ``https://logfire-us.pydantic.dev/v1/traces``
- EU: ``https://logfire-eu.pydantic.dev/v1/traces``

These tests pin the corrected endpoint host/path and the absence of the
``x-logfire-project`` header.
"""

from __future__ import annotations

import mergecraft.tracing.exporters as exporters


def test_logfire_endpoint_uses_correct_us_region() -> None:
    """Default region yields the US ingest endpoint and no project header."""
    endpoint, _headers = exporters._build_logfire_endpoint_and_headers(
        project="demo", token="pylf_test_us", region="us"
    )
    assert endpoint == "https://logfire-us.pydantic.dev/v1/traces"


def test_logfire_endpoint_eu_region() -> None:
    """``region='eu'`` yields the EU ingest endpoint."""
    endpoint, _headers = exporters._build_logfire_endpoint_and_headers(
        project="demo", token="pylf_test_eu", region="eu"
    )
    assert endpoint == "https://logfire-eu.pydantic.dev/v1/traces"


def test_logfire_endpoint_no_project_header() -> None:
    """Headers carry the auth token and never the ``x-logfire-project`` header."""
    for project in ("demo", None, ""):
        _endpoint, headers = exporters._build_logfire_endpoint_and_headers(
            project=project, token="pylf_test_xxx", region="us"
        )
        assert "authorization" in headers
        assert headers["authorization"] == "Bearer pylf_test_xxx"
        assert "x-logfire-project" not in headers


def test_logfire_endpoint_explicit_override() -> None:
    """An explicit entry endpoint is used verbatim (self-hosted/testing)."""
    endpoint, _headers = exporters._build_logfire_endpoint_and_headers(
        project="demo",
        token="pylf_test_ovr",
        region="us",
        endpoint_override="https://otel-collector.internal:4318/v1/traces",
    )
    assert endpoint == "https://otel-collector.internal:4318/v1/traces"
