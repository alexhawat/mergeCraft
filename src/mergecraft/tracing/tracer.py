"""Best-effort span lifecycle for mergeCraft tracing.

Module: mergecraft.tracing.tracer
Depends: mergecraft.tracing.{event,sinks}, loguru

Exports:
    Classes:
        Tracer — Creates and emits real spans to a configured sink.
        Span — Context-managed trace span.
        NullTracer — Disabled tracing implementation.
        NullSpan — Disabled span implementation.
    Functions:
        resolve_correlation_from_env — Read GitHub correlation fields from the environment.
        resolve_session_id — Resolve or generate the trace session identifier.
        get_tracer_from_settings — Build a real or null tracer from repo settings.
"""

from __future__ import annotations

import os
import time
import uuid
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.tracing.event import TraceEvent
from mergecraft.tracing.resolve import resolve_active_tracing
from mergecraft.tracing.sinks import claim_sink

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

    from mergecraft.config.settings import RepoSettings


@dataclass(slots=True)
class Tracer:
    """Create spans and route completed events to one configured sink."""

    sink: object
    session_id: str
    run_id: str
    tier: str = "balanced"

    def current_span(self) -> Span | None:
        """Return this tracer's active span, if any."""
        active = _ACTIVE_SPAN.get()
        return active if isinstance(active, Span) and active.tracer is self else None

    def start_span(
        self,
        kind: str,
        *,
        parent_span_id: str | None = None,
        attrs_source: Callable[[], dict[str, Any]] | None = None,
    ) -> Span:
        """Create a span whose parent defaults to the active span.

        Args:
            kind (str): Canonical span kind.
            parent_span_id (str | None, optional): Explicit parent span identifier.
                Defaults to the active span when it belongs to this tracer.
            attrs_source (Callable[[], dict[str, Any]] | None, optional): Lazy attribute
                producer evaluated only when the span closes. Defaults to None.

        Returns:
            Span: A context-managed span ready to enter.

        Examples:
            >>> tracer = Tracer(sink=object(), session_id="session", run_id="run")
            >>> tracer.start_span("mergecraft.run").kind
            'mergecraft.run'
        """
        active = _ACTIVE_SPAN.get()
        resolved_parent = parent_span_id
        if resolved_parent is None and isinstance(active, Span) and active.tracer is self:
            resolved_parent = active.span_id
        return Span(
            tracer=self,
            kind=kind,
            parent_span_id=resolved_parent,
            span_id=uuid.uuid4().hex,
            session_id=self.session_id,
            turn_id=uuid.uuid4().hex,
            tier=self.tier,
            _attrs_source=attrs_source,
        )

    def _write(self, event: TraceEvent) -> None:
        """Write one event without allowing sink failures onto the review path.

        Args:
            event (TraceEvent): Completed trace event.

        Examples:
            >>> Tracer(sink=object(), session_id="session", run_id="run")._write
            <bound method Tracer._write of Tracer(sink=<object object at ...>, session_id='session', run_id='run', tier='balanced')>
        """
        write = getattr(self.sink, "write", None)
        if not callable(write):
            return
        try:
            write(event)
        except Exception as exc:
            logger.warning("trace sink {} failed: {}", type(self.sink).__name__, exc)


@dataclass(slots=True)
class Span:
    """Context-managed span that emits a ``TraceEvent`` when it closes."""

    tracer: Tracer
    kind: str
    parent_span_id: str | None
    span_id: str
    session_id: str
    turn_id: str
    tier: str
    status: str = "ok"
    error: str | None = None
    _attrs_source: Callable[[], dict[str, Any]] | None = None
    ts_start_ns: int = 0
    ts_end_ns: int = 0
    _attrs: dict[str, Any] = field(default_factory=dict)
    _exc: BaseException | None = None
    _context_token: Token[Span | NullSpan | None] | None = None

    def __enter__(self) -> Span:
        """Start timing and make this span active."""
        self.ts_start_ns = time.time_ns()
        self._context_token = _ACTIVE_SPAN.set(self)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close and emit the span without suppressing body exceptions.

        Args:
            exc_type (type[BaseException] | None): Exception type raised by the body.
            exc (BaseException | None): Exception raised by the body.
            tb (TracebackType | None): Exception traceback.
        """
        del exc_type, tb
        if exc is not None:
            self.record_exception(exc)
        self.ts_end_ns = time.time_ns()

        attrs: dict[str, Any] = {}
        if self._attrs_source is not None:
            try:
                attrs.update(self._attrs_source())
            except Exception as attrs_exc:
                logger.warning("trace span {} attributes failed: {}", self.kind, attrs_exc)
        attrs.update(self._attrs)
        if self.error is not None:
            attrs.setdefault("error", self.error)

        self.tracer._write(
            TraceEvent(
                kind=self.kind,
                span_id=self.span_id,
                parent_span_id=self.parent_span_id,
                session_id=self.session_id,
                turn_id=self.turn_id,
                tier=self.tier,
                ts_start_ns=self.ts_start_ns,
                ts_end_ns=self.ts_end_ns,
                status=self.status,
                attrs=attrs,
            )
        )
        if self._context_token is not None:
            _ACTIVE_SPAN.reset(self._context_token)
            self._context_token = None

    def set_attribute(self, key: str, value: Any) -> None:
        """Set or replace one span attribute.

        Args:
            key (str): Attribute key.
            value (Any): JSON-compatible attribute value.
        """
        self._attrs[key] = value

    def record_exception(self, exc: BaseException) -> None:
        """Record an exception and mark the span failed.

        Args:
            exc (BaseException): Exception observed by the span.
        """
        self._exc = exc
        self.set_status("error", str(exc) or type(exc).__name__)

    def set_status(self, status: str, error: str | None = None) -> None:
        """Set the span status and optional error message.

        Args:
            status (str): Status vocabulary value.
            error (str | None, optional): Human-readable error. Defaults to None.
        """
        self.status = status
        self.error = error


class NullSpan:
    """No-op context manager used while tracing is disabled."""

    span_id = ""
    parent_span_id: str | None = None
    status = "ok"

    def __enter__(self) -> NullSpan:
        """Return this no-op span."""
        return self

    def __exit__(self, *args: Any) -> None:
        """Ignore context-manager exit state.

        Args:
            *args (Any): Context-manager exception state.
        """

    def set_attribute(self, *args: Any) -> None:
        """Ignore an attribute update.

        Args:
            *args (Any): Attribute key and value.
        """

    def record_exception(self, *args: Any) -> None:
        """Ignore a recorded exception.

        Args:
            *args (Any): Exception payload.
        """

    def set_status(self, *args: Any) -> None:
        """Ignore a status update.

        Args:
            *args (Any): Status and optional error.
        """


class NullTracer:
    """No-op tracer used when tracing is disabled or cannot initialize."""

    session_id = ""
    run_id = ""
    tier = "balanced"

    def current_span(self) -> None:
        """Return no active span while tracing is disabled."""
        return

    def start_span(self, *args: Any, **kwargs: Any) -> NullSpan:
        """Return a no-op span without evaluating lazy attributes.

        Args:
            *args (Any): Ignored positional arguments.
            **kwargs (Any): Ignored keyword arguments.

        Returns:
            NullSpan: A reusable no-op span.
        """
        return NullSpan()


_ACTIVE_SPAN: ContextVar[Span | NullSpan | None] = ContextVar(
    "mergecraft_active_trace_span", default=None
)


def resolve_correlation_from_env() -> dict[str, Any]:
    """Resolve root-span correlation fields from GitHub Actions variables.

    Returns:
        dict[str, Any]: Correlation attributes, including keys whose values are absent.

    Examples:
        >>> isinstance(resolve_correlation_from_env(), dict)
        True
    """
    github_run_id = os.environ.get("GITHUB_RUN_ID")
    return {
        "run_id": os.environ.get("MERGECRAFT_RUN_ID") or github_run_id,
        "repo": os.environ.get("GITHUB_REPOSITORY"),
        "pr_number": _int_or_text(os.environ.get("GITHUB_PR_NUMBER")),
        "commit_sha": os.environ.get("GITHUB_SHA"),
        "workflow_run_id": github_run_id,
        "job_id": os.environ.get("GITHUB_JOB"),
    }


def _int_or_text(value: str | None) -> int | str | None:
    """Convert a decimal environment value to int while preserving other text.

    Args:
        value (str | None): Raw environment value.

    Returns:
        int | str | None: Parsed integer, original text, or None.

    Examples:
        >>> _int_or_text("42")
        42
    """
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return value


def resolve_session_id() -> str:
    """Resolve a stable session identifier or generate one.

    Returns:
        str: Session identifier for all spans in the current tracer.

    Examples:
        >>> bool(resolve_session_id())
        True
    """
    return (
        os.environ.get("MERGECRAFT_TRACE_SESSION_ID")
        or os.environ.get("GITHUB_RUN_ID")
        or uuid.uuid4().hex
    )


def get_tracer_from_settings(settings: RepoSettings) -> Tracer | NullTracer:
    """Build the enabled tracer for ``settings`` or return the null path.

    Args:
        settings (RepoSettings): Resolved repository settings.

    Returns:
        Tracer | NullTracer: Active tracer when enabled; otherwise a no-op tracer.

    Examples:
        >>> from mergecraft.config import RepoSettings
        >>> isinstance(get_tracer_from_settings(RepoSettings()), NullTracer)
        True
    """
    # Honor the env/CLI/YAML/default precedence (``MERGECRAFT_TRACING``,
    # ``--tracing``, ``.mergecraft/config.yaml``) rather than the YAML block
    # alone, so an operator's ``.env`` token + ``--tracing-to logfire`` drives
    # the live sink. The resolver falls back to ``os.environ`` and config
    # auto-discovery, keeping parity with the YAML-only path when no env/CLI
    # overrides are set.
    active_tracing = resolve_active_tracing(config=settings.tracing)
    if not active_tracing.enabled:
        return NullTracer()

    active = _ACTIVE_SPAN.get()
    if isinstance(active, Span):
        return active.tracer

    try:
        sink = claim_sink(active_tracing)
    except Exception as exc:
        logger.warning("trace sink initialization failed: {}", exc)
        return NullTracer()

    correlation = resolve_correlation_from_env()
    session_id = resolve_session_id()
    run_id = str(correlation.get("run_id") or session_id)
    tier = os.environ.get("MERGECRAFT_TRUST_TIER") or "balanced"
    return Tracer(sink=sink, session_id=session_id, run_id=run_id, tier=tier)


__all__ = [
    "NullSpan",
    "NullTracer",
    "Span",
    "Tracer",
    "get_tracer_from_settings",
    "resolve_correlation_from_env",
    "resolve_session_id",
]
