"""No-output / idle watchdog for agent drivers (slice 6).

The wall-clock cap in ``main.py`` answers "how long has this run taken?". It
cannot answer "is this run still doing anything?". A provider that accepts the
request and then emits nothing for twenty minutes looks exactly like a slow
review until the attempt budget expires, and the failure it produces names the
clock rather than the stall (``agent run timed out after 25m``).

This module adds the second signal. A driver starts one watchdog after spawning
its CLI; every parsed stream event calls :meth:`IdleWatchdog.touch`. When no
event arrives for ``interval_s`` the monitor thread kills the process group so
the blocking stream read returns, and the driver reports a diagnostic naming:

* the idle span and the event count,
* whether the model produced any output at all,
* the last provider error the stream saw, if any,
* the stderr tail captured by the existing drain.

The diagnostic is advisory: the driver returns ``success=False`` with
``metadata={"idle_timeout": True, ...}``, which the existing outcome mapping
treats as an environment/provider fault (``infra_error``), not a failed review.
Nothing here changes a gate, a trust tier, or a verdict.

The same monitor thread enforces the per-attempt wall-clock cap
(``MERGECRAFT_AGENT_TIMEOUT``, passed as ``deadline_s``). The cap counts from
spawn, not from stdout EOF: a CLI that keeps streaming events (a tool loop,
heartbeats) is never idle, so only a deadline checked while the stream is still
open can bound it. A capped attempt reports ``metadata={"timeout": True, ...}``.

Module: mergecraft.agents.activity_watchdog
Depends: mergecraft.utils.process_group

Exports:
    AgentDiagnostic — What stalled, and the evidence for it.
    IdleWatchdog — Per-attempt activity monitor with a real-time check.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from mergecraft.agents._stream_consumer import StreamSpanAccumulator

DEFAULT_IDLE_TIMEOUT_S: Final[float] = 900.0
"""Fifteen minutes with no parsed event is a stall, not a slow review."""

WALL_CLOCK_TIMEOUT_KIND: Final[str] = "wall-clock cap"
"""``AgentDiagnostic.timeout_kind`` for an attempt killed at its wall-clock cap."""

WALL_CLOCK_INFRA_REASON: Final[str] = "agent_wall_clock_timeout"
"""``AgentResult.metadata[INFRA_REASON_KEY]`` of an attempt killed at its wall-clock cap."""

IDLE_TIMEOUT_KIND: Final[str] = "no-output watchdog"
"""``AgentDiagnostic.timeout_kind`` for an attempt killed by the idle watchdog."""

_MAX_STDERR_CHARS: Final[int] = 3000
_MIN_POLL_S: Final[float] = 0.05
_MAX_POLL_S: Final[float] = 5.0


@dataclass(frozen=True, slots=True)
class AgentDiagnostic:
    """One stalled attempt's diagnostic, rendered for the packet and check summary."""

    label: str
    event_count: int
    idle_seconds: float
    saw_model_output: bool
    last_provider_error: str | None = None
    stderr_tail: tuple[str, ...] = field(default_factory=tuple)
    # The last stream event before the silence, so the report can say what the
    # run was doing when it went quiet (#1138).
    last_event_type: str | None = None
    last_event_at: str | None = None
    # A provider error that arrived only after the watchdog killed the attempt.
    # Killing the process closes its transport, so this is an effect of the
    # kill and is never offered as the cause.
    error_after_kill: str | None = None
    # Which limit killed the attempt: the idle watchdog or the wall-clock cap.
    timeout_kind: str = IDLE_TIMEOUT_KIND
    # Wall-clock cap only: how long the attempt ran, and the cap it hit.
    elapsed_seconds: float | None = None
    cap_seconds: float | None = None

    def __post_init__(self) -> None:
        """Redact provider/stderr text before it can reach a packet or record.

        The diagnostic is published in the run record and the check summary.
        Provider errors routinely echo the credential that caused them
        (``Incorrect API key provided: sk-...``), and stderr is child-process
        output, so both cross the same redaction boundary as tool errors.
        """
        from mergecraft.analyzers.redact import redact_secrets

        if self.last_provider_error:
            object.__setattr__(
                self, "last_provider_error", redact_secrets(self.last_provider_error)
            )
        if self.error_after_kill:
            object.__setattr__(self, "error_after_kill", redact_secrets(self.error_after_kill))
        object.__setattr__(
            self,
            "stderr_tail",
            tuple(redact_secrets(line) for line in self.stderr_tail),
        )

    @property
    def wall_clock(self) -> bool:
        """Return whether the wall-clock cap, not the idle watchdog, killed the attempt."""
        return self.timeout_kind == WALL_CLOCK_TIMEOUT_KIND

    def render(self, *, timeout_kind: str | None = None) -> str:
        """Render the operator-facing one-block diagnosis."""
        kind = timeout_kind or self.timeout_kind
        capped = kind == WALL_CLOCK_TIMEOUT_KIND
        cause = f" — likely cause: `{self.last_provider_error}`" if self.last_provider_error else ""
        if capped:
            elapsed = self.elapsed_seconds if self.elapsed_seconds is not None else 0.0
            cap = f" of {self.cap_seconds:.0f}s" if self.cap_seconds is not None else ""
            lines = [
                f"{self.label} timed out: it hit the wall-clock cap{cap}{cause}",
                (
                    f"The attempt ran for {elapsed:.0f}s and was killed at "
                    f"MERGECRAFT_AGENT_TIMEOUT ({self.event_count} event(s) processed)."
                ),
            ]
        else:
            lines = [
                f"{self.label} stalled{cause}",
                (
                    f"No model event arrived for {self.idle_seconds:.0f}s "
                    f"({self.event_count} event(s) processed before the stall)."
                ),
            ]
        if self.last_event_type:
            what = "the kill" if capped else "the silence"
            when = f" at {self.last_event_at}" if self.last_event_at else ""
            lines.append(f"Last event before {what}: `{self.last_event_type}`{when}.")
        if not self.last_provider_error and not capped:
            lines.append("No provider error was seen before the stall, so the cause is not known.")
        if self.error_after_kill:
            lines.append(
                "A provider error arrived after the kill and is an effect of it, not the "
                f"cause: `{self.error_after_kill}`"
            )
        if not self.saw_model_output and not self.last_provider_error and not capped:
            lines.append(
                "The model produced no output at all — the request was sent but nothing "
                "came back. This is usually transient; re-running often succeeds."
            )
        if self.stderr_tail:
            lines.append("recent stderr tail:")
            lines.extend(f"  {line}" for line in self.stderr_tail)
        return "\n".join(lines)

    def as_metadata(self) -> dict[str, Any]:
        """Return the diagnostic as JSON-safe metadata for ``AgentResult``."""
        kind_keys: dict[str, Any]
        if self.wall_clock:
            kind_keys = {
                "timeout": True,
                "wall_clock_timeout": True,
                # ``shared.INFRA_REASON_KEY`` (not imported: ``shared`` imports
                # this module). The clock, not the review, ended the attempt, so
                # the run reads as ``infra_error`` with this reason, as an idle
                # stall does, and never as a review that ``failed``.
                "infra_reason": WALL_CLOCK_INFRA_REASON,
                "elapsed_seconds": (
                    round(self.elapsed_seconds, 3) if self.elapsed_seconds is not None else None
                ),
                "cap_seconds": self.cap_seconds,
            }
        else:
            kind_keys = {"idle_timeout": True}
        return {
            # A stall or a capped attempt is the provider's or the transport's
            # fault, not the review's: the next chain entry may succeed (#1328).
            "retryable": True,
            **kind_keys,
            "idle_seconds": round(self.idle_seconds, 3),
            "event_count": self.event_count,
            "saw_model_output": self.saw_model_output,
            "last_provider_error": self.last_provider_error,
            "last_event_type": self.last_event_type,
            "last_event_at": self.last_event_at,
            "error_after_kill": self.error_after_kill,
            "stderr_tail": list(self.stderr_tail),
            "diagnostic": self.render(),
        }


class IdleWatchdog:
    """Per-attempt activity monitor.

    ``clock`` and ``kill`` are injectable so the watchdog is testable
    without a real process or a real 15-minute wait. Production drivers use the
    :meth:`start` helper, which runs :meth:`check` on a daemon thread and kills
    the process group when it returns true.
    """

    def __init__(
        self,
        *,
        label: str,
        interval_s: float = DEFAULT_IDLE_TIMEOUT_S,
        accumulator: StreamSpanAccumulator | None = None,
        stderr_text: Callable[[], str] | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        kill: Callable[[int | None], None] | None = None,
        process: Any | None = None,
        deadline_s: float | None = None,
    ) -> None:
        self.label = label
        self.interval_s = max(float(interval_s), 0.0)
        # Wall-clock cap counted from construction (spawn); ``None``/``<= 0`` is no cap.
        self.deadline_s = float(deadline_s) if deadline_s and deadline_s > 0 else None
        self._accumulator = accumulator
        self._stderr_text = stderr_text
        self._clock = clock
        self._wall_clock = wall_clock
        self._kill = kill
        self._process = process
        self._last_activity = clock()
        self._started = self._last_activity
        self._deadline_hit = False
        self._stalled_elapsed_seconds: float | None = None
        self._event_count = 0
        self._saw_model_output = False
        self._last_event_type: str | None = None
        self._last_event_at: str | None = None
        self._stalled = False
        # The provider error on the stream *when the stall was declared*. Anything
        # the accumulator records after that point followed the kill (#1138).
        self._error_at_stall: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def stalled(self) -> bool:
        """Return whether the watchdog has declared this attempt stalled."""
        return self._stalled

    @property
    def deadline_hit(self) -> bool:
        """Return whether the wall-clock cap (not idleness) ended this attempt."""
        return self._deadline_hit

    @property
    def event_count(self) -> int:
        """Return the number of stream events observed."""
        return self._event_count

    def touch(self, *, model_output: bool = False, event_type: str | None = None) -> None:
        """Mark activity. ``model_output`` distinguishes a real model turn.

        ``event_type`` is the stream event's ``type``; the diagnostic names the
        last one so a stall report says what the run was doing when it went quiet.
        """
        self._last_activity = self._clock()
        self._event_count += 1
        if model_output:
            self._saw_model_output = True
        # Events emitted during shutdown must not replace the pre-stall record.
        if event_type and not self._stalled:
            self._last_event_type = event_type
            self._last_event_at = _iso_utc(self._wall_clock())

    def idle_seconds(self, *, now: float | None = None) -> float:
        """Return seconds since the last activity marker."""
        return max((now if now is not None else self._clock()) - self._last_activity, 0.0)

    def elapsed_seconds(self, *, now: float | None = None) -> float:
        """Return seconds since the attempt started (the watchdog was built at spawn)."""
        return max((now if now is not None else self._clock()) - self._started, 0.0)

    def check(self, *, now: float | None = None) -> bool:
        """Return true when the attempt is idle past the interval or past its cap."""
        if self._stalled:
            return True
        current = now if now is not None else self._clock()
        if self.deadline_s is not None and self.elapsed_seconds(now=current) >= self.deadline_s:
            self._deadline_hit = True
            self._mark_stalled(current)
            logger.warning(
                "agent wall-clock cap: {} ran {:.0f}s (cap {:.0f}s, {} event(s)); killing attempt",
                self.label,
                self.elapsed_seconds(now=current),
                self.deadline_s,
                self._event_count,
            )
            return True
        if self.interval_s <= 0:
            return False
        if self.idle_seconds(now=current) < self.interval_s:
            return False
        self._mark_stalled(current)
        logger.warning(
            "agent idle watchdog: {} produced no event for {:.0f}s ({} event(s)); killing attempt",
            self.label,
            self._stalled_idle_seconds,
            self._event_count,
        )
        return True

    def _mark_stalled(self, now: float) -> None:
        self._stalled = True
        self._stalled_idle_seconds = self.idle_seconds(now=now)
        self._stalled_elapsed_seconds = self.elapsed_seconds(now=now)
        # Snapshot before the monitor kills the process: the kill closes the
        # transport, and the error that reports it must not become the cause.
        self._error_at_stall = self._current_stream_error()

    def diagnostic(self) -> AgentDiagnostic:
        """Build the diagnostic for the current (stalled) attempt."""
        from mergecraft.analyzers.redact import redact_secrets

        # Redact the *full* tail before truncating. Truncating first can cut a
        # credential in half, and the partial token no longer matches the
        # redactor's patterns — the same order main.py uses for setup stderr.
        raw_stderr = redact_secrets(self._stderr_text() if self._stderr_text else "")
        stderr_lines = tuple(line for line in raw_stderr.splitlines() if line)[-20:]
        joined = "\n".join(stderr_lines)
        if len(joined) > _MAX_STDERR_CHARS:
            joined = f"... (older lines truncated)\n{joined[-_MAX_STDERR_CHARS:]}"
        current_error = self._current_stream_error()
        # Once stalled, only an error seen *before* the kill may be the cause.
        before_kill = self._error_at_stall if self._stalled else current_error
        after_kill = current_error if self._stalled and current_error != before_kill else None
        return AgentDiagnostic(
            label=self.label,
            event_count=self._event_count,
            idle_seconds=getattr(self, "_stalled_idle_seconds", self.idle_seconds()),
            saw_model_output=self._saw_model_output,
            last_provider_error=before_kill,
            stderr_tail=tuple(joined.splitlines()) if joined else (),
            last_event_type=self._last_event_type,
            last_event_at=self._last_event_at,
            error_after_kill=after_kill,
            timeout_kind=WALL_CLOCK_TIMEOUT_KIND if self._deadline_hit else IDLE_TIMEOUT_KIND,
            elapsed_seconds=self._stalled_elapsed_seconds if self._deadline_hit else None,
            cap_seconds=self.deadline_s if self._deadline_hit else None,
        )

    def _current_stream_error(self) -> str | None:
        return self._accumulator.stream_error if self._accumulator is not None else None

    def start(self) -> IdleWatchdog:
        """Start the monitor thread for a real attempt."""
        if (self.interval_s <= 0 and self.deadline_s is None) or self._thread is not None:
            return self
        spans = [self.interval_s / 2.0] if self.interval_s > 0 else []
        if self.deadline_s is not None:
            spans.append(self.deadline_s / 4.0)
        poll = max(_MIN_POLL_S, min(*spans, _MAX_POLL_S))
        self._thread = threading.Thread(
            target=self._monitor, args=(poll,), name=f"agent-idle-{self.label}", daemon=True
        )
        self._thread.start()
        return self

    def _monitor(self, poll: float) -> None:
        while not self._stop.wait(poll):
            if not self.check():
                continue
            self._stalled_idle_seconds = self.idle_seconds()
            if self._kill is not None:
                self._kill(getattr(self._process, "pid", None))
            return

    def stop(self) -> None:
        """Stop the monitor thread without changing the stall state."""
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)


def _iso_utc(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=UTC).isoformat(timespec="milliseconds")


def event_type_name(event: dict[str, Any]) -> str | None:
    """Return the stream event's ``type`` for the watchdog's last-event record."""
    event_type = str(event.get("type") or "").strip()
    return event_type or None


def event_has_model_output(event: dict[str, Any]) -> bool:
    """Return whether one stream event carries model-produced text.

    ``event_count`` cannot answer this: lifecycle/prompt-echo events arrive
    before the provider is contacted, so a live stream is never at zero when it
    stalls. This looks for the shapes the supported harnesses use for assistant
    text and treats everything else as transport activity.
    """
    event_type = str(event.get("type") or "").casefold()
    if any(marker in event_type for marker in ("message", "text", "content_block_delta")):
        return True
    for key in ("item", "part", "content_block"):
        nested = event.get(key)
        if isinstance(nested, dict):
            nested_type = str(nested.get("type") or "").casefold()
            if nested_type in {"message", "text", "assistant", "output_text"}:
                return True
            if isinstance(nested.get("text"), str) and nested["text"].strip():
                return True
    return False


def watchdog_for_process(
    process: Any,
    *,
    label: str,
    interval_s: float,
    accumulator: StreamSpanAccumulator | None = None,
    stderr_text: Callable[[], str] | None = None,
    deadline_s: float | None = None,
) -> IdleWatchdog:
    """Build and start the production watchdog for ``process``.

    ``deadline_s`` is the attempt's wall-clock cap counted from now (spawn);
    drivers pass ``MERGECRAFT_AGENT_TIMEOUT``. ``None`` disables the cap.
    """
    from mergecraft.utils.process_group import kill_process_group

    def _kill(pid: int | None) -> None:
        kill_process_group(pid if isinstance(pid, int) else None)

    return IdleWatchdog(
        label=label,
        interval_s=interval_s,
        accumulator=accumulator,
        stderr_text=stderr_text,
        kill=_kill,
        process=process,
        deadline_s=deadline_s,
    ).start()


__all__ = [
    "DEFAULT_IDLE_TIMEOUT_S",
    "IDLE_TIMEOUT_KIND",
    "WALL_CLOCK_INFRA_REASON",
    "WALL_CLOCK_TIMEOUT_KIND",
    "AgentDiagnostic",
    "IdleWatchdog",
    "event_has_model_output",
    "event_type_name",
    "watchdog_for_process",
]
