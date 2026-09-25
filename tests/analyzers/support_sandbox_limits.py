"""Shared seams for the sandbox drop-cap probe tests.

The privilege drop's ``RLIMIT_NPROC`` cap is no longer a raw ``/proc`` count: a
count is blind inside a PID namespace (the CI harness runs pytest under
``unshare --pid --mount-proc``), where it reads zero for a uid the kernel still
knows is busy in the parent namespace. The cap is instead derived by probing the
kernel's own answer — run the real credential-changing ``setpriv`` exec at a
candidate limit, step upward while it is refused, fail closed when the bound is
exhausted — and ``/proc`` stays only a starting hint.

These helpers drive that probe at its per-candidate seam (one credential-changing
exec), so a test can assert the stepping, the tight pair when the hint is
visible, and the fail-closed bound without depending on the probe's private loop.
Both a private and a public spelling of the seam are patched, so the tests do not
lock an underscore convention the implementation is free to choose; the
``ATTEMPT_SEAMS`` tuple is the contract the implementation must satisfy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

if TYPE_CHECKING:
    import pytest

# One credential-changing ``setpriv`` exec at a candidate limit; truthy when the
# drop landed at that limit.
ATTEMPT_SEAMS: tuple[str, ...] = (
    "drop_exec_succeeds_at_limit",
    "_drop_exec_succeeds_at_limit",
    "drop_exec_succeeds",
    "_drop_exec_succeeds",
    "drop_at_limit_succeeds",
    "_drop_at_limit_succeeds",
    "setpriv_drop_succeeds",
    "_setpriv_drop_succeeds",
    "setpriv_drop_succeeds_at_limit",
    "_setpriv_drop_succeeds_at_limit",
    "probe_drop_exec_succeeds",
    "_probe_drop_exec_succeeds",
    "credential_drop_succeeds_at_limit",
    "_credential_drop_succeeds_at_limit",
    "nproc_drop_succeeds",
    "_nproc_drop_succeeds",
)

# The bounded loop that turns the per-candidate seam into the derived limit.
PROBE_SEAMS: tuple[str, ...] = (
    "probe_process_limit_for_drop",
    "_probe_process_limit_for_drop",
    "probe_drop_process_limit",
    "_probe_drop_process_limit",
)

# A bounded probe must exhaust this many candidates at the very most — a probe
# that keeps going is the unbounded loop this suite exists to catch.
MAX_PROBE_CANDIDATES = 4096

# Hard stop for the fake itself, well above ``MAX_PROBE_CANDIDATES``, so a badly
# unbounded implementation fails the assertion instead of hanging the suite.
_SAFETY_MAX_ATTEMPTS = 100_000

_LIMIT_KEYS = ("limit", "candidate", "nproc", "process_limit", "value")


class DropTarget(NamedTuple):
    """The resolved ``(uid, gid)`` a drop lands on, indexable and attribute-readable."""

    uid: int
    gid: int


class ProbeAttempt:
    """A per-candidate probe seam that succeeds once the candidate reaches ``succeed_at``.

    ``succeed_at=None`` refuses every candidate, modelling a probe whose bound is
    exhausted. Every candidate is recorded, so a test can assert the upward,
    ``max_processes``-spaced stepping and that the probe ran in the parent, before
    the fork.
    """

    def __init__(self, *, succeed_at: int | None) -> None:
        self.succeed_at = succeed_at
        self.attempts: list[int] = []

    def __call__(self, *args: Any, **kwargs: Any) -> bool:
        limit = _candidate(args, kwargs)
        if limit is None:
            raise AssertionError(
                f"the drop-cap probe was called without a candidate limit: {args!r} {kwargs!r}"
            )
        self.attempts.append(limit)
        if len(self.attempts) > _SAFETY_MAX_ATTEMPTS:
            raise AssertionError("the drop-cap probe is unbounded")
        if self.succeed_at is None:
            return False
        return limit >= self.succeed_at


def install_probe(monkeypatch: pytest.MonkeyPatch, module: Any, attempt: ProbeAttempt) -> None:
    """Patch every per-candidate seam spelling with ``attempt``."""
    for name in ATTEMPT_SEAMS:
        monkeypatch.setattr(module, name, attempt, raising=False)


def refuse_probe(monkeypatch: pytest.MonkeyPatch, module: Any) -> None:
    """Make any probe spelling fail the test if it is reached."""

    def _unreachable(*args: Any, **kwargs: Any) -> bool:
        raise AssertionError("the drop-cap probe must not run")

    for name in ATTEMPT_SEAMS + PROBE_SEAMS:
        monkeypatch.setattr(module, name, _unreachable, raising=False)


def patch_drop_target(
    monkeypatch: pytest.MonkeyPatch, module: Any, *, uid: int | None, gid: int | None
) -> None:
    """Pin the drop-target resolution for ``module``, however it is exposed.

    Patches the uid/gid siblings and the record spelling, so the test does not
    depend on which shape the implementation chose. A no-drop target resolves to
    ``None`` through every spelling.
    """

    record = None if uid is None else DropTarget(uid, gid if gid is not None else 0)
    for name in ("resolve_drop_target_uid",):
        monkeypatch.setattr(module, name, lambda: uid, raising=False)
    for name in ("resolve_drop_target_gid",):
        monkeypatch.setattr(module, name, lambda: gid, raising=False)
    for name in ("resolve_drop_target",):
        monkeypatch.setattr(module, name, lambda: record, raising=False)


def resolve_uid(module: Any) -> int | None:
    """Read the resolved drop uid through whichever resolver shape exists."""
    uid_fn = getattr(module, "resolve_drop_target_uid", None)
    if callable(uid_fn):
        return uid_fn()  # type: ignore[no-any-return]
    raise AssertionError("the module exposes no resolve_drop_target_uid()")


def resolve_gid(module: Any) -> int | None:
    """Read the resolved drop gid, preferring the sibling, falling back to a record."""
    gid_fn = getattr(module, "resolve_drop_target_gid", None)
    if callable(gid_fn):
        return gid_fn()  # type: ignore[no-any-return]
    record_fn = getattr(module, "resolve_drop_target", None)
    if callable(record_fn):
        record = record_fn()
        if record is None:
            return None
        if isinstance(record, tuple):
            return int(record[1])
        return int(record.gid)
    raise AssertionError(
        "the module exposes neither resolve_drop_target_gid() nor resolve_drop_target()"
    )


def _candidate(args: tuple[Any, ...], kwargs: dict[str, Any]) -> int | None:
    for key in _LIMIT_KEYS:
        value = kwargs.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    for value in args:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None
