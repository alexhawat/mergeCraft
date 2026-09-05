"""``--resume`` is the local review-result cache, not ``resume_review``."""

from __future__ import annotations

import inspect
import re

from typer.testing import CliRunner

import mergecraft.offline_review as offline_mod
from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE
from mergecraft.offline_review import _run_offline_diff_review, run_offline_diff_review

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def test_offline_review_hot_path_does_not_export_resume_review() -> None:
    """Unit: ``offline_review`` must not export ``resume_review``."""
    assert not hasattr(offline_mod, "resume_review")


def test_recovery_module_does_not_export_resume_review() -> None:
    """Unit: ``reliability.recovery`` must not export ``resume_review``."""
    from mergecraft.reliability import recovery as recovery_mod

    assert not hasattr(recovery_mod, "resume_review")


def test_review_help_documents_resume_as_local_result_cache() -> None:
    """Happy: ``review --help`` describes ``--resume`` as the same cache as ``--use-cache``."""
    result = runner.invoke(app, ["review", "--help"], env=_DUMB_ENV)
    help_text = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, help_text
    compact = " ".join(help_text.split()).casefold()
    assert "--resume" in compact
    assert "--use-cache" in compact
    assert "result cache" in compact
    assert "does not restore" in compact
    assert "a live agent" in compact
    assert "checkpoint" in compact


def test_run_offline_diff_review_has_no_distinct_resume_parameter() -> None:
    """Unit: ``--resume`` is the same read policy as ``--use-cache`` (one bool)."""
    params = inspect.signature(run_offline_diff_review).parameters
    assert "use_cache" in params
    assert "resume" not in params


def test_run_offline_diff_review_body_has_no_distinct_resume_parameter() -> None:
    """Unit: the private runner also has only ``use_cache`` (CLI folds ``--resume``)."""
    params = inspect.signature(_run_offline_diff_review).parameters
    assert "use_cache" in params
    assert "resume" not in params
