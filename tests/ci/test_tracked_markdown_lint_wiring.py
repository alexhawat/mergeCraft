"""Plan 26 H4 — checker is wired into ``make lint`` and pre-commit."""

from __future__ import annotations

from tests.ci.workflow_support import REPO_ROOT

_SCRIPT = "scripts/check_tracked_markdown.py"
_MAKE_TARGET = "tracked-markdown-check"
_HOOK_ID = "mergecraft-tracked-markdown"


def test_makefile_lint_invokes_tracked_markdown_checker() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    lint_idx = makefile.index("\nlint:")
    next_target = makefile.find("\n\n", lint_idx + 1)
    lint_block = makefile[lint_idx : next_target if next_target != -1 else None]
    assert _SCRIPT in makefile
    assert _MAKE_TARGET in makefile
    assert _SCRIPT in lint_block or "tracked-markdown" in lint_block
    assert _MAKE_TARGET in lint_block


def test_pre_commit_invokes_tracked_markdown_checker() -> None:
    text = (REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert _SCRIPT in text
    assert f"id: {_HOOK_ID}" in text
