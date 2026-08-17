"""Best-effort span lifecycle for mergeCraft tracing.

Module: mergecraft.tracing.tracer
Depends: mergecraft.tracing.{event,sinks}, loguru

|Exports:
    Classes:
        Tracer — Creates and emits real spans to a configured sink.
        Span — Context-managed trace span.
        NullTracer — Disabled tracing implementation.
        NullSpan — Disabled span implementation.
    Functions:
        baseline_run_attrs — Self-describing run attrs (version, VCS, CI) (O3).
        resolve_correlation_from_env — Read GitHub correlation fields from the environment.
        resolve_session_id — Resolve or generate the trace session identifier.
        resolve_trace_id — Resolve or generate the per-run trace identifier.
        get_tracer_from_settings — Build a real or null tracer from repo settings.
"""

from __future__ import annotations

import contextlib
import os
import time
import uuid
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Iterator

from loguru import logger

from mergecraft.tracing.event import TraceEvent
from mergecraft.tracing.resolve import resolve_active_tracing
from mergecraft.tracing.review_context import current_review_context
from mergecraft.tracing.sinks import claim_sink

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

    from mergecraft.config.settings import RepoSettings


# G-F10 / #56 D6 — a guard, not a budget. A large review emits on the order
# of hundreds of spans (one ``analyzer.run`` per analyzer, one ``tool.call``
# per tool invocation, one ``llm.call`` + ``provider.call`` per turn); 10k is
# ~20x the realistic ceiling, so this only fires on a genuine runaway. See
# ``docs/TRACING.md``'s Limits section.
MAX_SPANS_PER_RUN: Final[int] = 10_000


@dataclass(slots=True)
class Tracer:
    """Create spans and route completed events to one configured sink."""

    sink: object
    session_id: str
    run_id: str
    tier: str = "balanced"
    trace_id: str = ""
    # D5 — ``repr=False``: the dataclass repr is pinned by the module
    # docstring example and by tests, so the baseline attrs must not join it.
    baseline_attrs: dict[str, Any] = field(default_factory=dict, repr=False)
    _span_count: int = 0
    _cap_warned: bool = False

    def __post_init__(self) -> None:
        """Resolve ``trace_id`` from env when the caller did not pass one.

        Tracers constructed without an explicit ``trace_id`` (the common
        path — ``Tracer(sink=..., session_id=..., run_id=...)``) share the
        same per-run identifier so every span in one run lands under one
        Logfire trace. The resolver keeps the T3 precedence (D7 / T3.2):
        ``MERGECRAFT_TRACE_ID`` → ``MERGECRAFT_TRACE_SESSION_ID`` →
        ``GITHUB_RUN_ID`` → ``uuid.uuid4().hex``. An explicit empty
        ``trace_id`` from a caller who wants the no-op fallback is
        preserved so the disabled path (``NullTracer``) keeps its
        ``trace_id = ""`` contract.
        """
        if not self.trace_id:
            self.trace_id = resolve_trace_id()

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

        Past :data:`MAX_SPANS_PER_RUN`, the returned ``Span`` is marked
        suppressed: it still enters/exits/chains normally (so callers that
        assume a plain ``Span`` — the ``http.py`` / ``provider_llm_pair``
        call sites — keep working unmodified), but ``close()`` skips both
        the ``attrs_source`` evaluation and the sink write, so the
        configured sink never receives more than the cap's worth of events
        (G-F10 / #56 D6 — a guard, not a budget; hitting it must never fail
        the run). The transition is logged exactly once at ``warning``, not
        once per subsequent call.

        Args:
            kind (str): Canonical span kind.
            parent_span_id (str | None, optional): Explicit parent span identifier.
                Defaults to the active span when it belongs to this tracer.
            attrs_source (Callable[[], dict[str, Any]] | None, optional): Lazy attribute
                producer evaluated only when the span closes. Defaults to None.

        Returns:
            Span: A context-managed span ready to enter. Suppressed (emits
            nothing on close) once :data:`MAX_SPANS_PER_RUN` has been reached.

        Examples:
            >>> tracer = Tracer(sink=object(), session_id="session", run_id="run")
            >>> tracer.start_span("mergecraft.run").kind
            'mergecraft.run'
        """
        if self._span_count >= MAX_SPANS_PER_RUN:
            if not self._cap_warned:
                logger.warning(
                    "trace span cap reached: {} spans emitted this run, further spans dropped",
                    MAX_SPANS_PER_RUN,
                )
                self._cap_warned = True
            return Span(
                tracer=self,
                kind=kind,
                parent_span_id=parent_span_id,
                span_id=uuid.uuid4().hex,
                session_id=self.session_id,
                trace_id=self.trace_id,
                turn_id=uuid.uuid4().hex,
                tier=self.tier,
                _suppressed=True,
            )
        self._span_count += 1

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
            trace_id=self.trace_id,
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
            <bound method Tracer._write of Tracer(sink=<object object at ...>, session_id='session', run_id='run', trace_id='', tier='balanced')>
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
    trace_id: str = ""
    status: str = "ok"
    error: str | None = None
    _attrs_source: Callable[[], dict[str, Any]] | None = None
    ts_start_ns: int = 0
    ts_end_ns: int = 0
    _attrs: dict[str, Any] = field(default_factory=dict)
    _exc: BaseException | None = None
    _context_token: Token[Span | NullSpan | None] | None = None
    _closed: bool = False
    _suppressed: bool = False

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
        # W5 / L2 — ``Span.close`` is the single source of truth for
        # emitting the TraceEvent and resetting the active ContextVar.
        # ``__exit__`` delegates to it so the manually-built span path
        # (which calls ``close`` without an ``__enter__``) and the
        # ``with`` block path converge on the same emit + reset discipline.
        self.close()

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

    def close(self) -> None:
        """End the span: stamp end time + emit the TraceEvent + reset the active ContextVar.

        Callers that build a span outside a ``with`` block (the verb sub-event
        emission, the ``provider_llm_pair`` helper, the HTTP wrapper close
        sites) use this instead of poking ``ts_end_ns`` and ``__exit__``
        directly. The active-context reset mirrors ``__exit__`` so a span
        closed manually still pops its ContextVar frame.

        Re-calling ``close()`` is a no-op — the dedicated ``_closed`` flag
        tracks the close path independently of ``_context_token`` so the
        manually-built span case (no ``__enter__``; ``_context_token`` is
        still ``None`` on the first ``close``) emits its TraceEvent exactly
        once. W5 / L2 — the prior implementation conflated the never-
        entered and already-closed cases by gating on ``_context_token is
        None`` alone, which silently dropped manually-built spans; the flag
        keeps the contract that ``close()`` is idempotent and emits once.

        G-F10 / #56 D6 — a span opened past :data:`MAX_SPANS_PER_RUN` is
        constructed with ``_suppressed=True``. It still pops its active-span
        frame like any other span (so parent/child bookkeeping stays sound),
        but skips ``attrs_source`` evaluation and the sink write entirely,
        mirroring ``NullSpan``'s true no-op contract for the disabled path.
        """
        if self._closed:
            return
        self.ts_end_ns = time.time_ns()

        if self._suppressed:
            if self._context_token is not None:
                _ACTIVE_SPAN.reset(self._context_token)
                self._context_token = None
            self._closed = True
            return

        # D4 — review attrs merge here, at close time (not at creation), so a
        # ReviewContext bound after the tracer was built still reaches open
        # spans. Precedence: tracer baseline → review context → lazy
        # ``attrs_source`` → explicit ``set_attribute``.
        attrs: dict[str, Any] = dict(self.tracer.baseline_attrs)
        try:
            review_ctx = current_review_context()
            if review_ctx is not None:
                attrs.update(review_ctx.attrs())
        except Exception as review_exc:
            logger.warning(
                "trace span {} review-context attributes failed: {}", self.kind, review_exc
            )
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
                trace_id=self.trace_id,
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
        self._closed = True


class NullSpan:
    """No-op context manager used while tracing is disabled."""

    span_id = ""
    parent_span_id: str | None = None
    status = "ok"
    trace_id = ""

    def __enter__(self) -> NullSpan:
        """Return this no-op span."""
        return self

    def __exit__(self, *args: Any) -> None:
        """Ignore context-manager exit state.

        Args:
            *args (Any): Context-manager exception state.
        """

    def close(self) -> None:
        """No-op close (W4 / M6 — mirrors :meth:`Span.close`)."""

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
    trace_id = ""

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


def baseline_run_attrs() -> dict[str, Any]:
    """Self-describing run attributes for every span in the process (O3).

    Populates ``mergecraft.run_id`` / ``mergecraft.version`` /
    ``mergecraft.trust_tier`` plus the VCS/CI fields
    (``vcs.repository.name``, ``vcs.change.id``, ``vcs.revision``,
    ``ci.workflow_run_id``, ``ci.job_id``) from
    :func:`resolve_correlation_from_env` and the package version, so a trace
    can say which build and which change produced it. Absent values are
    dropped rather than emitted as nulls.

    Returns:
        dict[str, Any]: Baseline attributes (never empty — the version is
        always known).
    """
    from mergecraft import __version__

    correlation = resolve_correlation_from_env()
    attrs: dict[str, Any] = {"mergecraft.version": __version__}
    run_id = correlation.get("run_id")
    if run_id:
        attrs["mergecraft.run_id"] = run_id
    trust_tier = os.environ.get("MERGECRAFT_TRUST_TIER")
    if trust_tier:
        attrs["mergecraft.trust_tier"] = trust_tier
    repo = correlation.get("repo")
    if repo:
        attrs["vcs.repository.name"] = repo
    pr_number = correlation.get("pr_number")
    if pr_number is not None:
        attrs["vcs.change.id"] = pr_number
    commit_sha = correlation.get("commit_sha")
    if commit_sha:
        attrs["vcs.revision"] = commit_sha
    workflow_run_id = correlation.get("workflow_run_id")
    if workflow_run_id:
        attrs["ci.workflow_run_id"] = workflow_run_id
    job_id = correlation.get("job_id")
    if job_id:
        attrs["ci.job_id"] = job_id
    return attrs


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


@dataclass(slots=True)
class ProviderLLMPair:
    """Handle for the ``provider.call`` parent + ``llm.call`` child pair (W4 H1).

    Yielded by ``provider_llm_pair``. Both spans share a single ``parent_span_id``
    chain (parent → child); the consumer can attach per-event attrs to either
    span by calling ``set_attribute(...)`` directly. Close order is fixed:
    the context manager closes the inner ``llm.call`` span first, then the
    outer ``provider.call`` span, mirroring the LIFO discipline the driver
    event handlers were already defending against (#56 D6).
    """

    provider: Span
    llm: Span


def _open_provider_llm_pair(
    tracer: Tracer | NullTracer | None,
    *,
    model_id: str,
    family: str,
    provider_id: str,
    parent_span_id: str | None = None,
) -> ProviderLLMPair | None:
    """Open a ``ProviderLLMPair`` and enter both spans.

    Shared body for the ``provider_llm_pair`` context manager and the
    streaming driver event handlers (W5 / H1). Returns ``None`` when
    ``tracer`` is ``None`` / ``NullTracer`` so the disabled path is a
    single-line guard at every call site.

    W6 / L-1 — once ``provider_span.__enter__()`` runs, the provider span
    is the active frame on ``_ACTIVE_SPAN``. If the subsequent
    ``tracer.start_span(...)`` or ``llm_span.__enter__()`` raises, the
    public ``provider_llm_pair`` context manager's ``try/finally`` would
    call ``_close_provider_llm_pair`` and the leak is contained — but
    the streaming driver event handlers (claude / codex / gemini) call
    this helper directly, store the pair in their own bookkeeping dict,
    and rely on a matching terminal event to close it. Any raised
    exception between the two ``__enter__()`` calls would leave the
    provider span stuck on ``_ACTIVE_SPAN`` for the rest of the run.
    The local ``try/except`` here ensures the provider span is closed
    (and its active-span frame reset) before the exception propagates,
    regardless of which caller path is used.

    Args:
        tracer: The owning tracer. ``None`` / ``NullTracer`` is a no-op.
        model_id: Model identifier attached to both spans.
        family: Transport family (``"anthropic"`` / ``"chat_completions"`` /
            ``"responses_api"``); becomes ``provider.transport_family``.
        provider_id: Provider identifier; becomes ``provider.id``.
        parent_span_id: Optional explicit parent span id.

    Returns:
        ProviderLLMPair | None: The open pair, or ``None`` when disabled.
    """
    if tracer is None or isinstance(tracer, NullTracer):
        return None
    provider_span = tracer.start_span("provider.call", parent_span_id=parent_span_id)
    provider_span.set_attribute("provider.id", provider_id)
    provider_span.set_attribute("provider.transport_family", family)
    provider_span.set_attribute("model.id", model_id)
    provider_span.set_attribute("gen_ai.system", provider_id)
    provider_span.set_attribute("gen_ai.operation.name", "chat")
    provider_span.ts_start_ns = time.time_ns()
    provider_span.__enter__()
    try:
        llm_span = tracer.start_span("llm.call", parent_span_id=provider_span.span_id)
        llm_span.__enter__()
    except BaseException:
        # W6 / L-1 — the provider span is the active frame on
        # ``_ACTIVE_SPAN`` at this point. Close it so its context-token
        # frame is popped before the exception propagates to the caller;
        # otherwise the next ``tracer.start_span`` would treat the
        # provider span as its parent and chain a child onto a
        # never-closed span. The provider span's ``close()`` is
        # idempotent on its own (``_closed`` flag — W5 / L2) so a
        # second close from a caller-side ``finally`` is a no-op.
        provider_span.__exit__(None, None, None)
        raise
    return ProviderLLMPair(provider=provider_span, llm=llm_span)


def _close_provider_llm_pair(pair: ProviderLLMPair | None) -> None:
    """Close a ``ProviderLLMPair`` opened by ``_open_provider_llm_pair``.

    Closes the inner ``llm.call`` span first (LIFO) and the outer
    ``provider.call`` span after — matching the close discipline the driver
    event handlers were already defending against (#56 D6). ``None`` is a
    no-op so the disabled path is a single-line guard.

    Args:
        pair: The pair returned by ``_open_provider_llm_pair``. ``None``
            (disabled path) is accepted.
    """
    if pair is None:
        return
    pair.llm.close()
    pair.provider.close()


@contextlib.contextmanager
def provider_llm_pair(
    tracer: Tracer | NullTracer | None,
    *,
    model_id: str,
    family: str,
    provider_id: str,
    parent_span_id: str | None = None,
) -> Iterator[ProviderLLMPair | None]:
    """Open a ``provider.call`` + ``llm.call`` pair under one context manager.

    Unifies the open/close discipline that ``claude.py`` / ``codex.py`` /
    ``gemini.py`` were each re-implementing (W4 H1). The provider span
    carries ``provider.id`` / ``provider.transport_family`` / ``model.id`` /
    ``gen_ai.system`` / ``gen_ai.operation.name`` so Logfire groups every
    upstream API request under one row; the ``llm.call`` span becomes the
    child the model-aware attrs (``model.event``, ``gen_ai.usage.*``) attach
    to.

    On exit the inner ``llm.call`` span closes first (LIFO) and the outer
    ``provider.call`` span closes after — matching the close discipline the
    driver event handlers were already defending against (#56 D6).

    Args:
        tracer: The owning tracer. ``None`` / ``NullTracer`` yields ``None``;
            no spans open and no exceptions propagate. Callers can rely on
            a single ``with`` line without a separate disabled check.
        model_id: The model identifier attached to both spans (``model.id``
            attr; the provider span's ``model.id`` is the canonical source).
        family: Transport family string (``"anthropic"`` / ``"chat_completions"``
            / ``"responses_api"``); becomes ``provider.transport_family``.
        provider_id: Provider identifier (``"anthropic"`` / ``"openai_codex"``
            / ``"google_gemini"``); becomes ``provider.id``.
        parent_span_id: Optional explicit parent span id. Defaults to the
            active span when it belongs to ``tracer``.

    Yields:
        ProviderLLMPair | None: The open pair of spans, or ``None`` when
        ``tracer`` is ``None`` / ``NullTracer``.

    Examples:
        >>> from mergecraft.tracing import MemorySink, Tracer
        >>> sink = MemorySink()
        >>> tracer = Tracer(sink=sink, session_id="s", run_id="r")
        >>> with provider_llm_pair(
        ...     tracer, model_id="claude-sonnet-4", family="anthropic",
        ...     provider_id="anthropic",
        ... ) as pair:
        ...     if pair is not None:
        ...         pair.llm.set_attribute("model.event", "message_start")
    """
    pair = _open_provider_llm_pair(
        tracer,
        model_id=model_id,
        family=family,
        provider_id=provider_id,
        parent_span_id=parent_span_id,
    )
    try:
        yield pair
    finally:
        _close_provider_llm_pair(pair)


def active_span_for(tracer: Tracer | NullTracer | None) -> Span | None:
    """Return the currently active mergeCraft ``Span`` owned by ``tracer``.

    Helper for the three sites that previously re-implemented this lookup:
    the httpx sync/async ``_wrap_*_send`` active-span resolver and the
    stream consumer's ``_resolve_active_span_for_otel_bridge``. Returns
    ``None`` when no span is active, when the active span belongs to a
    different tracer (the W5 W6 W3 multi-tracer tests catch this case),
    when the active value is a ``NullSpan`` (tracing disabled), or when
    ``tracer`` itself is ``None`` / ``NullTracer``.

    Args:
        tracer: The tracer that should own the active span. ``NullTracer``
            and ``None`` are accepted and always return ``None``.

    Returns:
        Span | None: The active span when it belongs to ``tracer``; ``None`` otherwise.
    """
    if tracer is None:
        return None
    if isinstance(tracer, NullTracer):
        return None
    active = _ACTIVE_SPAN.get()
    if isinstance(active, Span) and getattr(active, "tracer", None) is tracer:
        return active
    return None


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


def resolve_trace_id() -> str:
    """Resolve the per-run trace identifier (Logfire / OTel ``trace_id``).

    One ``trace_id`` is shared by every span emitted by a single
    ``mergecraft diff-review`` run; Logfire (and any OTel backend) groups
    those spans under one trace. The precedence mirrors the existing
    session-id resolver (D7 / T3.2):

    1. ``MERGECRAFT_TRACE_ID`` — explicit per-run override.
    2. ``MERGECRAFT_TRACE_SESSION_ID`` — alias preserving the
       pre-#137 contract so existing pipelines keep working.
    3. ``GITHUB_RUN_ID`` — the Actions run id, monotonic and unique.
    4. ``uuid.uuid4().hex`` — local fallback when no env vars are set.

    Returns:
        str: 32-hex (uuid4) trace identifier, or the resolved env value.

    Examples:
        >>> bool(resolve_trace_id())
        True
    """
    return (
        os.environ.get("MERGECRAFT_TRACE_ID")
        or os.environ.get("MERGECRAFT_TRACE_SESSION_ID")
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
    trace_id = resolve_trace_id()
    tier = os.environ.get("MERGECRAFT_TRUST_TIER") or "balanced"
    return Tracer(
        sink=sink,
        session_id=session_id,
        run_id=run_id,
        tier=tier,
        trace_id=trace_id,
        baseline_attrs=baseline_run_attrs(),
    )


__all__ = [
    "NullSpan",
    "NullTracer",
    "Span",
    "Tracer",
    "active_span_for",
    "baseline_run_attrs",
    "get_tracer_from_settings",
    "provider_llm_pair",
    "resolve_correlation_from_env",
    "resolve_session_id",
    "resolve_trace_id",
]
