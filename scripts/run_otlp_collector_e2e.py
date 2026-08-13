#!/usr/bin/env python3
"""Start a real OTLP collector, seed spans, and run the W7 e2e pytest module.

Used by ``make test-otlp-collector``. Requires Docker and the ``[tracing]`` extra.
When Docker is unavailable locally, exits 0 after printing ``skipped: no docker``.
In CI (``CI`` or ``GITHUB_ACTIONS``), exits 1 unless ``MERGECRAFT_ALLOW_NO_DOCKER=1``.
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
from typing import Final

REPO_ROOT = Path(__file__).resolve().parents[1]
OTLP_COLLECTOR_IMAGE_FILE = REPO_ROOT / "scripts" / "otel_collector_image.txt"
CONTAINER_NAME = "mergecraft-otel-collector-e2e"
COLLECTOR_DUMP_MOUNT = "/var/lib/otelcol/out"
COLLECTOR_DUMP_BASENAME = "spans.json"

# Keep in sync with tests/tracing/test_otlp_collector_e2e.py (pre-seed contract slice).
OTLP_PRE_SEED_TESTS: Final[tuple[str, ...]] = (
    "test_wrong_exporter_endpoint_fails_the_job",
    "test_tracing_disabled_is_true_noop_no_collector_traffic",
    "test_env_cli_yaml_precedence_resolves_to_live_sink",
    "test_unguarded_set_tracer_provider_swallow_would_fail_the_job",
    "test_collector_image_is_digest_pinned_in_ci",
    "test_make_target_invokes_collector_suite",
    "test_w7_touched_workflows_remain_sha_pinned",
)

OTLP_POST_SEED_TESTS: Final[tuple[str, ...]] = (
    "test_spans_arrive_at_real_collector_with_gen_ai_attributes",
    "test_one_trace_per_run_holds_against_the_collector",
)


def _default_collector_image() -> str:
    return OTLP_COLLECTOR_IMAGE_FILE.read_text(encoding="utf-8").strip()


def _pytest_k(names: tuple[str, ...]) -> str:
    return " or ".join(names)


COLLECTOR_CONFIG = REPO_ROOT / "scripts" / "otel-collector-e2e.yaml"


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _run(cmd: list[str], *, env: dict[str, str] | None = None) -> None:
    subprocess.run(cmd, check=True, env=env)


def _run_quiet(cmd: list[str], *, env: dict[str, str] | None = None) -> None:
    subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)


def _container_running() -> bool:
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", CONTAINER_NAME],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip().lower() == "true"


def _collector_logs() -> str:
    result = subprocess.run(
        ["docker", "logs", CONTAINER_NAME],
        check=False,
        capture_output=True,
        text=True,
    )
    return f"{result.stdout}{result.stderr}"


def _prepare_dump_dir(dump_dir: Path) -> Path:
    """Host dir bind-mounted into the collector (uid 10001 must be able to write)."""
    dump_dir.mkdir(parents=True, exist_ok=True)
    dump_path = dump_dir / COLLECTOR_DUMP_BASENAME
    dump_path.touch()
    dump_dir.chmod(0o777)
    dump_path.chmod(0o666)
    return dump_path


def _start_collector(*, image: str, dump_dir: Path) -> None:
    _run_quiet(["docker", "rm", "-f", CONTAINER_NAME])
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
            f"{dump_dir}:{COLLECTOR_DUMP_MOUNT}",
            image,
            "--config",
            "/etc/otelcol/config.yaml",
        ]
    )
    deadline = time.time() + 30.0
    host = "127.0.0.1"
    port = 4318
    while time.time() < deadline:
        if not _container_running():
            raise RuntimeError(
                f"collector exited before opening {host}:{port}:\n{_collector_logs()}"
            )
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError(f"collector did not become ready on {host}:{port}:\n{_collector_logs()}")


def _wait_for_dump(dump_path: Path, *, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if dump_path.is_file() and dump_path.stat().st_size > 0:
            return
        if not _container_running():
            raise RuntimeError(f"collector exited before writing dump:\n{_collector_logs()}")
        time.sleep(0.25)
    raise RuntimeError(f"collector dump stayed empty:\n{_collector_logs()}")


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
        default=os.environ.get("MERGECRAFT_OTEL_COLLECTOR_IMAGE", _default_collector_image()),
    )
    args = parser.parse_args(argv)
    pytest_args = [
        "tests/tracing/test_otlp_collector_e2e.py",
        "-v",
        "--tb=short",
        "--runxfail",
    ]
    pre_seed_tests = _pytest_k(OTLP_PRE_SEED_TESTS)
    post_seed_tests = _pytest_k(OTLP_POST_SEED_TESTS)

    if not _docker_available():
        print("skipped: no docker", file=sys.stderr)
        if os.environ.get("MERGECRAFT_ALLOW_NO_DOCKER") == "1":
            return 0
        if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
            return 1
        return 0

    slice_rc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "check_otlp_e2e_slices.py")],
        cwd=REPO_ROOT,
        check=False,
    ).returncode
    if slice_rc != 0:
        return slice_rc

    endpoint = os.environ.get(
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        os.environ.get("MERGECRAFT_OTEL_ENDPOINT", "http://127.0.0.1:4318/v1/traces"),
    )
    with tempfile.TemporaryDirectory(prefix="mergecraft-otel-e2e-") as tmp:
        dump_dir = Path(tmp)
        dump_path = _prepare_dump_dir(dump_dir)
        env = os.environ.copy()
        env["MERGECRAFT_OTEL_COLLECTOR_DUMP"] = str(dump_path)
        env["OTEL_EXPORTER_OTLP_ENDPOINT"] = endpoint
        env["MERGECRAFT_OTEL_ENDPOINT"] = endpoint
        try:
            _start_collector(image=args.collector_image, dump_dir=dump_dir)
            _run(
                [sys.executable, "-m", "pytest", *pytest_args, "-k", pre_seed_tests],
                env=env,
            )
            if not _container_running():
                raise RuntimeError(f"collector exited during pre-seed tests:\n{_collector_logs()}")
            _seed_spans(endpoint=endpoint)
            _wait_for_dump(dump_path)
            _run(
                [sys.executable, "-m", "pytest", *pytest_args, "-k", post_seed_tests],
                env=env,
            )
        except Exception:
            sys.stderr.write(_collector_logs())
            raise
        finally:
            _stop_collector()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
