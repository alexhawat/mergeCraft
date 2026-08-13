"""W7 — spans must reach a real OTLP collector (#143), not the in-memory processor."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pytest
from tests.ci.workflow_support import REPO_ROOT, assert_third_party_uses_sha_pinned, read_text

_W7 = pytest.mark.xfail(
    reason="green after W7: OTLP collector e2e (spans leave the process)",
    strict=False,
)

_GEN_AI_ATTRS = (
    "gen_ai.operation.name",
    "gen_ai.request.model",
    "gen_ai.usage.input_tokens",
    "gen_ai.usage.output_tokens",
)


def _dump_path() -> Path:
    raw = os.environ.get("MERGECRAFT_OTEL_COLLECTOR_DUMP", "")
    if not raw:
        pytest.fail(
            "MERGECRAFT_OTEL_COLLECTOR_DUMP is required — collector file exporter dump "
            "(do not fall back to in-memory recording processor)"
        )
    path = Path(raw)
    if not path.is_file():
        pytest.fail(f"collector dump missing: {path}")
    return path


def _load_dump() -> Any:
    text = _dump_path().read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return [json.loads(line) for line in text.splitlines() if line.strip()]


@pytest.mark.integration
@_W7
def test_spans_arrive_at_real_collector_with_gen_ai_attributes() -> None:
    dump = _load_dump()
    blob = json.dumps(dump)
    assert "MemorySink" not in blob
    missing = [name for name in _GEN_AI_ATTRS if name not in blob]
    assert not missing, f"collector dump missing gen_ai attributes: {missing}"


@pytest.mark.integration
@_W7
def test_one_trace_per_run_holds_against_the_collector() -> None:
    dump = _load_dump()
    ids: set[str] = set()

    def collect(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"traceId", "trace_id"} and isinstance(value, str) and value:
                    ids.add(value)
                else:
                    collect(value)
        elif isinstance(node, list):
            for item in node:
                collect(item)

    collect(dump)
    assert ids, "collector dump has no trace ids"
    assert len(ids) == 1, f"one-trace-per-run violated at collector: {ids}"


@pytest.mark.integration
@_W7
def test_env_cli_yaml_precedence_resolves_to_live_sink() -> None:
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or os.environ.get(
        "MERGECRAFT_OTEL_ENDPOINT", ""
    )
    assert endpoint, "live collector endpoint env is unset"
    from mergecraft.config import RepoSettings
    from mergecraft.tracing import sink_factory
    from mergecraft.tracing.exporters import last_otel_endpoint

    settings = RepoSettings.model_validate(
        {
            "tracing": {
                "enabled": True,
                "sinks": [{"type": "otel", "endpoint": endpoint}],
            }
        }
    ).tracing
    sink = sink_factory(settings)
    assert type(sink).__name__ != "MemorySink"
    resolved = last_otel_endpoint()
    assert resolved is not None
    host = urlparse(endpoint).hostname or endpoint
    assert host in str(resolved)


@pytest.mark.integration
@_W7
def test_wrong_exporter_endpoint_fails_the_job() -> None:
    """Guard-deletion: exporting only to a closed port must not produce a collector dump."""
    from mergecraft.config import RepoSettings
    from mergecraft.tracing import sink_factory
    from mergecraft.tracing.event import TraceEvent

    settings = RepoSettings.model_validate(
        {
            "tracing": {
                "enabled": True,
                "sinks": [{"type": "otel", "endpoint": "http://127.0.0.1:1/v1/traces"}],
            }
        }
    ).tracing
    sink = sink_factory(settings)
    event = TraceEvent(
        kind="llm.call",
        span_id="1",
        session_id="s",
        turn_id="t",
        tier="trusted",
        ts_start_ns=0,
        ts_end_ns=1,
        status="ok",
        attrs={"gen_ai.operation.name": "chat"},
    )
    writer = getattr(sink, "write", None)
    if callable(writer):
        writer(event)
    dump = os.environ.get("MERGECRAFT_OTEL_COLLECTOR_DUMP")
    assert dump, "collector dump path unset — wrong-endpoint gate is not wired"
    if Path(dump).is_file():
        blob = Path(dump).read_text(encoding="utf-8")
        assert "gen_ai.operation.name" not in blob, (
            "wrong endpoint still produced collector traffic (failure swallowed)"
        )


@_W7
def test_unguarded_set_tracer_provider_swallow_would_fail_the_job() -> None:
    source = (REPO_ROOT / "src" / "mergecraft" / "tracing" / "exporters.py").read_text(
        encoding="utf-8"
    )
    assert "set_tracer_provider" in source
    assert "is_proxy" in source or "Overriding of current TracerProvider is not allowed" in source
    after = source.split("set_tracer_provider", 1)[1][:1200]
    assert "return None" not in after or "REUSE the existing provider" in source


@pytest.mark.integration
@_W7
def test_tracing_disabled_is_true_noop_no_collector_traffic() -> None:
    from mergecraft.config import RepoSettings
    from mergecraft.tracing import sink_factory
    from mergecraft.tracing.sinks import NullSink

    settings = RepoSettings.model_validate({"tracing": {"enabled": False}}).tracing
    sink = sink_factory(settings)
    assert isinstance(sink, NullSink)
    dump = os.environ.get("MERGECRAFT_OTEL_COLLECTOR_DUMP")
    before = Path(dump).read_text(encoding="utf-8") if dump and Path(dump).is_file() else ""
    emit = getattr(sink, "write", None) or getattr(sink, "emit", None)
    if callable(emit):
        emit("llm.call", lambda: {"gen_ai.operation.name": "chat"})
    if dump and Path(dump).is_file():
        after = Path(dump).read_text(encoding="utf-8")
        assert after == before, "disabled tracing sent traffic to the collector"


@_W7
def test_collector_image_is_digest_pinned_in_ci() -> None:
    haystack = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
    )
    assert "otel/opentelemetry-collector" in haystack
    idx = haystack.find("otel/opentelemetry-collector")
    assert "@sha256:" in haystack[idx : idx + 500]


@_W7
def test_make_target_invokes_collector_suite() -> None:
    makefile = read_text("Makefile")
    assert re.search(r"otlp|collector", makefile, re.IGNORECASE)


def test_w7_touched_workflows_remain_sha_pinned() -> None:
    for name in ("integration.yml", "ci-cd.yml", "e2e.yml"):
        path = REPO_ROOT / ".github" / "workflows" / name
        if path.is_file():
            assert_third_party_uses_sha_pinned(name)
