"""W2 DA RED — #380 one engine over one ``ReviewSnapshot``.

Wave plan: ``.ignorelocal/waves/open-issues-sweep-2026-08-20d-a-engine-wave-plan.md``
Authoring wave: **W2**. Implementation: **W6**.

No ``ReviewSnapshot`` type is in the tree today. CLI (``review``), Action
(``mergecraft.main`` / ``gha``), and SCM (``conforming_review_request``) do not
yet enter one engine over one snapshot. Hidden ``diff-review`` must remain.
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import re
from typing import Any

import pytest
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}

_SNAPSHOT_MODULES = (
    "mergecraft.review.snapshot",
    "mergecraft.review_snapshot",
    "mergecraft.engine.snapshot",
    "mergecraft.engine",
    "mergecraft.review",
)

_XFAIL_W6 = pytest.mark.xfail(
    reason="green after W6: ReviewSnapshot conformance",
    strict=False,
)


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def _find_review_snapshot() -> Any:
    for name in _SNAPSHOT_MODULES:
        spec = importlib.util.find_spec(name)
        if spec is None:
            continue
        module = importlib.import_module(name)
        snapshot = getattr(module, "ReviewSnapshot", None)
        if snapshot is not None:
            return snapshot
    pytest.fail("ReviewSnapshot type is not in the tree")


def _find_engine_run() -> Any:
    engine_modules = (
        "mergecraft.engine",
        "mergecraft.review.engine",
        "mergecraft.review.snapshot",
        "mergecraft.review_snapshot",
    )
    for name in engine_modules:
        spec = importlib.util.find_spec(name)
        if spec is None:
            continue
        module = importlib.import_module(name)
        for attr in ("run_review", "execute_review", "run_from_snapshot"):
            fn = getattr(module, attr, None)
            if callable(fn):
                return fn
    pytest.fail("no shared engine callable that accepts ReviewSnapshot")


# ── Already true — do not xfail; do not require deleting hidden diff-review ───


def test_review_is_the_documented_command() -> None:
    """Happy: ``review`` is listed; ``diff-review`` stays hidden (W6 must keep the alias)."""
    result = runner.invoke(app, ["--help"], env=_DUMB_ENV)
    help_text = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, help_text
    assert "review" in help_text.casefold()
    assert "diff-review" not in help_text


def test_hidden_diff_review_alias_remains_invocable() -> None:
    """Edge: hidden ``diff-review`` still serves ``--help`` (do not delete the alias)."""
    result = runner.invoke(app, ["diff-review", "--help"], env=_DUMB_ENV)
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, combined
    names = {cmd.name for cmd in app.registered_commands if cmd.name}
    assert "diff-review" in names
    hidden = [cmd for cmd in app.registered_commands if cmd.name == "diff-review"]
    assert hidden
    assert hidden[0].hidden is True


# ── W6 conformance (xfail) ────────────────────────────────────────────────────


@_XFAIL_W6
def test_review_snapshot_type_exists() -> None:
    """Unit: ``ReviewSnapshot`` is a public type CLI / Action / SCM can share."""
    snapshot = _find_review_snapshot()
    assert inspect.isclass(snapshot)
    assert snapshot.__name__ == "ReviewSnapshot"


@_XFAIL_W6
def test_shared_engine_accepts_review_snapshot() -> None:
    """Unit: one engine callable takes a ``ReviewSnapshot`` (or is annotated as such)."""
    snapshot = _find_review_snapshot()
    run = _find_engine_run()
    params = inspect.signature(run).parameters
    annotated = any(
        parameter.annotation is snapshot or "ReviewSnapshot" in str(parameter.annotation)
        for parameter in params.values()
    )
    named = any(name in {"snapshot", "review_snapshot"} for name in params)
    assert annotated or named, inspect.signature(run)


@_XFAIL_W6
def test_cli_review_path_builds_a_review_snapshot() -> None:
    """Integration: the CLI review module constructs ``ReviewSnapshot``."""
    from mergecraft.cli import diff_review_cmd

    source = inspect.getsource(diff_review_cmd)
    assert "ReviewSnapshot" in source


@_XFAIL_W6
def test_action_path_builds_a_review_snapshot() -> None:
    """Integration: the Action/runtime entry constructs ``ReviewSnapshot``."""
    import mergecraft.main as action_main

    source = inspect.getsource(action_main)
    assert "ReviewSnapshot" in source


@_XFAIL_W6
def test_scm_conforming_request_builds_or_feeds_a_review_snapshot() -> None:
    """Integration: SCM webhook review requests enter the same snapshot type."""
    from mergecraft.scm import webhooks

    source = inspect.getsource(webhooks)
    assert "ReviewSnapshot" in source
    snapshot = _find_review_snapshot()
    request = getattr(webhooks, "ConformingReviewRequest", None)
    if request is not None and inspect.isclass(request):
        hints = getattr(request, "__annotations__", {})
        blob = " ".join(str(value) for value in hints.values()) + str(request)
        if "ReviewSnapshot" not in blob and "snapshot" not in blob.casefold():
            # Callable path is enough: conforming_review_request must mention the type.
            fn_source = inspect.getsource(webhooks.conforming_review_request)
            assert "ReviewSnapshot" in fn_source
    else:
        assert snapshot is not None
