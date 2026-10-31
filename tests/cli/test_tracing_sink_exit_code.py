"""A mistyped tracing sink exits through the configuration code on the CLI (#930).

The Action path is pinned in ``tests/action/test_tracing_sink_configuration_error.py``.
Here the same typo arrives through ``MERGECRAFT_TRACING_TO`` or the
``--tracing-to`` flag, and the process must exit with
:data:`~mergecraft.cli.exits.CLI_CONFIGURATION_EXIT_CODE` naming the variable and
the value, rather than silently writing a local trace file for a sink the
operator never asked for.
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

_TYPO = "logfier"
_PATCH = "diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n@@ -1 +1,2 @@\n a\n+b\n"


@pytest.fixture(autouse=True)
def _hermetic_cli_env(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    for key in (
        "MERGECRAFT_ENV",
        "MERGECRAFT_CONFIG",
        "GITHUB_ACTIONS",
        "MERGECRAFT_TRACING",
        "MERGECRAFT_TRACING_TO",
        "MERGECRAFT_TRACING_REGION",
        "MERGECRAFT_TRACING_CONTENT",
        "MERGECRAFT_TRACING_EXPORT_UNTRUSTED_CONTENT",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.resolve()))
    monkeypatch.chdir(tmp_path)


@pytest.fixture(autouse=True)
def _rebind_cli_loguru_sink() -> Iterator[None]:
    yield
    from mergecraft.utils.log import configure_logging

    configure_logging(force=True)


def _run(argv: list[str], monkeypatch: MonkeyPatch) -> int | str | None:
    from mergecraft.cli import app as cli_app

    monkeypatch.setattr(sys, "argv", ["mergecraft", *argv])
    with pytest.raises(SystemExit) as excinfo:
        cli_app.main()
    return excinfo.value.code


def test_config_tracing_with_a_mistyped_env_sink_exits_with_the_configuration_code(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    from mergecraft.cli.exits import CLI_CONFIGURATION_EXIT_CODE

    monkeypatch.setenv("MERGECRAFT_TRACING", "true")
    monkeypatch.setenv("MERGECRAFT_TRACING_TO", _TYPO)

    code = _run(["config", "tracing"], monkeypatch)

    assert code == CLI_CONFIGURATION_EXIT_CODE
    out = capsys.readouterr()
    combined = out.out + out.err
    assert "MERGECRAFT_TRACING_TO" in combined
    assert _TYPO in combined


def test_review_with_a_mistyped_sink_flag_exits_with_the_configuration_code(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    from mergecraft.cli.exits import CLI_CONFIGURATION_EXIT_CODE

    patch = tmp_path / "change.patch"
    patch.write_text(_PATCH, encoding="utf-8")

    code = _run(
        ["review", "--diff", str(patch), "--dry-run", "--tracing", "--tracing-to", _TYPO],
        monkeypatch,
    )

    assert code == CLI_CONFIGURATION_EXIT_CODE
    out = capsys.readouterr()
    combined = out.out + out.err
    assert _TYPO in combined


def test_a_mistyped_sink_with_tracing_off_does_not_fail_the_command(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    from mergecraft.cli.exits import CLI_CONFIGURATION_EXIT_CODE, CLI_SUCCESS_EXIT_CODE

    monkeypatch.setenv("MERGECRAFT_TRACING", "false")
    monkeypatch.setenv("MERGECRAFT_TRACING_TO", _TYPO)

    code = _run(["config", "tracing"], monkeypatch)

    assert code == CLI_SUCCESS_EXIT_CODE
    assert code != CLI_CONFIGURATION_EXIT_CODE
    capsys.readouterr()


@pytest.mark.parametrize("sink", ["logfire", "otel", "local_files"])
def test_known_sinks_keep_the_success_exit(
    sink: str, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE

    monkeypatch.setenv("MERGECRAFT_TRACING", "true")
    monkeypatch.setenv("MERGECRAFT_TRACING_TO", sink)

    assert _run(["config", "tracing"], monkeypatch) == CLI_SUCCESS_EXIT_CODE
    capsys.readouterr()
