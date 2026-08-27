"""MCB-06 integrity gate through ``opencode._run`` (issue #540).

``tests/security/test_review_canary.py`` already proves ``verify_tree_unchanged``
raises on a mutated tree. That does not prove a review reaches the helper,
passes it the checkout that was hashed, or turns the raise into a failed
``AgentResult``. The wiring is where this has already gone wrong twice:

- Fail-open: ``_capture_integrity_baseline`` returning ``None`` short-circuits
  ``_apply_integrity_gate``. Helpers stay green while every review skips the
  check.
- Fail-closed-always (``0815b574``): baseline captured *before* mergeCraft
  wrote ``opencode.json`` into the evidence scratch. An in-checkout tmpdir
  then made every review fail on mergeCraft's own file.

These tests drive ``opencode._run`` against a stubbed agent (``_install`` is
the seam — the real binary is never invoked) and assert on the returned
``AgentResult``, not on a mock-call of ``verify_tree_unchanged``. A mock-call
would pass against a ``_run`` that calls the gate and discards the result.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import httpx
import pytest

from mergecraft.agents import opencode as oc
from mergecraft.agents.shared import AgentResult, AgentRunContext
from mergecraft.mcp.tool_state import init_tool_state
from tests.agents.conftest import make_agent_run_context

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

_INTEGRITY_ERROR = "checkout integrity failure"

# The three ``_apply_integrity_gate`` sites the issue pins: serve success,
# ``opencode run`` fallback, and the session-bootstrap error path.
_RUN_PATHS = ("serve_success", "serve_unavailable_fallback", "session_error")


class _FakeServeProc:
    """Exited-looking ``Popen`` so ``_ServerHandle.close`` only unregisters."""

    pid = 540_001

    def poll(self) -> int:
        return 0

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return 0

    def kill(self) -> None:
        return None


class _StubResponse:
    def __init__(self, *, status_code: int, body: object = None, text: str = "") -> None:
        self.status_code = status_code
        self._body = body
        self.text = text

    def json(self) -> object:
        return self._body


class _SessionClient:
    """``httpx.AsyncClient`` stand-in that answers ``POST /session`` only."""

    def __init__(self, response: _StubResponse, on_session: object) -> None:
        self._response = response
        self._on_session = on_session

    async def __aenter__(self) -> _SessionClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def post(self, url: str, **kwargs: object) -> _StubResponse:
        del kwargs
        if not url.endswith("/session"):
            msg = f"unrouted url: {url}"
            raise AssertionError(msg)
        if callable(self._on_session):
            self._on_session()
        return self._response


@pytest.fixture(autouse=True)
def _unset_evidence_env(monkeypatch: MonkeyPatch) -> None:
    """Reproduce the local/offline evidence resolution used by ``0815b574``.

    ``_evidence_dir`` falls back to ``<tmpdir>/evidence`` only when neither
    ``MERGECRAFT_EVIDENCE_DIR`` nor ``RUNNER_TEMP`` is set. CI runners export
    ``RUNNER_TEMP``; leaving it in place would hide the in-checkout scratch.
    """
    monkeypatch.delenv("MERGECRAFT_EVIDENCE_DIR", raising=False)
    monkeypatch.delenv("RUNNER_TEMP", raising=False)


def _harness(tmp_path: Path) -> tuple[AgentRunContext, Path]:
    """Checkout + in-repo scratch so ``opencode.json`` lands inside the hashed tree.

    ``tmpdir`` is a *subdirectory* of the checkout, not the checkout root.
    At the checkout root, ``hash_tree`` excludes ``evidence/``; putting the
    scratch there would make the ``0815b574`` regression unobservable — the
    config write would be hashed-out even if the baseline were captured first.
    """
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    tracked = checkout / "README.md"
    tracked.write_text("clean\n", encoding="utf-8")
    scratch = checkout / "run-scratch"
    scratch.mkdir()
    ctx = replace(
        make_agent_run_context(tmp_path, resolved_model=None),
        tmpdir=str(scratch),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(checkout)),
    )
    return ctx, tracked


def _assert_in_checkout_scratch(ctx: object, tracked: Path) -> None:
    """The evidence scratch must resolve *inside* the hashed checkout."""
    checkout = tracked.parent.resolve()
    evidence = oc._evidence_dir(ctx).resolve()  # type: ignore[arg-type]
    rel = evidence.relative_to(checkout).as_posix()
    assert rel != "evidence"
    assert not rel.startswith("evidence/")
    written = evidence / "opencode.json"
    assert written.is_file()
    assert written.resolve().is_relative_to(checkout)


def _maybe_mutate(tracked: Path, mutate: bool) -> None:
    if mutate:
        tracked.write_text("mutated by stub agent\n", encoding="utf-8")


def _stub_install(monkeypatch: MonkeyPatch) -> None:
    async def _install(_token: str | None = None) -> str:
        return "/usr/bin/opencode-stub"

    monkeypatch.setattr(oc, "_install", _install)
    monkeypatch.setattr(oc, "unregister_process_group", lambda _pid: None)
    monkeypatch.setattr(oc, "kill_process_group", lambda _pid: None)
    monkeypatch.setattr(oc, "instrument_httpx", lambda _client, tracer=None: None)


def _wire_run_path(
    monkeypatch: MonkeyPatch,
    *,
    run_path: str,
    tracked: Path,
    mutate: bool,
) -> None:
    """Steer ``_run`` onto one of the three integrity-gate call sites."""
    _stub_install(monkeypatch)

    def _mutate() -> None:
        _maybe_mutate(tracked, mutate)

    if run_path == "serve_unavailable_fallback":

        def _boom(**kwargs: object) -> object:
            del kwargs
            msg = "opencode serve did not print a listening URL"
            raise RuntimeError(msg)

        async def _fallback(*, cli: str, ctx: object, env: dict[str, str]) -> AgentResult:
            del cli, ctx, env
            _mutate()
            return AgentResult(success=True, output="cli fallback")

        monkeypatch.setattr(oc, "_boot_opencode_server", _boom)
        monkeypatch.setattr(oc, "_run_cli_fallback", _fallback)
        return

    handle = oc._ServerHandle(
        base_url="http://127.0.0.1:5400",
        proc=_FakeServeProc(),  # type: ignore[arg-type]
    )
    monkeypatch.setattr(oc, "_boot_opencode_server", lambda **kwargs: handle)

    if run_path == "session_error":
        response = _StubResponse(status_code=503, text="server busy")

        def _client(*args: object, **kwargs: object) -> _SessionClient:
            del args, kwargs
            return _SessionClient(response, _mutate)

        monkeypatch.setattr(httpx, "AsyncClient", _client)
        return

    if run_path != "serve_success":
        msg = f"unknown run path: {run_path}"
        raise AssertionError(msg)

    response = _StubResponse(status_code=200, body={"id": "sess-540"})

    def _client(*args: object, **kwargs: object) -> _SessionClient:
        del args, kwargs
        return _SessionClient(response, on_session=None)

    async def _prompt(*args: object, **kwargs: object) -> AgentResult:
        del args, kwargs
        _mutate()
        return AgentResult(success=True, output="serve ok")

    async def _no_retry(ctx: object, *, initial: AgentResult, resume: object) -> AgentResult:
        del ctx, resume
        return initial

    monkeypatch.setattr(httpx, "AsyncClient", _client)
    monkeypatch.setattr(oc, "_prompt_session", _prompt)
    monkeypatch.setattr(oc, "run_post_run_retry_loop", _no_retry)


@pytest.mark.parametrize("run_path", _RUN_PATHS)
@pytest.mark.parametrize("mutate", [True, False], ids=["mutated", "unmutated"])
async def test_integrity_gate_through_run(
    tmp_path: Path, monkeypatch: MonkeyPatch, run_path: str, mutate: bool
) -> None:
    """A mutated checkout fails closed; an unmutated one does not.

    Parametrised over the three ``_apply_integrity_gate`` call sites. The
    unmutated serve/fallback cases must return ``success=True`` so a harness
    that fails every review (wrong root, always-on gate) cannot go green.
    The session-error path is a failed bootstrap even without mutation — it
    must still *not* report an integrity failure when the tree is intact.
    """
    ctx, tracked = _harness(tmp_path)
    _wire_run_path(monkeypatch, run_path=run_path, tracked=tracked, mutate=mutate)

    result = await oc._run(ctx)

    _assert_in_checkout_scratch(ctx, tracked)
    if mutate:
        assert result.success is False
        assert result.error is not None
        assert _INTEGRITY_ERROR in result.error
        return
    if run_path == "session_error":
        assert result.success is False
        assert result.error == "failed to create opencode session: server busy"
        assert _INTEGRITY_ERROR not in result.error
        return
    assert result.success is True
    assert result.error is None


async def test_own_config_write_does_not_trip_gate_for_in_checkout_scratch(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """``0815b574``: mergeCraft writing ``opencode.json`` is not tampering.

    Baseline must be captured *after* that write. With ``MERGECRAFT_EVIDENCE_DIR``
    and ``RUNNER_TEMP`` unset, ``ctx.tmpdir`` sits inside the checkout so the
    evidence scratch is part of the hashed tree — the layout that used to
    fail every review.
    """
    ctx, tracked = _harness(tmp_path)
    _wire_run_path(
        monkeypatch, run_path="serve_unavailable_fallback", tracked=tracked, mutate=False
    )

    result = await oc._run(ctx)

    _assert_in_checkout_scratch(ctx, tracked)
    assert tracked.read_text(encoding="utf-8") == "clean\n"
    assert result.success is True
    assert result.error is None
    assert result.output == "cli fallback"
