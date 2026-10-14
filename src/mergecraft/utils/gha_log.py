"""GitHub Actions workflow-command helpers for log groups and annotations."""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator


def _in_github_actions() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


def escape_workflow_command(value: str) -> str:
    """Escape a value for use inside a GitHub Actions workflow command.

    A ``::error::``/``::warning::``/``::group::`` payload is line-oriented and
    ``%``-delimited, so an unescaped ``%``, CR or LF lets PR-controlled text
    inject a second command (``::add-mask::``, a fake annotation, …). The
    escape keeps brackets and colons intact; CRLF collapses to one line.
    """
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _write_workflow_command(command: str, message: str) -> None:
    if not _in_github_actions():
        return
    sys.stdout.write(f"::{command}::{escape_workflow_command(message)}\n")
    sys.stdout.flush()


@contextmanager
def group(title: str) -> Iterator[None]:
    """Collapse nested log output under a GitHub Actions log group."""
    if _in_github_actions():
        sys.stdout.write(f"::group::{escape_workflow_command(title)}\n")
        sys.stdout.flush()
    try:
        yield
    finally:
        if _in_github_actions():
            sys.stdout.write("::endgroup::\n")
            sys.stdout.flush()


def notice(message: str) -> None:
    """Emit a ``::notice::`` workflow annotation."""
    _write_workflow_command("notice", message)


def warning(message: str) -> None:
    """Emit a ``::warning::`` workflow annotation."""
    _write_workflow_command("warning", message)


def error(message: str) -> None:
    """Emit a ``::error::`` workflow annotation."""
    _write_workflow_command("error", message)
