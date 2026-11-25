"""``gha_log.add_mask`` writes a raw, escaped ``::add-mask::`` command (#1558).

Every other workflow command goes through ``utils.gha_log`` and is written raw,
never through Rich. The mask was the exception: ``console.print`` with markup
on, so ``[...]`` was rewritten and the runner could mask a different string than
the one in ``$GITHUB_OUTPUT``; Rich could also wrap or colourise the line.

Contract: ``add_mask(value)`` writes exactly one ``::add-mask::`` line to
stdout, through ``escape_workflow_command``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from _pytest.capture import CaptureFixture


def test_add_mask_escapes_and_writes_to_stdout(capsys: CaptureFixture[str]) -> None:
    """Happy: ``%`` and a newline are escaped, and stdout gets the whole line."""
    from mergecraft.utils import gha_log

    assert hasattr(gha_log, "add_mask"), "mergecraft.utils.gha_log.add_mask is not implemented"
    gha_log.add_mask("a%b\nc")

    captured = capsys.readouterr()
    assert captured.out == "::add-mask::a%25b%0Ac\n"
    assert captured.err == ""


def test_add_mask_keeps_brackets_intact(capsys: CaptureFixture[str]) -> None:
    """Edge: ``[...]`` is literal text, never Rich markup."""
    from mergecraft.utils import gha_log

    assert hasattr(gha_log, "add_mask"), "mergecraft.utils.gha_log.add_mask is not implemented"
    gha_log.add_mask("tok[bold]en")

    assert capsys.readouterr().out == "::add-mask::tok[bold]en\n"
