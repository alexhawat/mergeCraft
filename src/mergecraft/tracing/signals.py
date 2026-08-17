"""Outcome and attribution signal spans (OB4 — O8/O9, D10/D12).

Module: mergecraft.tracing.signals
Depends: mergecraft.tracing.{content,tracer}, loguru

The spans that make the pipeline and its conclusions legible:

- ``mergecraft.phase`` — one point span per review-lifecycle phase
  (``emit_phase``). The phase vocabulary is the EXISTING
  ``mcp/verdict.py::ReviewPhase`` enum — reused, never redeclared. A run
  that dies before ``SUBMIT`` leaves a trace whose phase list visibly
  stops: the fail-closed case is diagnosable at a glance.
- ``mergecraft.agent.run`` — one span per dispatched agent
  (``agent_run_span``), carrying the dispatch-issued identity
  (``mergecraft.agent.id``, mirrored to ``gen_ai.agent.name`` for Logfire's
  AI views) plus role/lens/executed model/prompt version/toolset. The id
  is bound for the dynamic scope (``current_agent_id()``) and exported
  across the ``spawn_agent_cli`` boundary as ``MERGECRAFT_AGENT_ID`` (D10)
  so the MCP server can attribute that agent's ``tool.call`` spans —
  mergeCraft cannot instrument inside the harness subprocess (plan: Out of
  scope), so the env handoff IS the boundary contract.
- ``mergecraft.finding`` — finding lifecycle events keyed by fingerprint
  (``proposed`` → ``verified`` → ``published`` / ``withdrawn``); the body
  rides under the OB2 content policy via ``capture_text`` (convention 4).
- ``mergecraft.verdict`` — the run's terminal verdict: agent + structural
  verdicts, the emitter-DERIVED disagreement flag (never caller-supplied —
  a rubber-stamping gate cannot hide the mismatch by omitting it),
  findings counts, and ``fallback_reason`` (omitted when unset, never
  null).
- ``mergecraft.eval.score`` — one span per scored eval case, each metric
  its own ``mergecraft.eval.<metric>`` attribute (a zero is real data).
  Spans AND files (D12): the span inherits the active ``review.id`` via
  the OB1 D4 close-time merge, which makes the eval↔trace join free.

Convention 3: every emitter is total and non-throwing — ``None`` /
``NullTracer`` is a silent no-op, a malformed payload degrades to a missing
row. Convention 5: a normal review's signal spans are O(dozens), three
orders of magnitude under ``MAX_SPANS_PER_RUN``.

|Exports:
    Functions:
        emit_phase — ``mergecraft.phase`` point span.
        agent_run_span — ``mergecraft.agent.run`` context manager + identity binding.
        current_agent_id — the bound agent id (or None).
        emit_finding — ``mergecraft.finding`` lifecycle point span.
        emit_verdict — ``mergecraft.verdict`` point span (derived disagreement).
        emit_eval_score — ``mergecraft.eval.score`` point span.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.tracing.content import ContentCapture, capture_text

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from mergecraft.tracing.tracer import NullTracer, Span, Tracer

AGENT_ID_ENV_VAR = "MERGECRAFT_AGENT_ID"

_CURRENT_AGENT_ID: ContextVar[str | None] = ContextVar("mergecraft_current_agent_id", default=None)


def current_agent_id() -> str | None:
    """Return the agent id bound by :func:`agent_run_span`, or ``None``.

    Returns:
        str | None: The dispatch-issued agent identity inside an
        ``agent_run_span`` dynamic scope; ``None`` outside one.
    """
    return _CURRENT_AGENT_ID.get()


def _open_point_span(
    tracer: Tracer | NullTracer | None,
    kind: str,
    attrs: Mapping[str, Any],
) -> None:
    """Open-decorate-close one point span (the ``emit_verb_subevent`` discipline).

    ``None`` / ``NullTracer`` is a silent no-op; any failure degrades to a
    missing row (convention 3).
    """
    if tracer is None:
        return
    try:
        span = tracer.start_span(kind)
        span.__enter__()
        for key, value in attrs.items():
            try:
                span.set_attribute(key, value)
            except Exception as attr_exc:  # pragma: no cover — defensive
                logger.debug("signal span attr {} failed: {}", key, attr_exc)
        span.close()
    except Exception as exc:
        # Tracing must never fail the review (#56 D6).
        logger.debug("signal span {} failed: {}", kind, exc)


def emit_phase(tracer: Tracer | NullTracer | None, *, phase: Any) -> None:
    """Emit one ``mergecraft.phase`` point span for a review-lifecycle phase.

    Args:
        tracer: The tracer (``None`` / ``NullTracer`` → no-op).
        phase: A ``mcp/verdict.py::ReviewPhase`` member (the existing
            vocabulary — reused, never redeclared); its ``.value`` lands on
            ``mergecraft.phase.name``. Plain strings with the same shape are
            tolerated so callers never need a conversion dance.
    """
    _open_point_span(
        tracer,
        "mergecraft.phase",
        {"mergecraft.phase.name": getattr(phase, "value", str(phase))},
    )


@contextmanager
def agent_run_span(
    tracer: Tracer | NullTracer | None,
    *,
    agent_id: str,
    role: str,
    lens: str | None = None,
    executed_model: str | None = None,
    prompt_version: str | None = None,
    toolset: Any = (),
) -> Iterator[Span | Any]:
    """Open a ``mergecraft.agent.run`` span and bind the agent identity (O8/D10).

    The identity attrs land on the span; the id is additionally bound for
    the dynamic scope so ``current_agent_id()`` resolves inside the block
    (and ``spawn_agent_cli`` exports it as ``MERGECRAFT_AGENT_ID``). The
    binding ends with the span. When ``tracer`` is ``None``/``NullTracer``
    the span is a no-op but the identity still binds — attribution must not
    depend on the sink being enabled.

    Args:
        tracer: The tracer (``None`` / ``NullTracer`` → no-op span).
        agent_id (str): Dispatch-issued identity (also mirrored to
            ``gen_ai.agent.name`` so Logfire's AI views group by agent).
        role (str): The agent's role (``reviewer`` / ``verifier`` / …).
        lens (str | None): Review lens, when the agent carries one.
        executed_model (str | None): The model this agent actually ran
            (post-fallback — D11).
        prompt_version (str | None): The mode-prompt version.
        toolset: The tool names this agent may call.

    Yields:
        The opened span (``NullSpan`` on the disabled path).
    """
    token = _CURRENT_AGENT_ID.set(agent_id)
    span: Any = None
    try:
        if tracer is not None:
            try:
                span = tracer.start_span("mergecraft.agent.run")
                span.__enter__()
                attrs: dict[str, Any] = {
                    "mergecraft.agent.id": agent_id,
                    "gen_ai.agent.name": agent_id,
                    "mergecraft.agent.role": role,
                }
                if lens:
                    attrs["mergecraft.agent.lens"] = lens
                if executed_model:
                    attrs["mergecraft.agent.executed_model"] = executed_model
                if prompt_version:
                    attrs["mergecraft.agent.prompt_version"] = prompt_version
                if toolset:
                    attrs["mergecraft.agent.toolset"] = list(toolset)
                for key, value in attrs.items():
                    span.set_attribute(key, value)
            except Exception as exc:
                logger.debug("agent run span open failed: {}", exc)
                span = None
        yield span
    finally:
        if span is not None:
            try:
                span.close()
            except Exception as exc:  # pragma: no cover — defensive
                logger.debug("agent run span close failed: {}", exc)
        _CURRENT_AGENT_ID.reset(token)


def emit_finding(
    tracer: Tracer | NullTracer | None,
    *,
    fingerprint: str,
    stage: str,
    severity: str | None = None,
    category: str | None = None,
    message: str | None = None,
    policy: ContentCapture = ContentCapture.REDACTED,
) -> None:
    """Emit one ``mergecraft.finding`` lifecycle point span (O9).

    Keyed by ``mergecraft.finding.fingerprint`` with
    ``mergecraft.finding.stage`` (``proposed`` → ``verified`` →
    ``published`` / ``withdrawn``). The body rides under the OB2 content
    policy via ``capture_text`` at the ``mergecraft.finding.body`` prefix
    (convention 4 — no second policy mechanism): at ``metadata`` only the
    D8 hash + counts ship.

    Args:
        tracer: The tracer (``None`` / ``NullTracer`` → no-op).
        fingerprint (str): Stable finding identity across lifecycle stages.
        stage (str): The lifecycle stage being recorded.
        severity (str | None): Finding severity, when known.
        category (str | None): Finding category, when known.
        message (str | None): The finding body; captured under ``policy``.
        policy (ContentCapture): The resolved content-capture level
            (defaults to the D6 default ``redacted``).
    """
    attrs: dict[str, Any] = {
        "mergecraft.finding.fingerprint": fingerprint,
        "mergecraft.finding.stage": stage,
    }
    if severity:
        attrs["mergecraft.finding.severity"] = severity
    if category:
        attrs["mergecraft.finding.category"] = category
    if message:
        attrs.update(capture_text(message, "mergecraft.finding.body", policy))
    _open_point_span(tracer, "mergecraft.finding", attrs)


def emit_verdict(
    tracer: Tracer | NullTracer | None,
    *,
    agent_verdict: str,
    structural_verdict: str,
    published_count: int | None = None,
    withdrawn_count: int | None = None,
    fallback_reason: str | None = None,
) -> None:
    """Emit the run's ``mergecraft.verdict`` point span (O9).

    Carries the agent's terminal verdict (``approve`` / ``request_changes``
    — the existing ``mcp/verdict.py`` vocabulary) beside the structural
    verdict (``pass`` / ``fail``). ``mergecraft.verdict.disagreement`` is
    DERIVED here from the two verdicts — never caller-supplied — so a
    rubber-stamping gate cannot hide the mismatch (approve + fail, or
    request_changes + pass, is a disagreement). ``fallback_reason`` is
    omitted entirely (not null) when no fallback occurred.

    Args:
        tracer: The tracer (``None`` / ``NullTracer`` → no-op).
        agent_verdict (str): The agent's terminal verdict.
        structural_verdict (str): The structural/static-checks verdict.
        published_count (int | None): Findings published.
        withdrawn_count (int | None): Findings withdrawn.
        fallback_reason (str | None): Why a model fallback occurred.
    """
    agent_positive = agent_verdict == "approve"
    structural_positive = structural_verdict == "pass"
    attrs: dict[str, Any] = {
        "mergecraft.verdict.agent": agent_verdict,
        "mergecraft.verdict.structural": structural_verdict,
        "mergecraft.verdict.disagreement": agent_positive != structural_positive,
    }
    if published_count is not None:
        attrs["mergecraft.verdict.findings_published"] = published_count
    if withdrawn_count is not None:
        attrs["mergecraft.verdict.findings_withdrawn"] = withdrawn_count
    if fallback_reason:
        attrs["mergecraft.verdict.fallback_reason"] = fallback_reason
    _open_point_span(tracer, "mergecraft.verdict", attrs)


def emit_eval_score(
    tracer: Tracer | NullTracer | None,
    *,
    case_id: str,
    metrics: Mapping[str, Any],
) -> None:
    """Emit one ``mergecraft.eval.score`` point span per scored case (O9/D12).

    Each metric lands as its own ``mergecraft.eval.<metric>`` attribute — a
    zero is real data and is emitted. The span inherits the active
    ``review.id`` via the OB1 D4 close-time merge, which makes the
    eval↔trace join free (D12: spans AND files).

    Args:
        tracer: The tracer (``None`` / ``NullTracer`` → no-op).
        case_id (str): The corpus case identity.
        metrics: Metric name → value; every entry becomes an attribute.
    """
    attrs: dict[str, Any] = {"mergecraft.eval.case_id": case_id}
    for name, value in metrics.items():
        attrs[f"mergecraft.eval.{name}"] = value
    _open_point_span(tracer, "mergecraft.eval.score", attrs)


__all__ = [
    "AGENT_ID_ENV_VAR",
    "agent_run_span",
    "current_agent_id",
    "emit_eval_score",
    "emit_finding",
    "emit_phase",
    "emit_verdict",
]
