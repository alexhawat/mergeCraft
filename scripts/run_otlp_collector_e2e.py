#!/usr/bin/env python3
"""Start a real OTLP collector, seed spans, and run the W7 e2e pytest module.

Used by ``make test-otlp-collector``. Requires Docker and the ``[tracing]`` extra.
When Docker is unavailable, exits 0 after printing ``skipped: no docker`` so CI
operators can distinguish a harness miss from a contract failure.
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COLLECTOR_IMAGE = (
    "otel/opentelemetry-collector"
    "@sha256:1daa4312b48312dbae2d543e67b77e897dd5d9c48e7651d1416cdb417026ad06"
)
COLLECTOR_CONFIG = REPO_ROOT / "scripts" / "otel-collector-e2e.yaml"
CONTAINER_NAME = "mergecraft-otel-collector-e2e"


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _run(cmd: list[str], *, env: dict[str, str] | None = None) -> None:
    subprocess.run(cmd, check=True, env=env)


def _run_quiet(cmd: list[str], *, env: dict[str, str] | None = None) -> None:
    subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)


def _start_collector(*, image: str, dump_path: Path, endpoint: str) -> None:
    _run_quiet(["docker", "rm", "-f", CONTAINER_NAME])
    dump_path.parent.mkdir(parents=True, exist_ok=True)
    if not dump_path.exists():
        dump_path.touch()
    _run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            CONTAINER_NAME,
            "-p",
            "4318:4318",
            "-v",
            f"{COLLECTOR_CONFIG}:/etc/otelcol/config.yaml:ro",
            "-v",
            f"{dump_path}:/tmp/spans.json",
            image,
            "--config",
            "/etc/otelcol/config.yaml",
        ]
    )
    deadline = time.time() + 30.0
    host = "127.0.0.1"
    port = 4318
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError(f"collector did not become ready on {host}:{port}")


def _stop_collector() -> None:
    if not _docker_available():
        return
    subprocess.run(["docker", "rm", "-f", CONTAINER_NAME], check=False)


def _seed_spans(*, endpoint: str) -> None:
    from mergecraft.config import RepoSettings
    from mergecraft.tracing import sink_factory
    from mergecraft.tracing.event import TraceEvent

    settings = RepoSettings.model_validate(
        {
            "tracing": {
                "enabled": True,
                "sinks": [{"type": "otel", "endpoint": endpoint}],
            }
        }
    ).tracing
    sink = sink_factory(settings)
    flush = getattr(sink, "flush", None)
    trace_id = "a" * 32
    for index in range(2):
        event = TraceEvent(
            kind="llm.call",
            span_id=f"span-{index}",
            session_id="collector-e2e",
            turn_id="turn-1",
            tier="trusted",
            ts_start_ns=0,
            ts_end_ns=1_000_000,
            status="ok",
            trace_id=trace_id,
            attrs={
                "gen_ai.operation.name": "chat",
                "gen_ai.request.model": "claude-sonnet-5",
                "gen_ai.usage.input_tokens": 120,
                "gen_ai.usage.output_tokens": 48,
            },
        )
        sink.write(event)
    if callable(flush):
        flush()
    time.sleep(2.0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--collector-image",
        default=os.environ.get("MERGECRAFT_OTEL_COLLECTOR_IMAGE", DEFAULT_COLLECTOR_IMAGE),
    )
    args = parser.parse_args(argv)
    pytest_args = [
        "tests/tracing/test_otlp_collector_e2e.py",
        "-v",
        "--tb=short",
        "--runxfail",
    ]
    pre_seed_tests = (
        "test_wrong_exporter_endpoint_fails_the_job or "
        "test_tracing_disabled_is_true_noop_no_collector_traffic or "
        "test_env_cli_yaml_precedence_resolves_to_live_sink or "
        "test_unguarded_set_tracer_provider_swallow_would_fail_the_job or "
        "test_collector_image_is_digest_pinned_in_ci or "
        "test_make_target_invokes_collector_suite or "
        "test_w7_touched_workflows_remain_sha_pinned"
    )
    post_seed_tests = (
        "test_spans_arrive_at_real_collector_with_gen_ai_attributes or "
        "test_one_trace_per_run_holds_against_the_collector"
    )

    if not _docker_available():
        print("skipped: no docker", file=sys.stderr)
        return 0

    endpoint = os.environ.get(
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        os.environ.get("MERGECRAFT_OTEL_ENDPOINT", "http://127.0.0.1:4318/v1/traces"),
    )
    with tempfile.TemporaryDirectory(prefix="mergecraft-otel-e2e-") as tmp:
        dump_path = Path(tmp) / "spans.json"
        dump_path.touch()
        env = os.environ.copy()
        env["MERGECRAFT_OTEL_COLLECTOR_DUMP"] = str(dump_path)
        env["OTEL_EXPORTER_OTLP_ENDPOINT"] = endpoint
        env["MERGECRAFT_OTEL_ENDPOINT"] = endpoint
        try:
            _start_collector(image=args.collector_image, dump_path=dump_path, endpoint=endpoint)
            _run(
                [sys.executable, "-m", "pytest", *pytest_args, "-k", pre_seed_tests],
                env=env,
            )
            _seed_spans(endpoint=endpoint)
            _run(
                [sys.executable, "-m", "pytest", *pytest_args, "-k", post_seed_tests],
                env=env,
            )
        finally:
            _stop_collector()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
