"""``--resume`` is the local review-result cache, not ``resume_review``."""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}
_REPO_ROOT = Path(__file__).resolve().parents[2]
_OFFLINE = _REPO_ROOT / "src" / "mergecraft" / "offline_review.py"


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def test_offline_review_hot_path_does_not_import_resume_review() -> None:
    """Unit: ``offline_review.py`` must not import or call ``resume_review``."""
    source = _OFFLINE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if (
                module.endswith("reliability.recovery")
                or module == "mergecraft.reliability.recovery"
            ):
                names = {alias.name for alias in node.names}
                assert "resume_review" not in names
        if isinstance(node, ast.Attribute) and node.attr == "resume_review":
            raise AssertionError("offline_review.py must not call resume_review")
        if isinstance(node, ast.Name) and node.id == "resume_review":
            raise AssertionError("offline_review.py must not name resume_review")
    assert "resume_review" not in source


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

    from mergecraft.cli import diff_review_cmd

    option_source = inspect.getsource(diff_review_cmd.run)
    assert "same local result cache as --use-cache" in option_source
    assert "Does not restore a live" in option_source
