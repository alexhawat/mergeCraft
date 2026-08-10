"""Shared fixtures for the W5 stream-json migration RED suite.

What this conftest pins:

- **Recorded stream fixtures.** Three realistic NDJSON sessions — a Claude
  ``stream-json`` session with two message turns and one tool call, a codex
  ``exec --json`` session with the same shape, and a malformed-stream session
  that drops a corrupted line in the middle. These are byte-for-byte the
  fixtures W6 will assert against; changing them moves the contract.
- **Driver subprocess monkeypatch.** A helper that swaps ``subprocess.run``
  (current driver shape) and ``subprocess.Popen`` (the W6 likely shape) for
  fakes that deliver the recorded stream. The test marks the assertion
  ``xfail`` until W6 wires the streaming read loop.
- **MemorySink + Tracer capture.** A fixture that resolves ``RepoSettings``
  to a live ``MemorySink`` via ``sink_factory`` and exposes a ``CapturedSink``
  for assertions. The W6 impl must route the per-event spans into this sink
  via the standard tracer pathway (``get_tracer_from_settings``).

The conftest is intentionally additive — it does **not** shadow the parent
``tests/tracing/conftest.py`` or ``tests/tracing/instrumentation/conftest.py``.
"""

from __future__ import annotations

import importlib
import io
import json
import subprocess
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest

# ----------------------------------------------------------------------------
# Recorded stream fixtures
# ----------------------------------------------------------------------------
#
# Each fixture is a list of dicts that maps 1:1 to a real stream-json line.
# The test serializes via ``json.dumps`` + newline so the fixture is what an
# observer of ``stdout`` would see. The Claude shape mirrors
# ``agents/claude.py``'s documented ``--output-format stream-json`` event set
# (W0.5 table); the codex shape mirrors ``codex exec --json``.

# A realistic two-turn Claude stream-json session. Turn 1 reads a file
# (one tool_use + tool_result); turn 2 produces the final assistant text
# and a ``result`` event carrying ``usage`` and ``total_cost_usd``.
CLAUDE_TOOL_CALL_STREAM: list[dict[str, Any]] = [
    {
        "type": "message_start",
        "message": {
            "id": "msg_1",
            "role": "assistant",
            "usage": {"input_tokens": 100, "output_tokens": 0},
        },
    },
    {
        "type": "content_block_start",
        "index": 0,
        "content_block": {"type": "text", "text": ""},
    },
    {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "text_delta", "text": "Reading the diff..."},
    },
    {"type": "content_block_stop", "index": 0},
    {
        "type": "content_block_start",
        "index": 1,
        "content_block": {
            "type": "tool_use",
            "id": "tu_read_1",
            "name": "Read",
            "input": {"file_path": "src/foo.py"},
        },
    },
    {
        "type": "content_block_delta",
        "index": 1,
        "delta": {"type": "input_json_delta", "partial_json": ""},
    },
    {"type": "content_block_stop", "index": 1},
    {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
    {"type": "message_stop"},
    {
        "type": "tool_result",
        "tool_use_id": "tu_read_1",
        "content": "x = 1\n",
    },
    {
        "type": "message_start",
        "message": {
            "id": "msg_2",
            "role": "assistant",
            "usage": {"input_tokens": 50, "output_tokens": 0},
        },
    },
    {
        "type": "content_block_start",
        "index": 0,
        "content_block": {"type": "text", "text": ""},
    },
    {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "text_delta", "text": "Review complete."},
    },
    {"type": "content_block_stop", "index": 0},
    {
        "type": "message_delta",
        "delta": {"stop_reason": "end_turn", "usage": {"output_tokens": 20}},
    },
    {"type": "message_stop"},
    {
        "type": "result",
        "result": "Review complete: 1 issue found",
        "usage": {"input_tokens": 150, "output_tokens": 20},
        "total_cost_usd": 0.001,
    },
]


# A simpler codex ``exec --json`` session — one turn, one tool call, one
# result event. Mirrors what ``codex.py`` parses today via
# ``_parse_codex_stdout`` but in the streaming-incremental form W6 will
# consume.
CODEX_TOOL_CALL_STREAM: list[dict[str, Any]] = [
    {
        "type": "thread.started",
        "thread_id": "thread_1",
    },
    {
        "type": "item.started",
        "item": {"type": "tool_call", "id": "tc_1", "name": "Read"},
    },
    {
        "type": "item.completed",
        "item": {
            "type": "tool_call",
            "id": "tc_1",
            "name": "Read",
            "input": {"file_path": "src/foo.py"},
        },
    },
    {
        "type": "item.completed",
        "item": {
            "type": "tool_result",
            "tool_use_id": "tc_1",
            "content": "x = 1\n",
        },
    },
    {
        "type": "message.completed",
        "message": {"role": "assistant", "content": "Reviewed."},
    },
    {
        "type": "turn.completed",
        "usage": {"input_tokens": 80, "output_tokens": 30},
        "total_cost_usd": 0.0005,
    },
]


# A session where one line is intentionally malformed (truncated JSON). The
# parser must skip the bad line and continue to the next event — same pattern
# as ``read_jsonl_events`` in ``tracing/sinks.py``.
MALFORMED_STREAM: list[dict[str, Any] | str] = [
    {"type": "message_start", "message": {"id": "msg_1", "usage": {"input_tokens": 10}}},
    '{"type": "message_start", "message": {"id": "msg_2", "us',  # truncated
    {"type": "content_block_start", "index": 0, "content_block": {"type": "text"}},
    {"type": "content_block_stop", "index": 0},
    {"type": "message_stop"},
    {"type": "result", "result": "ok", "usage": {"input_tokens": 10, "output_tokens": 0}},
]


def serialize_stream(stream: list[dict[str, Any] | str]) -> str:
    """Render a recorded stream as a newline-delimited JSON string."""
    out: list[str] = []
    for item in stream:
        if isinstance(item, str):
            out.append(item)
        else:
            out.append(json.dumps(item))
    return "\n".join(out) + "\n"


def stream_lines(stream: list[dict[str, Any] | str]) -> Iterator[str]:
    """Yield one line per stream entry, mirroring ``stdout`` byte-for-byte."""
    for item in stream:
        if isinstance(item, str):
            yield item
        else:
            yield json.dumps(item)


# ----------------------------------------------------------------------------
# Drive harness support
# ----------------------------------------------------------------------------


@dataclass(slots=True)
class CapturedSink:
    """Wrap a ``MemorySink`` and surface the events by ``kind``."""

    memory: Any = None
    events: list[Any] = field(default_factory=list)
    by_kind: dict[str, list[Any]] = field(default_factory=dict)

    def record(self) -> None:
        """Refresh the caches from the underlying ``MemorySink``."""
        self.events = list(self.memory.events)
        self.by_kind = {}
        for event in self.events:
            kind = getattr(event, "kind", None)
            if not isinstance(kind, str):
                continue
            self.by_kind.setdefault(kind, []).append(event)

    @property
    def kinds(self) -> list[str]:
        return [getattr(event, "kind", None) for event in self.events]


def _build_memory_tracing_settings() -> Any:
    """Build ``RepoSettings`` carrying a single ``memory`` tracing sink."""
    from mergecraft.config import RepoSettings

    return RepoSettings.model_validate(
        {
            "tracing": {
                "enabled": True,
                "sinks": [{"type": "memory"}],
            },
        }
    )


@pytest.fixture
def captured_streaming_sink() -> CapturedSink:
    """Resolve ``RepoSettings.tracing`` to a live ``MemorySink``.

    W6 must route the per-event spans (``tool.call`` / ``llm.call``) through
    the standard tracer pathway so the assertions below see them. The
    fixture's ``by_kind`` helper makes the assertion shape stable across
    the W6 implementation.
    """
    from mergecraft.tracing import sink_factory

    settings = _build_memory_tracing_settings()
    sink = sink_factory(settings.tracing)
    memory = sink.inner.sinks[0]
    return CapturedSink(memory=memory)


@pytest.fixture
def disabled_streaming_sink() -> Any:
    """A ``NullSink`` resolved for the disabled-path tracing case.

    Used by W5.4 to verify that ``utils/activity.py``'s idle-detection
    behaviour is unaffected by tracing state (convention 9).
    """
    from mergecraft.config import RepoSettings
    from mergecraft.tracing import NullSink, sink_factory

    sink = sink_factory(RepoSettings.model_validate({}).tracing)
    assert isinstance(sink, NullSink)
    return sink


def _build_agent_run_context(
    tmp_path: Any,
    *,
    resolved_model: str | None = "anthropic/claude-sonnet-5",
) -> Any:
    """Build a minimal ``AgentRunContext`` for a recorded-stream driver call."""
    from mergecraft.agents.shared import AgentRunContext, ResolvedInstructions
    from mergecraft.mcp.context import PayloadEvent, ResolvedPayload
    from mergecraft.mcp.tool_state import init_tool_state

    return AgentRunContext(
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request")),
        mcp_server_url="http://127.0.0.1:0/mcp",
        tmpdir=str(tmp_path),
        subagent_denied_tools=(),
        instructions=ResolvedInstructions(user="review this diff"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        resolved_model=resolved_model,
    )


@pytest.fixture
def make_agent_run_context(tmp_path: Any) -> Callable[..., Any]:
    """Return a factory for ``AgentRunContext`` rooted in ``tmp_path``."""

    def _factory(**kwargs: Any) -> Any:
        return _build_agent_run_context(tmp_path, **kwargs)

    return _factory


# ----------------------------------------------------------------------------
# Subprocess monkeypatching
# ----------------------------------------------------------------------------
#
# W6 will likely switch from ``subprocess.run(..., capture_output=True)`` to
# ``subprocess.Popen`` for line-by-line consumption. The helpers below patch
# both surfaces so the test stays agnostic to which path W6 picks.


class _FakePopen:
    """Minimal ``subprocess.Popen`` look-alike that delivers a recorded stream.

    Exposes ``stdout`` / ``stderr`` as ``io.BytesIO`` so a streaming consumer
    can iterate; a ``communicate`` shim returns the full bytes for the
    non-streaming call site. ``returncode`` honours the call site contract.
    """

    def __init__(
        self,
        args: Any,
        *,
        stdout_blob: bytes,
        stderr_blob: bytes,
        returncode: int,
        **kwargs: Any,
    ) -> None:
        self.args = args
        self._stdout = io.BytesIO(stdout_blob)
        self._stderr = io.BytesIO(stderr_blob)
        self.stdout: Any = self._stdout
        self.stderr: Any = self._stderr
        self.returncode = returncode
        self._closed = False

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode

    def poll(self) -> int | None:
        return self.returncode

    def communicate(
        self, input: bytes | None = None, timeout: float | None = None
    ) -> tuple[bytes, bytes]:
        del input, timeout
        out = self._stdout.getvalue()
        err = self._stderr.getvalue()
        self._closed = True
        return out, err

    def __enter__(self) -> _FakePopen:
        return self

    def __exit__(self, *args: Any) -> None:
        self._closed = True


@pytest.fixture
def patch_driver_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[..., dict[str, Any]]:
    """Return a callable that patches a driver module's subprocess to a fake.

    Usage::

        def test_xxx(patch_driver_subprocess):
            recorded = patch_driver_subprocess(
                "mergecraft.agents.claude",
                stdout="<recorded stream>",
                stderr="",
                returncode=0,
            )
            # ... driver invocation ...
            assert recorded["cmd"]  # the argv it was invoked with
    """

    invocations: list[dict[str, Any]] = []

    def _patch(
        module_name: str,
        *,
        stdout: str,
        stderr: str = "",
        returncode: int = 0,
    ) -> dict[str, Any]:
        stdout_blob = stdout.encode("utf-8")
        stderr_blob = stderr.encode("utf-8")

        def _recording_run(cmd: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            invocations.append(
                {
                    "cmd": list(cmd),
                    "stdout": stdout,
                    "stderr": stderr,
                    "returncode": returncode,
                }
            )
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=returncode,
                stdout=stdout,
                stderr=stderr,
            )

        def _recording_popen(args: Any, **kwargs: Any) -> _FakePopen:
            invocations.append({"cmd": list(args) if args else [], "stdout": stdout})
            return _FakePopen(
                args,
                stdout_blob=stdout_blob,
                stderr_blob=stderr_blob,
                returncode=returncode,
                **kwargs,
            )

        module = importlib.import_module(module_name)
        monkeypatch.setattr(module.subprocess, "run", _recording_run)
        monkeypatch.setattr(module.subprocess, "Popen", _recording_popen)
        return invocations[-1] if invocations else {}

    return _patch
