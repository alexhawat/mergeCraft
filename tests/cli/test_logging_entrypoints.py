"""Every CLI entrypoint leaves one log patcher that redacts and carries context.

The root callback is the single logging hook shared by ``review``,
``diff-review``, ``mcp serve`` and ``gha``. After it runs, a record must carry
the bound run-correlation fields *and* have secret-shaped values removed from
its message. These tests drive the real callback for each entrypoint (through
``--help`` so no command body executes) and then observe a locally captured
record.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from typer.testing import CliRunner

import mergecraft.utils.log as log_mod
from mergecraft.cli.app import app
from mergecraft.cli.global_surface import apply_global_cli_options
from mergecraft.utils.log import bind_run_context, clear_run_context, configure_logging

_CANARY = "ghp_AbCdEfGhIjKlMnOpQrStUvWxYz1234567890"
runner = CliRunner()

_ENTRYPOINTS = [
    pytest.param(["review", "--help"], id="review"),
    pytest.param(["diff-review", "--help"], id="diff-review"),
    pytest.param(["mcp", "serve", "--help"], id="mcp-serve"),
    pytest.param(["gha", "--help"], id="gha"),
]


@pytest.fixture(autouse=True)
def _restore_log_patcher() -> Iterator[None]:
    """Restore the process-wide patcher and redactor slot after each test."""
    yield
    setter = getattr(log_mod, "set_message_redactor", None)
    if setter is not None:
        setter(None)
    configure_logging(force=True)
    clear_run_context()


def _capture_context_and_message() -> tuple[dict[str, Any], str]:
    """Log one canary record and return its ``extra`` mapping and message text."""
    captured: list[Any] = []
    sink_id = log_mod.logger.add(lambda message: captured.append(message), level="TRACE")
    try:
        bind_run_context(run_id="run-cli", repo="acme/demo", pr=5, phase="review")
        log_mod.logger.warning("planted {} in a message", _CANARY)
    finally:
        log_mod.logger.remove(sink_id)
    assert captured, "no log record reached the local sink"
    record = captured[-1].record
    return dict(record["extra"]), str(record["message"])


class _FakeCliContext:
    """Minimal ``typer.Context`` stand-in: the callback only stores ``ctx.obj``."""

    obj: Any = None


def test_root_callback_keeps_context_and_redaction() -> None:
    """The callback installs both behaviours in one composed patcher."""
    apply_global_cli_options(
        _FakeCliContext(),
        output_format="table",
        quiet=False,
        verbose=False,
        log_level=None,
        color="auto",
    )
    extra, message = _capture_context_and_message()
    assert extra.get("run_id") == "run-cli"
    assert extra.get("repo") == "acme/demo"
    assert extra.get("pr") == 5
    assert extra.get("phase") == "review"
    assert _CANARY not in message


@pytest.mark.parametrize("argv", _ENTRYPOINTS)
def test_entrypoint_logging_state_keeps_context_and_redaction(argv: list[str]) -> None:
    """Invoking an entrypoint through the root callback leaves both installed."""
    result = runner.invoke(app, argv)
    assert result.exit_code == 0, result.stdout + result.stderr
    extra, message = _capture_context_and_message()
    assert extra.get("run_id") == "run-cli"
    assert extra.get("repo") == "acme/demo"
    assert _CANARY not in message
