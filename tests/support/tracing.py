"""Per-test OTel ownership and an in-memory HTTP transport for unit tests.

Keep the real exporter, encoding and batch processor so tracing contracts still
exercise the production pipeline. Only its default HTTP session is replaced;
network/integration/live tests and explicitly injected transports keep theirs.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def otlp_requests(
    request: pytest.FixtureRequest,
    _block_network: None,
) -> Iterator[list[Any]]:
    """Capture unit OTLP requests and stop every provider before network teardown.

    OTel's global provider and one-shot registration latch must both be reset.
    Track constructor calls too: tests can create providers that are never installed
    globally, and those providers still own batch-export worker threads.
    """
    captured: list[Any] = []
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.util._once import Once
        from requests import Response, Session
        from requests.adapters import BaseAdapter
    except ImportError:
        # The tracing extra is optional; do not skip unrelated tests without it.
        yield captured
        return

    from mergecraft.tracing import exporters

    class RecordingAdapter(BaseAdapter):
        def send(self, request: Any, **kwargs: Any) -> Response:
            captured.append(request)
            response = Response()
            response.status_code = 200
            response._content = b""
            response.request = request
            return response

        def close(self) -> None:
            pass

    provider_init = TracerProvider.__init__
    exporter_init = OTLPSpanExporter.__init__
    with pytest.MonkeyPatch.context() as patch, ExitStack() as providers:
        patch.setattr(trace, "_TRACER_PROVIDER", None)
        patch.setattr(trace, "_TRACER_PROVIDER_SET_ONCE", Once())
        patch.setattr(trace, "_PROXY_TRACER_PROVIDER", trace.ProxyTracerProvider())

        def init_provider(self: Any, *args: Any, **kwargs: Any) -> None:
            provider_init(self, *args, **kwargs)
            # shutdown drains queued spans and joins the batch worker. ExitStack
            # runs every shutdown even if another provider's cleanup raises.
            providers.callback(self.shutdown)

        def init_exporter(self: Any, *args: Any, **kwargs: Any) -> None:
            # session is the eighth positional argument in the pinned SDK.
            if len(args) < 8 and kwargs.get("session") is None and not kwargs.get("_transport"):
                session = Session()
                session.trust_env = False
                session.mount("http://", RecordingAdapter())
                session.mount("https://", RecordingAdapter())
                kwargs["session"] = session
            exporter_init(self, *args, **kwargs)

        patch.setattr(TracerProvider, "__init__", init_provider)
        if not any(request.node.get_closest_marker(m) for m in ("network", "integration", "live")):
            patch.setattr(OTLPSpanExporter, "__init__", init_exporter)
        exporters._reset_test_seam()
        try:
            yield captured
        finally:
            try:
                providers.close()
            finally:
                exporters._reset_test_seam()
