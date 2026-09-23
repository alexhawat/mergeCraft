"""Agent-attempt spans distinguish executed and unvisited chain entries.

The configured fallback index is stable even when an earlier entry wins.
Executed entries report their result status; entries after a terminal success
or nonretryable failure emit ``not_visited`` spans and never call ``run_once``.

Driving strategy: build a fake ``run_once`` that returns a canned
``AgentResult`` per executed index, so exhausting the iterator catches an
unexpected call to a later model. The tests pin:

- For a 3-entry chain that returns ``success=True`` on entry 0: one executed
  span and two ``not_visited`` spans.
- For a 3-entry chain that returns ``retryable=True`` on entry 0 then
  ``success=True`` on entry 1: two executed spans, indices 0 and 1.
- For a 3-entry chain where entry 0 fails nonretryably: one executed span and
  two ``not_visited`` spans.

Every case asserts the ``model.fallback_index`` attribute.
"""

from __future__ import annotations

from typing import Any

from tests.tracing.instrumentation.conftest import (
    make_agent_result,
    make_agent_usage,
)


def _build_settings(*, models: list[str], fallbacks: dict[str, list[str]] | None = None) -> Any:
    from mergecraft.config import RepoSettings

    payload: dict[str, Any] = {
        "tracing": {"enabled": True, "sinks": [{"type": "memory"}]},
        "models": models,
    }
    if fallbacks is not None:
        payload["modelFallbacks"] = fallbacks
    return RepoSettings.model_validate(payload)


def _drive_chain(settings: Any, results: list[Any]) -> Any:
    import asyncio

    from mergecraft.utils.agent_resolve import run_with_model_chain

    iterator = iter(results)

    async def run_once(slug: str) -> Any:
        return next(iterator)

    return asyncio.run(run_with_model_chain(settings=settings, run_once=run_once))


def test_success_stops_execution_and_marks_later_entries_not_visited(
    captured_sink: Any,
) -> None:
    """A successful first entry prevents either later model from executing."""
    settings = _build_settings(
        models=["anthropic/claude-sonnet", "openai/gpt-5", "google/gemini-pro"],
    )
    results = [make_agent_result(success=True, usage=make_agent_usage(agent="claude"))]
    winning_slug, result = _drive_chain(settings, results)
    assert winning_slug == "anthropic/claude-sonnet"
    assert result.success

    captured_sink.record()
    attempts = captured_sink.by_kind.get("agent.attempt", [])
    assert len(attempts) == 3
    indices = [attempt.attrs.get("model.fallback_index") for attempt in attempts]
    assert indices == [0, 1, 2]
    assert [attempt.status for attempt in attempts] == ["ok", "not_visited", "not_visited"]


def test_one_agent_attempt_span_per_retryable_failure(captured_sink: Any) -> None:
    """W3.2 (retried) — entry 0 fails retryably; entry 1 succeeds.

    Two attempts (one per visited entry); both spans carry their
    ``model.fallback_index`` and the failure status of entry 0.
    """
    settings = _build_settings(
        models=["anthropic/claude-sonnet", "openai/gpt-5"],
    )
    results = [
        make_agent_result(
            success=False,
            error="rate limited",
            retryable=True,
        ),
        make_agent_result(success=True, usage=make_agent_usage(agent="codex")),
    ]
    winning_slug, result = _drive_chain(settings, results)
    assert winning_slug == "openai/gpt-5"
    assert result.success

    captured_sink.record()
    attempts = captured_sink.by_kind.get("agent.attempt", [])
    assert len(attempts) == 2
    indices = [attempt.attrs.get("model.fallback_index") for attempt in attempts]
    assert indices == [0, 1]
    # First attempt's status should reflect the retryable failure — the
    # exact status string is W4's choice, but the span must mark it as
    # not-ok so downstream consumers can attribute the retry.
    assert attempts[0].status != "ok", (
        f"first retryable attempt should not be status=ok, got {attempts[0].status!r}"
    )
    assert attempts[1].status == "ok"


def test_nonretryable_failure_stops_execution(captured_sink: Any) -> None:
    """A nonretryable first failure does not call either configured fallback."""
    settings = _build_settings(
        models=["anthropic/claude-sonnet", "openai/gpt-5", "google/gemini-pro"],
    )
    results = [make_agent_result(success=False, error="invalid request")]
    winning_slug, result = _drive_chain(settings, results)
    assert winning_slug == "anthropic/claude-sonnet"
    assert not result.success

    captured_sink.record()
    attempts = captured_sink.by_kind.get("agent.attempt", [])
    assert [attempt.status for attempt in attempts] == ["error", "not_visited", "not_visited"]


def test_one_agent_attempt_span_when_chain_is_singleton(captured_sink: Any) -> None:
    """W3.2 (edge — single-entry chain) — exactly one span, index 0."""
    settings = _build_settings(models=["anthropic/claude-sonnet"])
    results = [make_agent_result(success=True, usage=make_agent_usage(agent="claude"))]
    winning_slug, _result = _drive_chain(settings, results)
    assert winning_slug == "anthropic/claude-sonnet"

    captured_sink.record()
    attempts = captured_sink.by_kind.get("agent.attempt", [])
    assert len(attempts) == 1
    assert attempts[0].attrs.get("model.fallback_index") == 0


def test_agent_attempt_span_carries_provider_model_and_mode(captured_sink: Any) -> None:
    """W3.2 (attrs) — the issue's §4 attributes on ``agent.attempt``.

    Each ``agent.attempt`` span must carry ``agent.provider``,
    ``agent.mode``, ``agent.cli_argv`` (redacted — see test_secrets),
    plus the fallback index. This test pins the non-redacted subset.
    """
    settings = _build_settings(models=["anthropic/claude-sonnet"])
    results = [make_agent_result(success=True, usage=make_agent_usage(agent="claude"))]
    _drive_chain(settings, results)

    captured_sink.record()
    attempts = captured_sink.by_kind.get("agent.attempt", [])
    assert len(attempts) == 1
    attrs = attempts[0].attrs
    assert attrs.get("agent.provider"), "agent.provider missing"
    assert attrs.get("agent.mode") == "claude", (
        f"agent.mode should be 'claude', got {attrs.get('agent.mode')!r}"
    )
    assert "model.fallback_index" in attrs


__all__ = [
    "test_agent_attempt_span_carries_provider_model_and_mode",
    "test_nonretryable_failure_stops_execution",
    "test_one_agent_attempt_span_per_retryable_failure",
    "test_one_agent_attempt_span_when_chain_is_singleton",
    "test_success_stops_execution_and_marks_later_entries_not_visited",
]
