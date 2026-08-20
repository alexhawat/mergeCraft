"""Shared fixtures for tracing contract tests."""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable


@pytest.fixture(autouse=True)
def _reset_process_tracer_cache() -> Iterator[None]:
    """Reset the process-wide Tracer cache introduced in W4 (#292).

    Each test that creates a ``MemorySink`` or ``_RaisingSink`` and then
    exercises the emit path via ``run_with_model_chain`` must see spans on
    *its own* sink, not on a cached tracer from a sibling test.  Autouse
    ensures this without requiring every test function to import the seam.
    """
    from mergecraft.tracing.tracer import reset_process_tracer_cache

    reset_process_tracer_cache()
    yield
    reset_process_tracer_cache()


@pytest.fixture
def trace_dir(tmp_path: Path) -> Path:
    return tmp_path / ".mergecraft" / "traces"


@pytest.fixture
def fake_attrs() -> dict[str, Any]:
    return {"model.id": "anthropic/claude-sonnet", "attempt": 1}


@pytest.fixture
def trace_event_data(fake_attrs: dict[str, Any]) -> dict[str, Any]:
    # T3.1 — `trace_id` is the Logfire/OTel trace identifier shared by every
    # span in one run (D7 / T3.2). Including it here pins the round-trip
    # fixture across every test that validates ``event.model_dump()``.
    return {
        "kind": "llm.call",
        "span_id": "span-1",
        "parent_span_id": None,
        "session_id": "run-1",
        "turn_id": "turn-1",
        "tier": "trusted",
        "ts_start_ns": 1_000,
        "ts_end_ns": 2_000,
        "status": "ok",
        "attrs": fake_attrs,
        "trace_id": "trace-fixture-0001",
    }


@pytest.fixture
def review_context_module() -> Any:
    """Lazily import the OB1.2 review-context module (``tracing/review_context.py``).

    The module does not exist until the OB1.2 implementation wave lands it.
    Importing inside the fixture (rather than at module top level) keeps test
    collection clean — zero collection errors — while every dependent test
    still fails RED at runtime under its non-strict ``xfail`` marker.
    """
    return importlib.import_module("mergecraft.tracing.review_context")


@pytest.fixture
def review_context_factory(review_context_module: Any) -> Callable[..., Any]:
    """Build a fully populated ``ReviewContext`` with benign defaults.

    Field names pin the OB1.2 contract (plan §OB1.2 File 1): ``review_id``,
    ``correlation_key``, ``attempt``, ``source``, ``repo``, ``pr_number``,
    ``base_ref``/``base_sha``/``head_ref``/``head_sha``, ``mode``, ``trigger``,
    ``trust_tier``.
    """

    def _make(**overrides: Any) -> Any:
        fields: dict[str, Any] = {
            "review_id": "review-ob1-0001",
            "correlation_key": "c" * 64,
            "attempt": 1,
            "source": "action",
            "repo": "octo/mergecraft",
            "pr_number": 42,
            "base_ref": "main",
            "base_sha": "0" * 40,
            "head_ref": "feature/ob1-review-correlation",
            "head_sha": "f" * 40,
            "mode": "review",
            "trigger": "pull_request",
            "trust_tier": "trusted",
        }
        fields.update(overrides)
        return review_context_module.ReviewContext(**fields)

    return _make


@pytest.fixture
def genai_module() -> Any:
    """Lazily import the OB3.2 GenAI builders module (``tracing/genai.py``).

    The module does not exist until the OB3.2 implementation wave lands it.
    Importing inside the fixture (rather than at module top level) keeps test
    collection clean — zero collection errors — while every dependent test
    still fails RED at runtime under its non-strict ``xfail`` marker.
    """
    return importlib.import_module("mergecraft.tracing.genai")


@pytest.fixture
def signals_module() -> Any:
    """Lazily import the OB4.2 outcome-spans module (``tracing/signals.py``).

    The module does not exist until the OB4.2 implementation wave lands it.
    Importing inside the fixture (rather than at module top level) keeps test
    collection clean — zero collection errors — while every dependent test
    still fails RED at runtime under its non-strict ``xfail`` marker.
    """
    return importlib.import_module("mergecraft.tracing.signals")
