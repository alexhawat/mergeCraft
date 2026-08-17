"""Review-wide correlation on every span — OB1.1 RED suite (part 1 of 3).

Wave plan: ``.ignorelocal/waves/04-observability-eval-wave-plan.md`` (PR OB1,
sub-wave OB1.1). Test-plan doc: ``docs/test-plans/04-observability-eval.md``.

Pins the OB1 contracts against the OB1.2 target API, which does not exist yet:

- ``mergecraft.tracing.review_context`` (new): frozen ``ReviewContext``, the
  ``bind_review_context`` context manager, ``resolve_review_id()`` (env-inherited
  ``MERGECRAFT_REVIEW_ID`` → ``uuid4``), ``correlation_key_for()``
  (deterministic ``sha256(repo|pr|head_sha)``, D3), and
  ``ReviewContext.attrs()`` which drops empty values rather than emitting nulls.
- ``mergecraft.tracing.tracer``: ``Tracer.baseline_attrs`` (D5, ``repr=False``),
  ``baseline_run_attrs()`` (O3), and the D4 close-time merge order
  (tracer baseline → review context → lazy ``attrs_source`` → explicit
  ``set_attribute``).

All imports of the once-new module are lazy (inside fixtures/tests), which kept
collection clean at RED-suite time. The nine contract tests carried non-strict
``xfail`` markers (``green after OB1.2``) while OB1.2 was unimplemented; the
markers were removed in the post-OB1.2 reconciliation (commit ``3891020`` made
all 14 XPASS), so every test here is now a clean real pass.

Acceptance (plan §OB1.1, post-reconciliation): 15 collected; 15 passed;
0 xfail/xpass.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

    from _pytest.monkeypatch import MonkeyPatch


@pytest.fixture
def tracer_and_sink() -> dict[str, Any]:
    """A real ``MemorySink`` wired to a ``Tracer`` with explicit correlation ids."""
    from mergecraft.tracing import MemorySink, Tracer

    sink = MemorySink()
    tracer = Tracer(
        sink=sink,
        session_id="session-ob1",
        run_id="run-ob1",
        trace_id="trace-ob1",
    )
    return {"sink": sink, "tracer": tracer}


def test_review_id_lands_on_every_span(
    tracer_and_sink: dict[str, Any],
    review_context_module: Any,
    review_context_factory: Callable[..., Any],
) -> None:
    """O1/D2 — every span kind closed under a bound review carries ``review.id``."""
    rc = review_context_module
    tracer = tracer_and_sink["tracer"]
    sink = tracer_and_sink["sink"]
    ctx = review_context_factory(review_id="review-ob1-every-span")

    kinds = (
        "mergecraft.run",
        "mergecraft.prep",
        "tool.call",
        "provider.call",
        "llm.call",
        "analyzer.run",
        "mergecraft.publish",
    )
    with rc.bind_review_context(ctx):
        for kind in kinds:
            with tracer.start_span(kind):
                pass

    assert len(sink.events) == len(kinds)
    for event in sink.events:
        assert event.attrs["review.id"] == "review-ob1-every-span", (
            f"{event.kind} span closed without the bound review.id"
        )
        assert event.attrs["review.correlation_key"] == ctx.correlation_key, (
            f"{event.kind} span closed without the bound review.correlation_key"
        )


def test_review_id_is_stable_within_a_review(
    review_context_module: Any,
    review_context_factory: Callable[..., Any],
) -> None:
    """O1 — spans from two runs of one review share a single ``review.id``."""
    from mergecraft.tracing import MemorySink, Tracer

    rc = review_context_module
    ctx = review_context_factory(review_id="review-ob1-stable")
    sink_a, sink_b = MemorySink(), MemorySink()
    tracer_a = Tracer(sink=sink_a, session_id="s-a", run_id="r-a", trace_id="trace-run-a")
    tracer_b = Tracer(sink=sink_b, session_id="s-b", run_id="r-b", trace_id="trace-run-b")

    with rc.bind_review_context(ctx):
        with tracer_a.start_span("mergecraft.run"):
            pass
        with tracer_b.start_span("mergecraft.run"):
            pass

    events = [*sink_a.events, *sink_b.events]
    assert len(events) == 2
    for event in events:
        assert event.attrs["review.id"] == "review-ob1-stable"


def test_trace_id_is_per_run_not_per_review(
    monkeypatch: MonkeyPatch,
    review_context_module: Any,
    review_context_factory: Callable[..., Any],
) -> None:
    """D2 — three agent runs of one review: ONE ``review.id``, THREE ``trace_id`` values."""
    from mergecraft.tracing import MemorySink, Tracer

    for var in ("MERGECRAFT_TRACE_ID", "MERGECRAFT_TRACE_SESSION_ID", "GITHUB_RUN_ID"):
        monkeypatch.delenv(var, raising=False)

    rc = review_context_module
    ctx = review_context_factory(review_id="review-ob1-three-runs")
    sinks = [MemorySink() for _ in range(3)]
    # No explicit trace_id and the env overrides cleared: each Tracer resolves
    # its own uuid4 fallback, modelling three separate agent-run processes.
    tracers = [Tracer(sink=sink, session_id="session", run_id="run") for sink in sinks]

    with rc.bind_review_context(ctx):
        for tracer in tracers:
            with tracer.start_span("mergecraft.run"):
                pass

    events = [event for sink in sinks for event in sink.events]
    assert len(events) == 3
    review_ids = {event.attrs["review.id"] for event in events}
    trace_ids = {event.trace_id for event in events}
    assert review_ids == {"review-ob1-three-runs"}, "one review must have exactly one review.id"
    assert len(trace_ids) == 3, "three agent runs of one review must keep three trace_ids"
    assert all(trace_ids), "no run may fall back to an empty trace_id"


def test_correlation_key_is_deterministic(review_context_module: Any) -> None:
    """D3 — same repo/pr/head_sha always yields sha256(repo|pr|head_sha)."""
    rc = review_context_module
    head_sha = "f" * 40
    expected = hashlib.sha256(f"octo/mergecraft|42|{head_sha}".encode()).hexdigest()

    first = rc.correlation_key_for(repo="octo/mergecraft", pr_number=42, head_sha=head_sha)
    second = rc.correlation_key_for(repo="octo/mergecraft", pr_number=42, head_sha=head_sha)

    assert first == expected
    assert second == expected


def test_correlation_key_differs_from_review_id_across_attempts(
    monkeypatch: MonkeyPatch,
    review_context_module: Any,
    review_context_factory: Callable[..., Any],
) -> None:
    """D3 — two attempts at one commit share the correlation key, never the review id."""
    rc = review_context_module
    monkeypatch.delenv("MERGECRAFT_REVIEW_ID", raising=False)

    key = rc.correlation_key_for(repo="octo/mergecraft", pr_number=42, head_sha="f" * 40)
    attempt_one = review_context_factory(
        review_id=rc.resolve_review_id(), correlation_key=key, attempt=1
    )
    attempt_two = review_context_factory(
        review_id=rc.resolve_review_id(), correlation_key=key, attempt=2
    )

    assert attempt_one.correlation_key == attempt_two.correlation_key == key
    assert attempt_one.review_id != attempt_two.review_id, (
        "two reviews of one commit are two reviews — review_id must not derive from the head SHA"
    )


def test_correlation_key_is_empty_without_repo_context(
    tracer_and_sink: dict[str, Any],
    review_context_module: Any,
    review_context_factory: Callable[..., Any],
) -> None:
    """A local patch review (no repo/pr/head) emits no misleading correlation constant."""
    rc = review_context_module
    tracer = tracer_and_sink["tracer"]
    sink = tracer_and_sink["sink"]

    assert rc.correlation_key_for(repo=None, pr_number=None, head_sha=None) == ""

    ctx = review_context_factory(
        review_id="review-ob1-local",
        correlation_key="",
        repo=None,
        pr_number=None,
        head_sha=None,
    )
    attrs = ctx.attrs()
    assert attrs["review.id"] == "review-ob1-local"
    assert "review.correlation_key" not in attrs, "attrs() drops empty values, never emits nulls"

    with rc.bind_review_context(ctx), tracer.start_span("mergecraft.run"):
        pass

    event_attrs = sink.events[0].attrs
    assert event_attrs["review.id"] == "review-ob1-local"
    assert "review.correlation_key" not in event_attrs


def test_context_bound_after_tracer_creation_still_reaches_spans(
    tracer_and_sink: dict[str, Any],
    review_context_module: Any,
    review_context_factory: Callable[..., Any],
) -> None:
    """D4 — the merge happens at ``Span.close()``, so a context bound after the
    tracer was built (and after the span was opened) still reaches the span."""
    rc = review_context_module
    tracer = tracer_and_sink["tracer"]
    sink = tracer_and_sink["sink"]

    span = tracer.start_span("mergecraft.run")
    span.__enter__()
    # The review context is bound only now — after tracer construction AND
    # after span creation — and the span closes while it is still bound.
    with rc.bind_review_context(review_context_factory(review_id="review-ob1-late-bind")):
        span.close()

    assert len(sink.events) == 1
    assert sink.events[0].attrs["review.id"] == "review-ob1-late-bind"


def test_precedence_explicit_attr_beats_review_context(
    tracer_and_sink: dict[str, Any],
    review_context_module: Any,
    review_context_factory: Callable[..., Any],
) -> None:
    """D4 — precedence: baseline → review context → lazy attrs_source → explicit set_attribute."""
    rc = review_context_module
    tracer = tracer_and_sink["tracer"]
    sink = tracer_and_sink["sink"]

    with (
        rc.bind_review_context(review_context_factory(review_id="review-from-context")),
        tracer.start_span("mergecraft.run") as span,
    ):
        span.set_attribute("review.id", "review-explicit")

    assert sink.events[0].attrs["review.id"] == "review-explicit"


def test_baseline_attrs_carry_version_and_vcs_fields(
    monkeypatch: MonkeyPatch,
    review_context_factory: Callable[..., Any],
) -> None:
    """O3 — baseline attrs make a span self-describing: build version + VCS/CI fields.

    Amended post-review (PR #241): the baseline deliberately does NOT read
    ``MERGECRAFT_TRUST_TIER`` — that env var is CLI-only, so a baseline value
    would silently omit the tier on Action runs. The honestly derived tier
    reaches the span from the bound ``ReviewContext`` instead (asserted
    below), which mirrors it as both ``review.trust_tier`` and
    ``mergecraft.trust_tier``.
    """
    monkeypatch.setenv("GITHUB_REPOSITORY", "octo/mergecraft")
    monkeypatch.setenv("GITHUB_PR_NUMBER", "42")
    monkeypatch.setenv("GITHUB_SHA", "f" * 40)
    monkeypatch.setenv("GITHUB_RUN_ID", "424242")
    monkeypatch.setenv("GITHUB_JOB", "review")
    monkeypatch.delenv("MERGECRAFT_RUN_ID", raising=False)
    monkeypatch.setenv("MERGECRAFT_TRUST_TIER", "trusted")

    import mergecraft
    from mergecraft.tracing import MemorySink, Tracer
    from mergecraft.tracing.tracer import baseline_run_attrs

    baseline = baseline_run_attrs()
    assert baseline["mergecraft.version"] == mergecraft.__version__
    assert baseline["mergecraft.run_id"] == "424242"
    assert "mergecraft.trust_tier" not in baseline  # env guess removed; see docstring
    assert baseline["vcs.repository.name"] == "octo/mergecraft"
    assert baseline["vcs.change.id"] == 42
    assert baseline["vcs.revision"] == "f" * 40
    assert baseline["ci.workflow_run_id"] == "424242"
    assert baseline["ci.job_id"] == "review"

    sink = MemorySink()
    tracer = Tracer(
        sink=sink,
        session_id="session",
        run_id="run",
        trace_id="trace-ob1",
        baseline_attrs=baseline,
    )
    from mergecraft.tracing.review_context import bind_review_context

    ctx = review_context_factory(review_id="r-trust", trust_tier="untrusted")
    with bind_review_context(ctx), tracer.start_span("mergecraft.run"):
        pass

    event_attrs = sink.events[0].attrs
    assert event_attrs["mergecraft.version"] == mergecraft.__version__
    assert event_attrs["vcs.repository.name"] == "octo/mergecraft"
    # The derived tier lands via the D4 review-context merge, not the env var
    # (which says "trusted" here — proof the baseline no longer reads it).
    assert event_attrs["review.trust_tier"] == "untrusted"
    assert event_attrs["mergecraft.trust_tier"] == "untrusted"


def test_tracer_repr_is_unchanged() -> None:
    """D5 regression pin — ``baseline_attrs`` joins ``Tracer`` with ``repr=False``.

    The ``Tracer`` dataclass repr is asserted in a module docstring example;
    a plain ``baseline_attrs`` field would break it. This test passes today
    (no such field) and must keep passing after OB1.2 (field present but
    ``repr=False``). Not xfailed — it is the one green pin of the OB1.1 suite.
    """
    from mergecraft.tracing import MemorySink, Tracer

    tracer = Tracer(sink=MemorySink(), session_id="session", run_id="run", trace_id="trace-ob1")
    text = repr(tracer)

    assert text.startswith("Tracer(sink=")
    assert "session_id='session'" in text
    assert "run_id='run'" in text
    assert "trace_id='trace-ob1'" in text
    assert "baseline_attrs" not in text
