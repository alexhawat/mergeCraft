"""Per-agent run spans and attribution — OB4.1 RED suite (part 2 of 5).

Wave plan: ``.ignorelocal/waves/04-observability-eval-wave-plan.md`` (PR OB4,
sub-wave OB4.1, finding O8). Test-plan doc: ``docs/test-plans/04-observability-eval.md``.

Pins the OB4.2 ``agent_run_span`` context manager in
``mergecraft.tracing.signals`` (new): opens a ``mergecraft.agent.run`` span
carrying the agent's identity — ``mergecraft.agent.id`` (also mirrored to
``gen_ai.agent.name`` so Logfire's AI views group by agent),
``mergecraft.agent.role``, ``mergecraft.agent.lens``,
``mergecraft.agent.executed_model``, ``mergecraft.agent.prompt_version`` and
``mergecraft.agent.toolset`` — and binds that identity for the dynamic scope
(``signals.current_agent_id()``) so anything the agent touches can be
attributed.

D10: per-agent attribution comes from the MCP side. The identity is issued at
dispatch and must cross the process boundary —
``test_attribution_survives_the_subprocess_boundary`` pins the env contract at
the ``spawn_agent_cli`` boundary (``MERGECRAFT_AGENT_ID`` exported into the
child env, same setdefault discipline as OB1's review env), NOT anything inside
the harness subprocess, which mergeCraft cannot instrument (plan: Out of
scope).

The ``signals`` import is lazy (shared fixture in ``tests/tracing/conftest.py``),
which kept collection clean at RED-suite time; all four tests carried
non-strict ``xfail`` markers (``green after OB4.2``) until the post-OB4.2
reconciliation removed them (commit ``a3e9302`` made them XPASS), so all four
are now clean real passes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

from mergecraft.agents.shared import spawn_agent_cli
from mergecraft.utils import privilege as privilege_module

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


@pytest.fixture
def tracer_and_sink() -> dict[str, Any]:
    """A real ``MemorySink`` wired to a ``Tracer`` with explicit correlation ids."""
    from mergecraft.tracing import MemorySink, Tracer

    sink = MemorySink()
    tracer = Tracer(
        sink=sink,
        session_id="session-ob4",
        run_id="run-ob4",
        trace_id="trace-ob4",
    )
    return {"sink": sink, "tracer": tracer}


@pytest.fixture
def captured_popen(monkeypatch: MonkeyPatch) -> list[dict[str, Any]]:
    """Capture every ``subprocess.Popen`` call's argv + kwargs (non-root)."""
    import mergecraft.agents.shared as shared_module

    calls: list[dict[str, Any]] = []

    def _fake_popen(cmd: list[str], **kwargs: object) -> object:
        calls.append({"cmd": cmd, "kwargs": kwargs})
        return MagicMock()

    monkeypatch.setattr(shared_module.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(privilege_module.os, "getuid", lambda: 501)
    return calls


def test_agent_run_span_carries_identity(
    tracer_and_sink: dict[str, Any], signals_module: Any
) -> None:
    """O8 — an agent run span carries id, role, lens, executed model, prompt version, toolset."""
    signals = signals_module
    tracer = tracer_and_sink["tracer"]
    sink = tracer_and_sink["sink"]

    with signals.agent_run_span(
        tracer,
        agent_id="reviewer-security-1",
        role="reviewer",
        lens="security",
        executed_model="claude-opus-test",
        prompt_version="3",
        toolset=["read_file", "run_analyzers"],
    ):
        pass

    event = sink.events[0]
    assert event.kind == "mergecraft.agent.run"
    assert event.attrs["mergecraft.agent.id"] == "reviewer-security-1"
    assert event.attrs["gen_ai.agent.name"] == "reviewer-security-1"
    assert event.attrs["mergecraft.agent.role"] == "reviewer"
    assert event.attrs["mergecraft.agent.lens"] == "security"
    assert event.attrs["mergecraft.agent.executed_model"] == "claude-opus-test"
    assert event.attrs["mergecraft.agent.prompt_version"] == "3"
    assert event.attrs["mergecraft.agent.toolset"] == ["read_file", "run_analyzers"]


def test_tool_calls_chain_under_their_agent(
    tracer_and_sink: dict[str, Any], signals_module: Any
) -> None:
    """O8/D10 — tool calls parent under their agent's span and carry its identity."""
    signals = signals_module
    tracer = tracer_and_sink["tracer"]
    sink = tracer_and_sink["sink"]

    with signals.agent_run_span(tracer, agent_id="reviewer-1", role="reviewer") as agent_span:
        assert signals.current_agent_id() == "reviewer-1"
        with tracer.start_span("tool.call") as tool_span:
            # The MCP server stamps the active agent identity onto each call
            # (D10); the identity must be resolvable from the dynamic scope.
            tool_span.set_attribute("mergecraft.agent.id", signals.current_agent_id())

    assert signals.current_agent_id() is None, "the identity binding ends with the span"

    by_kind = {event.kind: event for event in sink.events}
    tool_event = by_kind["tool.call"]
    assert tool_event.parent_span_id == agent_span.span_id
    assert tool_event.attrs["mergecraft.agent.id"] == "reviewer-1"
    assert by_kind["mergecraft.agent.run"].attrs["mergecraft.agent.id"] == "reviewer-1"


def test_two_agents_are_distinguishable_in_one_trace(
    tracer_and_sink: dict[str, Any], signals_module: Any
) -> None:
    """Two agents in one run produce two distinguishable spans — a fan-out tree, not a flat list."""
    signals = signals_module
    tracer = tracer_and_sink["tracer"]
    sink = tracer_and_sink["sink"]

    with signals.agent_run_span(tracer, agent_id="reviewer-1", role="reviewer"):
        pass
    with signals.agent_run_span(tracer, agent_id="verifier-1", role="verifier"):
        pass

    assert len(sink.events) == 2
    first, second = sink.events
    assert first.span_id != second.span_id
    assert first.attrs["mergecraft.agent.id"] == "reviewer-1"
    assert second.attrs["mergecraft.agent.id"] == "verifier-1"
    assert first.attrs["mergecraft.agent.role"] != second.attrs["mergecraft.agent.role"]


def test_attribution_survives_the_subprocess_boundary(
    captured_popen: list[dict[str, Any]],
    tracer_and_sink: dict[str, Any],
    monkeypatch: MonkeyPatch,
    signals_module: Any,
) -> None:
    """D10 — the dispatch-issued agent id reaches the harness subprocess env.

    Pinned at the ``spawn_agent_cli`` boundary (the single choke point for all
    five drivers): inside an ``agent_run_span`` the child env carries
    ``MERGECRAFT_AGENT_ID`` so the MCP server can attribute that agent's calls.
    mergeCraft cannot instrument inside the subprocess (plan: Out of scope) —
    the env handoff IS the boundary contract. Exported via setdefault: a
    caller-supplied value wins, and the caller's env dict is never mutated.
    """
    signals = signals_module
    tracer = tracer_and_sink["tracer"]
    monkeypatch.delenv("MERGECRAFT_AGENT_ID", raising=False)
    caller_env = {"PATH": "/usr/bin", "HOME": "/home/dev"}

    with signals.agent_run_span(tracer, agent_id="verifier-1", role="verifier"):
        spawn_agent_cli(["codex", "exec"], env=caller_env)
        spawn_agent_cli(
            ["codex", "exec"],
            env={"PATH": "/usr/bin", "MERGECRAFT_AGENT_ID": "caller-pinned"},
        )

    assert len(captured_popen) == 2
    injected_env = captured_popen[0]["kwargs"]["env"]
    pinned_env = captured_popen[1]["kwargs"]["env"]
    assert injected_env["MERGECRAFT_AGENT_ID"] == "verifier-1"
    assert pinned_env["MERGECRAFT_AGENT_ID"] == "caller-pinned", "setdefault, not overwrite"
    assert "MERGECRAFT_AGENT_ID" not in caller_env, "the caller's env dict must not be mutated"
