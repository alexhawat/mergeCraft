"""The CLI entrypoint exits through the named configuration code, not a traceback.

A malformed control-carrying ``MERGECRAFT_*`` variable (a typo'd
``MERGECRAFT_TRACING``, an unknown ``MERGECRAFT_TRACING_REGION``) reaches the
process through the same typed env models the Action path reads. ``main()`` is
the real entrypoint: it must catch the resulting configuration error and exit
with :data:`~mergecraft.cli.exits.CLI_CONFIGURATION_EXIT_CODE`, naming the
variable and never echoing its value. Before the guard it let the error escape
unhandled — a Rich traceback and exit code ``1``.

``typer.testing.CliRunner`` is deliberately not used: it enters Click's
``Command.main()`` and never calls ``mergecraft.cli.app.main()``, so it cannot
pin this behaviour. The test drives ``main()`` with a patched ``sys.argv`` and a
hermetic environment (no ambient config, no workspace ``.env``, no network).

Only ``MERGECRAFT_*`` keys are covered here: the ``config tracing`` subcommand
resolves the env layer through ``TracingEnv``, which has no ``INPUT_*`` alias.
The two control-carrying Action inputs are deliberately out of reach of this
subcommand and are pinned on the Action startup path instead
(`tests/action/test_env_fail_closed_startup.py`).
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

# (variable, a malformed value that is also a unique canary).
_MALFORMED_CASES = [
    ("MERGECRAFT_TRACING", "flase-canary-49a"),
    ("MERGECRAFT_TRACING_REGION", "north-pole-canary-49a"),
]


@pytest.fixture(autouse=True)
def _hermetic_cli_env(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Keep the entrypoint hermetic: no ambient config, event or workspace ``.env``.

    ``main()`` first runs the startup ``.env`` load, which walks up to the git
    root outside Actions. Running from a fresh temp directory inside a
    ``GIT_CEILING_DIRECTORIES`` fence makes that walk stop at a directory with no
    ``.env``; ``$MERGECRAFT_ENV`` and ``$MERGECRAFT_CONFIG`` are cleared so no
    real file from the operator's checkout is read. The malformed key under test
    is set by the test body, after this fixture has run.
    """
    for key in (
        "MERGECRAFT_ENV",
        "MERGECRAFT_CONFIG",
        "GITHUB_ACTIONS",
        "MERGECRAFT_TRACING",
        "MERGECRAFT_TRACING_REGION",
        "MERGECRAFT_TRACING_CONTENT",
        "MERGECRAFT_TRACING_EXPORT_UNTRUSTED_CONTENT",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.resolve()))
    monkeypatch.chdir(tmp_path)


@pytest.fixture(autouse=True)
def _rebind_cli_loguru_sink() -> Iterator[None]:
    """Rebind the loguru sink after the test so it does not outlive the capture.

    The root callback calls ``configure_logging(force=True)``, which installs an
    ``enqueue=True`` loguru sink bound to ``sys.stderr`` — under pytest, the
    per-test capture stream. The sink is process-global; left pointing at that
    stream, its background thread writes to a closed file once capture ends and
    a later test logs (``ValueError: I/O operation on closed file``). Re-running
    the same setup after the test detaches it and rebinds to the real stderr,
    matching ``tests/utils/test_log.py``'s isolation for the same global.
    """
    yield
    from mergecraft.utils.log import configure_logging

    configure_logging(force=True)


@pytest.mark.parametrize(
    ("key", "canary"),
    _MALFORMED_CASES,
    ids=[key for key, _ in _MALFORMED_CASES],
)
def test_malformed_tracing_env_exits_with_the_configuration_code(
    key: str,
    canary: str,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    """A malformed control variable exits through the configuration code, naming the variable."""
    from mergecraft.cli import app as cli_app
    from mergecraft.cli.exits import CLI_CONFIGURATION_EXIT_CODE

    monkeypatch.setattr(sys, "argv", ["mergecraft", "config", "tracing"])
    monkeypatch.setenv(key, canary)

    with pytest.raises(SystemExit) as excinfo:
        cli_app.main()

    assert excinfo.value.code == CLI_CONFIGURATION_EXIT_CODE, (
        f"a malformed {key} must exit through the configuration code, got "
        f"{excinfo.value.code!r} — not a traceback with code 1"
    )

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert key in combined, f"the error must name {key}: {combined!r}"
    assert canary not in combined, f"the error must never print the value: {combined!r}"


def test_valid_tracing_env_does_not_exit_as_a_configuration_error(
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    """Guard — a well-formed value renders the command and keeps the success exit."""
    from mergecraft.cli import app as cli_app
    from mergecraft.cli.exits import CLI_CONFIGURATION_EXIT_CODE, CLI_SUCCESS_EXIT_CODE

    monkeypatch.setattr(sys, "argv", ["mergecraft", "config", "tracing"])
    monkeypatch.setenv("MERGECRAFT_TRACING", "true")

    with pytest.raises(SystemExit) as excinfo:
        cli_app.main()

    assert excinfo.value.code == CLI_SUCCESS_EXIT_CODE
    assert excinfo.value.code != CLI_CONFIGURATION_EXIT_CODE
    rendered = capsys.readouterr()
    assert "tracing" in (rendered.out + rendered.err).lower(), (
        "the guard must actually run the command, not exit before it renders"
    )
