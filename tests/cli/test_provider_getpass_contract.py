"""``_cancelable_getpass`` contract: cancel raises, a value comes back stripped (#1564).

The helper never returns ``None``: both cancel paths raise ``typer.Exit(0)`` after
printing ``canceled.``, so the five ``if … is None: return`` guards after its call
sites are unreachable. The annotation said ``str | None``; it says ``str``.
"""

from __future__ import annotations

import typing
from typing import TYPE_CHECKING

import pytest
import typer

from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE
from mergecraft.cli.provider_cmd import _cancelable_getpass

if TYPE_CHECKING:
    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch


def _stub_prompt(monkeypatch: MonkeyPatch, answer: str) -> None:
    monkeypatch.setattr("mergecraft.cli.provider_cmd.getpass.getpass", lambda _prompt="": answer)


def test_empty_entry_cancels_with_success_exit(
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    """Edge: an empty entry is a cancel, not an empty credential."""
    _stub_prompt(monkeypatch, "")

    with pytest.raises(typer.Exit) as excinfo:
        _cancelable_getpass("API key (Enter to cancel): ")

    assert excinfo.value.exit_code == CLI_SUCCESS_EXIT_CODE
    assert "canceled." in capsys.readouterr().err


def test_eof_cancels_with_success_exit(
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    """Error: EOF on the prompt is a cancel, not a crash."""

    def raise_eof(_prompt: str = "") -> str:
        raise EOFError

    monkeypatch.setattr("mergecraft.cli.provider_cmd.getpass.getpass", raise_eof)

    with pytest.raises(typer.Exit) as excinfo:
        _cancelable_getpass("API key (Enter to cancel): ")

    assert excinfo.value.exit_code == CLI_SUCCESS_EXIT_CODE
    assert "canceled." in capsys.readouterr().err


def test_value_is_returned_stripped(monkeypatch: MonkeyPatch) -> None:
    """Happy: surrounding whitespace never reaches the stored credential."""
    _stub_prompt(monkeypatch, "  placeholder-key  ")

    assert _cancelable_getpass("API key (Enter to cancel): ") == "placeholder-key"


def test_return_annotation_is_str() -> None:
    """Bug: the declared return type must match the only paths that can return."""
    hints = typing.get_type_hints(_cancelable_getpass)

    assert hints["return"] is str
