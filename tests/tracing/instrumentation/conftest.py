"""Shared fixtures for Batch B RED suite — span tree instrumentation.

The Batch A conftest (``tests/tracing/conftest.py``) owns the trace-dir and
event-data fixtures used by the config/sinks/redaction contracts. This
conftest is intentionally parallel and additive — it does **not** import or
shadow those fixtures.

What this conftest pins for W3:

- A factory that resolves ``RepoSettings.tracing`` to a live ``MemorySink``
  through the existing ``sink_factory`` (Batch A's public surface). W4 must
  make the production emit sites route through the same factory so the
  asserts below see the span tree.
- The minimum correlation attribute set required on the root span (W3.4):
  ``run_id``, ``repo``, ``pr_number``, ``commit_sha``, ``workflow_run_id``,
  ``job_id``.
- A fake ``run_once`` callable factory used to drive ``run_with_model_chain``
  with one canned ``AgentResult`` per fallback entry (W3.2). The fake raises
  or returns ``success=True`` on demand so the chain loop visits every
  entry — both the skipped and retried paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest


@dataclass(slots=True)
class CapturedSink:
    """Wrap a ``MemorySink`` and surface the events by ``kind``.

    W4's emit sites will land every span on a ``MemorySink`` wired through
    ``sink_factory``. To keep the assertions stable across the W4
    implementation, this wrapper only exposes ``by_kind`` / ``events`` /
    ``kinds`` — the shape, not the field ordering.
    """

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


@pytest.fixture
def captured_sink() -> CapturedSink:
    """Resolve ``RepoSettings.tracing`` to a live ``MemorySink``.

    W4 must expose the same ``sink_factory``-driven surface from
    ``mergecraft.tracing``; until then the returned ``CapturedSink.memory``
    starts empty and the xfail assertions below turn green.
    """
    from mergecraft.config import RepoSettings
    from mergecraft.tracing import sink_factory

    settings = RepoSettings.model_validate(
        {
            "tracing": {
                "enabled": True,
                "sinks": [{"type": "memory"}],
            }
        }
    ).tracing
    memory = sink_factory(settings).inner.sinks[0]
    return CapturedSink(memory=memory)


@pytest.fixture
def disabled_tracing(tmp_path: Path) -> Any:
    """Resolved ``NullSink`` for the convention-9 (disabled) assertions.

    Returns the raw ``NullSink`` so tests can also assert the type.
    """
    from mergecraft.config import RepoSettings
    from mergecraft.tracing import NullSink, sink_factory

    sink = sink_factory(RepoSettings.model_validate({}).tracing)
    assert isinstance(sink, NullSink)
    return sink


@pytest.fixture
def correlation_fields() -> dict[str, Any]:
    """The minimum correlation attributes W3.4 pins on the root span."""

    return {
        "run_id": "run-42",
        "repo": "alexhawat/mergeCraft",
        "pr_number": 99,
        "commit_sha": "deadbeef" * 5,
        "workflow_run_id": "1234567890",
        "job_id": "review",
    }


def make_agent_result(
    *,
    success: bool,
    error: str | None = None,
    retryable: bool = False,
    usage: Any | None = None,
) -> Any:
    """Build an ``AgentResult`` with optional ``retryable`` metadata."""

    from mergecraft.agents.shared import AgentResult

    metadata: dict[str, Any] = {}
    if retryable:
        metadata["retryable"] = True
    return AgentResult(
        success=success,
        error=error,
        metadata=metadata,
        usage=usage,
    )


def make_agent_usage(
    *,
    input_tokens: int = 100,
    output_tokens: int = 50,
    cache_read_tokens: int | None = None,
    cache_write_tokens: int | None = None,
    cost_usd: float | None = 0.001,
    agent: str = "claude",
) -> Any:
    """Build an ``AgentUsage`` with token and cost fields populated."""

    from mergecraft.agents.shared import AgentUsage

    return AgentUsage(
        agent=agent,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        cost_usd=cost_usd,
    )
