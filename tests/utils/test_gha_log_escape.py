"""N6 / CF4.6 — one public workflow-command escaper (CF-D14).

GitHub Actions interprets ``::error::``/``::warning::``/``::group::`` lines
and the ``%``/CR/LF escape sequences inside them. Any message that can carry
PR-controlled text on the failure path must run through the same escaper so a
newline cannot inject a second command (``::add-mask::``, fake annotations)
and Rich markup cannot mangle the line.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


def test_escape_workflow_command_escapes_percent_cr_and_lf() -> None:
    from mergecraft.utils.gha_log import escape_workflow_command

    assert escape_workflow_command("a%b\rc\nd") == "a%25b%0Dc%0Ad"


def test_escape_workflow_command_preserves_brackets_and_colons() -> None:
    from mergecraft.utils.gha_log import escape_workflow_command

    assert escape_workflow_command("::add-mask::x [bold]") == "::add-mask::x [bold]"


def test_escape_workflow_command_collapses_crlf_into_one_line() -> None:
    from mergecraft.utils.gha_log import escape_workflow_command

    escaped = escape_workflow_command("first\r\nsecond")
    assert "\n" not in escaped
    assert "\r" not in escaped
    assert escaped == "first%0D%0Asecond"


def test_error_annotation_routes_through_the_escaper(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    from mergecraft.utils import gha_log

    gha_log.error("boom 100%\nsecond line")
    output = capsys.readouterr().out
    assert output.count("::error::") == 1, output
    assert "%25" in output, output
    assert "%0A" in output, output
