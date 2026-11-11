"""Behaviour of the autouse hermeticity guards in ``tests/support/hermetic.py``."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from tests.support import hermetic


def test_non_loopback_connect_is_blocked() -> None:
    with pytest.raises(hermetic.NetworkBlockedError):
        socket.create_connection(("192.0.2.1", 80), timeout=1)
    hermetic._VIOLATIONS.clear()  # the raise above is the expected outcome


def test_dns_lookup_of_external_host_is_blocked() -> None:
    with pytest.raises(hermetic.NetworkBlockedError):
        socket.getaddrinfo("api.github.com", 443)
    hermetic._VIOLATIONS.clear()


def test_loopback_connect_is_allowed() -> None:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        with socket.create_connection(server.getsockname(), timeout=2):
            pass


@pytest.mark.network
def test_network_marker_lifts_the_guard() -> None:
    # With the guard lifted the lookup reaches the resolver (``.invalid`` never resolves).
    with pytest.raises(socket.gaierror):
        socket.getaddrinfo("nonexistent.invalid", 80)


def test_ambient_environment_is_scrubbed() -> None:
    for name in os.environ:
        assert not name.startswith(("MERGECRAFT_LIVE", "GITHUB_", "OTEL_", "OPENAI_"))
    assert "GITHUB_TOKEN" not in os.environ
    assert "GH_TOKEN" not in os.environ


@pytest.mark.parametrize("ci", ["true", "false", ""])
def test_environment_scrub_preserves_ci_sandbox_probe(
    ci: str,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    from mergecraft.analyzers.sandbox import _ISOLATION_PROBE_SCRIPT

    monkeypatch.setenv("CI", ci)
    monkeypatch.setenv("GITHUB_TOKEN", "ambient-token")
    monkeypatch.setenv("MERGECRAFT_PROBE_ALLOW_SUDO", "1")
    hermetic._isolate_environment.__wrapped__(request, monkeypatch, tmp_path_factory)
    assert "GITHUB_TOKEN" not in os.environ
    assert "MERGECRAFT_PROBE_ALLOW_SUDO" not in os.environ
    # Simulate a runner where only sudo can provide isolation. No real mount,
    # unshare or sudo commands run, but the production shell gate is exercised.
    stubs = "unshare() { return 1; }; mount() { return 1; }; umount() { return 1; }; sudo() { return 0; };\n"
    result = subprocess.run(
        ["bash", "-c", stubs + _ISOLATION_PROBE_SCRIPT],
        capture_output=True,
        text=True,
        check=True,
    )
    expected = "sudo-unshare" if ci == "true" else "none"
    assert f"pid_method={expected}" in result.stdout


def test_tracing_workers_and_provider_do_not_leak_between_tests(tmp_path: Path) -> None:
    pytest.importorskip("opentelemetry.sdk.trace")
    root = Path(__file__).resolve().parents[1]
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "conftest.py").write_text(
        'pytest_plugins = ["tests.support.hermetic", "tests.support.tracing"]\n',
        encoding="utf-8",
    )
    (tmp_path / "test_lifecycle.py").write_text(
        """
import threading
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

workers = []
exporters = []
requests = []

def test_owner(otlp_requests):
    before = set(threading.enumerate())
    # Include a provider never installed globally: it must be cleaned up too.
    for install in (True, False):
        provider = TracerProvider()
        if install:
            trace.set_tracer_provider(provider)
        exporter = OTLPSpanExporter(endpoint="https://collector.invalid/v1/traces")
        exporters.append(exporter)
        provider.add_span_processor(BatchSpanProcessor(exporter, schedule_delay_millis=60000))
        with provider.get_tracer("guard").start_as_current_span("owned-span"):
            pass
    workers.extend(set(threading.enumerate()) - before)
    assert workers
    requests.append(otlp_requests)
    # Leave spans queued: fixture teardown must drain them and stop the workers.

def test_neighbour(otlp_requests):
    assert all(not worker.is_alive() for worker in workers)
    assert all(exporter._shutdown for exporter in exporters)
    assert isinstance(trace.get_tracer_provider(), trace.ProxyTracerProvider)
    assert otlp_requests == []
    assert len(requests[0]) == 2
    for request in requests[0]:
        payload = ExportTraceServiceRequest.FromString(request.body)
        assert payload.resource_spans[0].scope_spans[0].spans[0].name == "owned-span"
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:randomly", str(tmp_path)],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(root)},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed" in result.stdout


@pytest.mark.network
def test_network_marker_keeps_real_otlp_transport(otlp_requests: list[object]) -> None:
    pytest.importorskip("opentelemetry.sdk.trace")
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    received: list[bytes] = []

    class Collector(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            received.append(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(200)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            pass

    with HTTPServer(("127.0.0.1", 0), Collector) as server:
        server.timeout = 5
        worker = threading.Thread(target=server.handle_request)
        worker.start()
        try:
            provider = TracerProvider()
            provider.add_span_processor(
                BatchSpanProcessor(
                    OTLPSpanExporter(endpoint=f"http://127.0.0.1:{server.server_port}/v1/traces")
                )
            )
            with provider.get_tracer("guard").start_as_current_span("real-transport"):
                pass
            assert provider.force_flush(timeout_millis=5000)
        finally:
            worker.join(timeout=10)
        assert not worker.is_alive()
    assert len(received) == 1
    assert received[0]
    assert otlp_requests == []


def test_home_and_xdg_live_outside_the_checkout() -> None:
    root = Path(__file__).resolve().parents[1]
    for name in ("HOME", "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "MERGECRAFT_TRACE_DIR"):
        assert not Path(os.environ[name]).resolve().is_relative_to(root)
    assert Path.home() == Path(os.environ["HOME"])


@pytest.mark.timeout(1)
def test_per_test_timeout_interrupts_a_hang() -> None:
    with pytest.raises(hermetic.TestTimeoutError):
        time.sleep(5)
