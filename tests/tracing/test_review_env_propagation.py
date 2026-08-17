"""Review identity crosses the agent subprocess boundary — OB1.1 RED suite (part 2 of 3).

Wave plan: ``.ignorelocal/waves/04-observability-eval-wave-plan.md`` (PR OB1,
sub-wave OB1.1, finding O2). Test-plan doc: ``docs/test-plans/04-observability-eval.md``.

O2: subagents run in spawned CLI subprocesses, and
``agents/shared.py::spawn_agent_cli`` is the single choke point for all five
drivers. OB1.2 exports the review env (``MERGECRAFT_REVIEW_ID`` +
``MERGECRAFT_REVIEW_CORRELATION_KEY``, resolved by
``tracing/review_context.py::review_env_for_subprocess``) into the child
**after** ``agent_subprocess_env`` and via ``setdefault`` — one wiring covers
every driver.

Per the plan note for this suite, ``test_spawn_agent_cli_exports_review_env``
inspects the env actually handed to ``subprocess.Popen`` (captured by a fake
``Popen`` at the real call site), never a mock's kwargs on a patched helper —
mirroring the established pattern in
``tests/agents/test_privilege_drop_home_wiring.py``.

The ``review_context`` import is lazy (shared fixtures in
``tests/tracing/conftest.py``), which kept collection clean at RED-suite time.
All four tests carried non-strict ``xfail`` markers (``green after OB1.2``);
the markers were removed in the post-OB1.2 reconciliation (commit ``3891020``
made them XPASS), so all four are now clean real passes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

from mergecraft.agents.shared import spawn_agent_cli
from mergecraft.utils import privilege as privilege_module

if TYPE_CHECKING:
    from collections.abc import Callable

    from _pytest.monkeypatch import MonkeyPatch


@pytest.fixture
def captured_popen(monkeypatch: MonkeyPatch) -> dict[str, Any]:
    """Capture argv + kwargs exactly as handed to ``subprocess.Popen``.

    Non-root (``getuid`` → 501) so ``wrap_agent_command`` / ``agent_subprocess_env``
    are pass-throughs and the review-env injection is the only mutation under test.
    """
    import mergecraft.agents.shared as shared_module

    captured: dict[str, Any] = {}

    def _fake_popen(cmd: list[str], **kwargs: object) -> object:
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return MagicMock()

    monkeypatch.setattr(shared_module.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(privilege_module.os, "getuid", lambda: 501)
    return captured


def test_spawn_agent_cli_exports_review_env(
    captured_popen: dict[str, Any],
    monkeypatch: MonkeyPatch,
    review_context_module: Any,
    review_context_factory: Callable[..., Any],
) -> None:
    """O2 — the child process env carries the bound review id + correlation key."""
    rc = review_context_module
    monkeypatch.delenv("MERGECRAFT_REVIEW_ID", raising=False)
    monkeypatch.delenv("MERGECRAFT_REVIEW_CORRELATION_KEY", raising=False)
    ctx = review_context_factory(review_id="review-ob1-env", correlation_key="d" * 64)
    caller_env = {"PATH": "/usr/bin", "HOME": "/home/dev"}

    with rc.bind_review_context(ctx):
        spawn_agent_cli(["codex", "exec"], env=caller_env)

    env = captured_popen["kwargs"]["env"]
    assert isinstance(env, dict)
    assert env["MERGECRAFT_REVIEW_ID"] == "review-ob1-env"
    assert env["MERGECRAFT_REVIEW_CORRELATION_KEY"] == "d" * 64
    assert "MERGECRAFT_REVIEW_ID" not in caller_env, "the caller's env dict must not be mutated"


def test_child_process_reuses_the_inherited_review_id(
    monkeypatch: MonkeyPatch,
    review_context_module: Any,
) -> None:
    """O2 — a child started with the exported env resolves the SAME review id.

    Pins both branches of ``resolve_review_id()``: ``MERGECRAFT_REVIEW_ID``
    present → inherited verbatim (this is what lets the subprocess join the
    parent's review); absent → a fresh uuid4 per resolution.
    """
    rc = review_context_module

    monkeypatch.setenv("MERGECRAFT_REVIEW_ID", "review-inherited-0001")
    assert rc.resolve_review_id() == "review-inherited-0001"

    monkeypatch.delenv("MERGECRAFT_REVIEW_ID")
    first = rc.resolve_review_id()
    second = rc.resolve_review_id()
    assert first
    assert second
    assert first != second, "uuid4 fallback mints one review id per resolution, not a constant"


def test_privilege_error_still_surfaces_first(
    monkeypatch: MonkeyPatch,
    review_context_module: Any,
    review_context_factory: Callable[..., Any],
) -> None:
    """A fail-closed setpriv error must not be masked by review-env injection.

    OB1.2 injects the review env **after** ``agent_subprocess_env`` (which
    itself runs after ``wrap_agent_command``), so with root simulated and
    ``setpriv`` missing, ``spawn_agent_cli`` still raises the privilege-drop
    configuration error — never a review-env failure in its place.
    """
    from mergecraft.main import _ConfigurationError

    rc = review_context_module
    monkeypatch.setattr(privilege_module.os, "getuid", lambda: 0)
    monkeypatch.setattr(privilege_module.shutil, "which", lambda _name: None)

    with (
        rc.bind_review_context(review_context_factory()),
        pytest.raises(_ConfigurationError, match="setpriv"),
    ):
        spawn_agent_cli(["codex", "exec"], env={"PATH": "/usr/bin"})


def test_explicit_caller_value_wins(
    captured_popen: dict[str, Any],
    review_context_module: Any,
    review_context_factory: Callable[..., Any],
) -> None:
    """A driver that already set ``MERGECRAFT_REVIEW_ID`` keeps its value (setdefault)."""
    rc = review_context_module

    with rc.bind_review_context(review_context_factory(review_id="review-from-context")):
        spawn_agent_cli(
            ["codex", "exec"],
            env={"PATH": "/usr/bin", "MERGECRAFT_REVIEW_ID": "review-caller-pinned"},
        )

    env = captured_popen["kwargs"]["env"]
    assert isinstance(env, dict)
    assert env["MERGECRAFT_REVIEW_ID"] == "review-caller-pinned"
